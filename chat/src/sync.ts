// Connection tracking, the outbox, and applying server events to the store.
//
// Every message is saved locally first with status "pending". The outbox sends
// pending messages oldest-first whenever the connection is up, and stops as soon
// as it drops; the rest go out automatically when it comes back.
import type { Contact, MediaKind, MediaRef, Message } from './types';
import {
  addContact,
  addGroupMembers,
  addMessage,
  createGroup,
  ensureDirectChat,
  findContactByPhone,
  findMessage,
  getChat,
  getContact,
  getState,
  isOnline,
  isRealChat,
  markChatRead,
  pendingMessages,
  realData,
  replaceData,
  setCall,
  setConnection,
  setPresence,
  setShowDemoState,
  setTyping,
  showToast,
  subscribe,
  updateMessage,
} from './store';
import { server, type Profile, type ServerEvent } from './mock/server';
import { handleCallEvent, handleRealCall, handleRtc, onConnectionLost } from './calls';
import { addRealContact, lookupPhones, net, sendReadReceipts, sendRealMessage, setRealHooks, startReal } from './real';
import type { RemoteUser } from './net/client';
import { createSeedState, ensureSeedMedia } from './mock/seed';
import { clearMediaExcept, putMedia, rememberMediaUrl } from './storage/media';
import { clearState, saveShowDemo, saveSimulatedOffline } from './storage/local';
import { chatLook, messagePreview, plural, uid } from './utils';

/** Chat the user is looking at; incoming messages there don't raise a toast. */
let activeChat: string | null = null;
export function setActiveChat(chatId: string | null) {
  activeChat = chatId;
}

// ---- sending --------------------------------------------------------------------------

export function sendText(chatId: string, text: string) {
  const trimmed = text.trim();
  if (!trimmed) return;
  addMessage({ id: uid(), chatId, author: 'me', text: trimmed, createdAt: Date.now(), status: 'pending' });
  flushOutbox();
}

export const MAX_FILE_SIZE = 100 * 1024 * 1024;

export async function sendMedia(chatId: string, file: File, caption = '') {
  const kind: MediaKind | null = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video' : null;
  if (!kind) {
    showToast(`«${file.name}» — можно отправить только фото или видео`, 'warning');
    return;
  }
  if (file.size > MAX_FILE_SIZE) {
    showToast(`«${file.name}» больше 100 МБ`, 'warning');
    return;
  }
  const id = uid();
  const media: MediaRef = { id, kind, mime: file.type, name: file.name, size: file.size, ...(await probeMedia(file, kind)) };
  // The file goes to IndexedDB before the message exists, so a pending message
  // always has its photo/video available, even after a reload without internet.
  try {
    await putMedia(id, file);
  } catch {
    showToast('Не удалось сохранить файл на устройстве — не хватает места?', 'warning');
    return;
  }
  rememberMediaUrl(id, file);
  addMessage({ id: uid(), chatId, author: 'me', text: caption.trim(), media, createdAt: Date.now(), status: 'pending' });
  flushOutbox();
}

