// Connection tracking, the outbox, and applying server events to the store.
//
// Every message is saved locally first with status "pending". The outbox sends
// pending messages oldest-first whenever the connection is up, and stops as soon
// as it drops; the rest go out automatically when it comes back.
import type { MediaKind, MediaRef, Message } from './types';
import {
  addMessage,
  findMessage,
  getContact,
  getState,
  isOnline,
  pendingMessages,
  replaceData,
  setConnection,
  setPresence,
  setTyping,
  showToast,
  subscribe,
  updateMessage,
} from './store';
import { server, type ServerEvent } from './mock/server';
import { createSeedState, ensureSeedMedia } from './mock/seed';
import { clearMedia, putMedia, rememberMediaUrl } from './storage/media';
import { clearState, saveSimulatedOffline } from './storage/local';
import { messagePreview, uid } from './utils';

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
      try {
        const sentAt = await server.send(message);
        updateMessage(message.chatId, message.id, { status: 'sent', sentAt });
        sent++;
        setConnection({ syncing: Math.max(0, queue.length - sent) });
      } catch {
        break; // connection dropped mid-way; the rest stays pending
      }
    }
  } finally {
    flushing = false;
    setConnection({ syncing: 0 });
  }
  if (sent && wasBacklog) showToast(`Синхронизация завершена: отправлено ${sent} ${plural(sent, 'сообщение', 'сообщения', 'сообщений')}`, 'success');
  // Anything written while we were busy, or left after a failure, gets another go.
  if (pendingMessages().length) retryTimer = window.setTimeout(flushOutbox, isOnline() ? 300 : 3000);
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
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
      addMessage(event.message);
      const contact = getContact(event.message.chatId);
      const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
      if (contact && (event.message.chatId !== activeChat || hidden)) {
        showToast(`${contact.name}: ${messagePreview(event.message)}`, 'message', contact.id);
      }
      break;
    }
    case 'presence':
      setPresence(event.contactId, event.online, event.at);
      break;
    case 'typing':
      setTyping(event.chatId, event.typing);
      break;
  }
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
    for (const chatId of Object.keys(getState().typing)) setTyping(chatId, false);
    if (!first) showToast('Нет подключения. Сообщения сохранятся и отправятся позже', 'warning');
  }
}

export function startSync() {
  window.addEventListener('online', () => setConnection({ browserOnline: true }));
  window.addEventListener('offline', () => setConnection({ browserOnline: false }));
  subscribe(onConnectionChange);

  const s = getState();
  server.start(s.contacts, s.messages, applyEvent);
  onConnectionChange();
  ensureSeedMedia();

  // Ask the browser not to evict our IndexedDB/localStorage under storage pressure.
  navigator.storage?.persist?.().catch(() => {});
}

export async function resetDemo() {
  server.stop();
  clearState();
  await clearMedia().catch(() => {});
  const seed = createSeedState();
  replaceData(seed);
  server.start(seed.contacts, seed.messages, applyEvent);
  server.setClientOnline(isOnline());
  await ensureSeedMedia();
  showToast('Демо-данные восстановлены', 'info');
}