/** Width/height (and duration for video) so the bubble can reserve space before the file loads. */
function probeMedia(file: File, kind: MediaKind): Promise<Partial<MediaRef>> {
  const url = URL.createObjectURL(file);
  const done = (result: Partial<MediaRef>) => {
    URL.revokeObjectURL(url);
    return result;
  };
  return new Promise<Partial<MediaRef>>((resolve) => {
    const timeout = setTimeout(() => resolve({}), 4000);
    const finish = (r: Partial<MediaRef>) => {
      clearTimeout(timeout);
      resolve(r);
    };
    if (kind === 'image') {
      const img = new Image();
      img.onload = () => finish({ width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = () => finish({});
      img.src = url;
    } else {
      const video = document.createElement('video');
      video.preload = 'metadata';
      video.muted = true;
      video.onloadedmetadata = () =>
        finish({ width: video.videoWidth || undefined, height: video.videoHeight || undefined, duration: isFinite(video.duration) ? video.duration : undefined });
      video.onerror = () => finish({});
      video.src = url;
    }
  }).then(done);
}

let flushing = false;
let retryTimer: number | undefined;

export async function flushOutbox() {
  if (flushing || !isOnline()) return;
  const queue = pendingMessages();
  if (!queue.length) return;

  flushing = true;
  clearTimeout(retryTimer);
  const wasBacklog = queue.length > 1 || Date.now() - queue[0].createdAt > 5000;
  let sent = 0;
  setConnection({ syncing: queue.length });
  try {
    for (const message of queue) {
      if (!isOnline()) break;
      if (findMessage(message.chatId, message.id)?.status !== 'pending') continue;
      const chat = getChat(message.chatId);
      if (!chat) continue;
      const real = isRealChat(chat);
      // Real chats wait for the server; demo chats for the (simulated) network.
      if (real && !net.isOnline()) continue;
      try {
        const sentAt = real ? await sendRealMessage(message, chat) : await server.send(message, chat);
        updateMessage(message.chatId, message.id, { status: 'sent', sentAt });
        sent++;
        setConnection({ syncing: Math.max(0, queue.length - sent) });
      } catch {
        if (real) continue; // the server dropped; demo messages can still go
        break; // connection dropped mid-way; the rest stays pending
      }
    }
  } finally {
    flushing = false;
    setConnection({ syncing: 0 });
  }
  if (sent && wasBacklog) showToast(`Синхронизация завершена: отправлено ${sent} ${plural(sent, 'сообщение', 'сообщения', 'сообщений')}`, 'success');
  // Anything written while we were busy, or left after a failure, gets another go.
  // (Real chats are retried when the server connection comes back.)
  const left = pendingMessages().filter((m) => !isRealChat(getChat(m.chatId)) || net.isOnline());
  if (left.length) retryTimer = window.setTimeout(flushOutbox, isOnline() ? 1000 : 3000);
}

// ---- receiving -----------------------------------------------------------------------

const ORDER: Record<Message['status'], number> = { pending: 0, sent: 1, delivered: 2, read: 3 };

function applyEvent(event: ServerEvent) {
  switch (event.type) {
    case 'delivered': {
      const m = findMessage(event.chatId, event.id);
      if (m && ORDER[m.status] < ORDER.delivered) updateMessage(event.chatId, event.id, { status: 'delivered', deliveredAt: event.at });
      break;
    }
    case 'read':
      for (const id of event.ids) {
        const m = findMessage(event.chatId, id);
        if (m && m.status !== 'read') updateMessage(event.chatId, id, { status: 'read', readAt: event.at, deliveredAt: m.deliveredAt ?? event.at });
      }
      break;
    case 'message': {
      const m = event.message;
      // Someone from my contacts wrote first: the direct chat appears in the list.
      if (!getChat(m.chatId) && getContact(m.chatId)) ensureDirectChat(m.chatId);
      const chat = getChat(m.chatId);
      if (!chat) break;
      addMessage(m);
      notifyIncoming(m);
      break;
    }
    case 'presence':
      setPresence(event.contactId, event.online, event.at);
      break;
    case 'typing':
      setTyping(event.chatId, event.contactId);
      break;
    default:
      handleCallEvent(event);
  }
}

/** Toast for a new message unless I'm looking at that chat. */
function notifyIncoming(m: Message) {
  const chat = getChat(m.chatId);
  if (!chat) return;
  const sender = m.senderId ? getContact(m.senderId) : undefined;
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
  if (m.chatId !== activeChat || hidden) {
    const { name } = chatLook(chat, getState().contacts);
    const who = chat.kind === 'group' && sender ? `${name} · ${sender.name.split(' ')[0]}` : name;
    showToast(`${who}: ${messagePreview(m)}`, 'message', chat.id, sender?.id);
  }
}

/** Mark the chat read, and tell real senders that I've read their messages. */
export function readChat(chatId: string) {
  const unread = (getState().messages[chatId] ?? []).filter((m) => m.author === 'them' && m.status !== 'read');
  if (!unread.length) return;
  markChatRead(chatId);
  sendReadReceipts(unread);
}

// ---- connection ------------------------------------------------------------------------

export function setSimulatedOffline(value: boolean) {
  saveSimulatedOffline(value);
  setConnection({ simulatedOffline: value });
}

let lastOnline: boolean | null = null;

function onConnectionChange() {
  const online = isOnline();
  if (online === lastOnline) return;
  const first = lastOnline === null;
  lastOnline = online;
  server.setClientOnline(online);
  if (online) {
    if (!first) showToast('Соединение восстановлено', 'success');
    flushOutbox();
  } else {
    // Without a connection we can't know who is typing.
    for (const chatId of Object.keys(getState().typing)) setTyping(chatId, undefined);
    onConnectionLost();
    if (!first) showToast('Нет подключения. Сообщения сохранятся и отправятся позже', 'warning');
  }
}

export function startSync() {
  window.addEventListener('online', () => setConnection({ browserOnline: true }));
  window.addEventListener('offline', () => setConnection({ browserOnline: false }));
  subscribe(onConnectionChange);

  const s = getState();
  server.start(s.contacts, s.chats, s.messages, applyEvent);
  server.setQuiet(!s.showDemo);
  setRealHooks({
    onOnline: () => flushOutbox(),
    onIncoming: notifyIncoming,
    onCall: (m) => handleRealCall(m as never),
    onRtc: (m) => handleRtc(m as never),
    onLost: () => onConnectionLost(true),
  });
  startReal();
  onConnectionChange();
  ensureSeedMedia();

  // Ask the browser not to evict our IndexedDB/localStorage under storage pressure.
  navigator.storage?.persist?.().catch(() => {});
}

export async function resetDemo() {
  onConnectionLost();
  setCall(null);
  server.stop();
  clearState();
  // My real contacts and chats stay — only the demo part is reset.
  const real = realData();
  const keep = new Set(Object.values(real.messages).flat().flatMap((m) => (m.media ? [m.media.id] : [])));
  await clearMediaExcept(keep).catch(() => {});
  const seed = createSeedState();
  replaceData({ ...seed, contacts: [...seed.contacts, ...real.contacts], chats: [...seed.chats, ...real.chats], messages: { ...seed.messages, ...real.messages } });
  server.start(seed.contacts, seed.chats, seed.messages, applyEvent);
  server.setClientOnline(isOnline());
  await ensureSeedMedia();
  showToast('Демо-данные восстановлены', 'info');
}

// ---- contacts & groups -----------------------------------------------------------------

export type LookupResult =
  | { status: 'found'; profile: Profile; real: false }
  | { status: 'found'; profile: Profile; real: true; user: RemoteUser }
  | { status: 'existing'; contact: Contact }
  | { status: 'not-found' }
  | { status: 'offline' }
  | { status: 'server-offline' }
  | { status: 'error' };

/**
 * Who uses this number: the real server when I'm registered, the demo directory otherwise.
 */
export async function lookupPhone(phone: string): Promise<LookupResult> {
  const s = getState();
  const existing = s.contacts.find((c) => c.phone === phone && (c.real || !s.account));
  if (existing) return { status: 'existing', contact: existing };
  if (!isOnline()) return { status: 'offline' };
  if (s.account) {
    if (!net.isOnline()) return { status: 'server-offline' };
    try {
      const [user] = await lookupPhones([phone]);
      if (!user) return { status: 'not-found' };
      const profile: Profile = { name: user.name, phone: user.phone, gender: 'u', about: user.about ?? '', colors: user.colors ?? ['#a1c4fd', '#c2e9fb'] };
      return { status: 'found', profile, real: true, user };
    } catch {
      return net.isOnline() ? { status: 'error' } : { status: 'server-offline' };
    }
  }
  try {
    const profile = await server.lookup(phone);
    return profile ? { status: 'found', profile, real: false } : { status: 'not-found' };
  } catch {
    return isOnline() ? { status: 'error' } : { status: 'offline' };
  }
}

/** Save a found person to my contacts (under the name I chose). */
export function saveContact(found: Extract<LookupResult, { status: 'found' }>, name: string): Contact {
  if (found.real) return addRealContact(found.user, name);
  const profile = found.profile;
  const existing = findContactByPhone(profile.phone);
  if (existing) return existing;
  const contact: Contact = {
    ...profile,
    id: 'u' + profile.phone,
    name: name.trim() || profile.name,
    online: Math.random() < 0.5,
    lastSeen: Date.now() - Math.round(Math.random() * 3_600_000),
  };
  addContact(contact);
  server.registerContact(contact);
  server.registerChat(ensureDirectChat(contact.id));
  return contact;
}

/** Phone book import: which of these numbers are on the server. */
export async function findRegistered(phones: string[]): Promise<RemoteUser[]> {
  const me = getState().account?.phone;
  const users = await lookupPhones(phones.filter((p) => p !== me));
  return users.filter((u) => u.phone !== me);
}

/** Show/hide the demo contacts and pause their simulated activity. */
export function setShowDemo(show: boolean) {
  saveShowDemo(show);
  setShowDemoState(show);
  server.setQuiet(!show);
}

export function openDirectChat(contactId: string) {
  const chat = ensureDirectChat(contactId);
  server.registerChat(chat);
  return chat.id;
}

export function newGroup(title: string, memberIds: string[]) {
  const chat = createGroup(title, memberIds);
  server.registerChat(chat);
  return chat.id;
}

export function addMembers(chatId: string, memberIds: string[]) {
  addGroupMembers(chatId, memberIds);
  const chat = getChat(chatId);
  if (chat) server.registerChat(chat);
}
