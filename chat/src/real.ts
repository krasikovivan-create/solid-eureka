// Everything about the real server that the rest of the app needs:
// my account, real contacts, sending/receiving messages, receipts, presence, typing.
// Real people get ids "p<phone>"; their direct chat has the same id.
import type { Account, Chat, Contact, Message } from './types';
import {
  addContact,
  addMessage,
  ensureDirectChat,
  findMessage,
  findMessageAnywhere,
  getChat,
  getContact,
  getState,
  isOnline,
  patchContact,
  setAccountState,
  setNet,
  setTyping,
  subscribe,
  updateMessage,
  upsertChat,
} from './store';
import { NetClient, normalizeServerUrl, type RemoteUser, type ServerMsg } from './net/client';
import { saveAccount, saveServerUrl } from './storage/local';
import { getMedia, MEDIA_READY_EVENT, putMedia } from './storage/media';
import { pickGroupColors } from './utils';

// Hooks set by sync.ts / calls.ts (avoids import cycles at load time).
const hooks = {
  onOnline: () => {},
  onIncoming: (_m: Message) => {},
  onCall: (_m: ServerMsg) => {},
  onRtc: (_m: ServerMsg) => {},
  onLost: () => {},
};
export function setRealHooks(h: Partial<typeof hooks>) {
  Object.assign(hooks, h);
}

export const net = new NetClient({
  onStatus: (status, error) => {
    setNet({ status, error });
    if (status !== 'online') {
      clearRealTyping();
      hooks.onLost();
    }
  },
  onWelcome: () => {
    watchContacts();
    hooks.onOnline();
  },
  onMessage: (m) => handle(m),
});

export const realId = (phone: string) => 'p' + phone;

// ---- connection & account -------------------------------------------------------------------

export function startReal() {
  let last = '';
  const reconcile = () => {
    const s = getState();
    const key = [s.net.url, s.account?.phone, s.account?.token, isOnline(s)].join('|');
    if (key === last) return;
    last = key;
    net.configure(s.net.url, s.account, isOnline(s));
  };
  subscribe(reconcile);
  reconcile();
  // New real contacts → start watching their presence.
  let lastReal = '';
  subscribe(() => {
    const phones = getState().contacts.filter((c) => c.real).map((c) => c.phone).join();
    if (phones !== lastReal) {
      lastReal = phones;
      if (net.isOnline()) watchContacts();
    }
  });
}

function randomToken() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * The secret for a number is kept even after "sign out": the server ties the number to it,
 * so signing in again on this device with the same number works.
 */
const TOKENS_KEY = 'svyaz.tokens';
function tokenFor(phone: string) {
  let map: Record<string, string> = {};
  try {
    map = JSON.parse(localStorage.getItem(TOKENS_KEY) || '{}');
  } catch {
    /* ignore */
  }
  if (!map[phone]) {
    map[phone] = randomToken();
    try {
      localStorage.setItem(TOKENS_KEY, JSON.stringify(map));
    } catch {
      /* ignore */
    }
  }
  return map[phone];
}

/** Register (or re-register) this device with my number and name. */
export function signIn(phone: string, name: string, serverUrl: string) {
  const url = normalizeServerUrl(serverUrl);
  const prev = getState().account;
  const account: Account = { phone, name: name.trim(), token: prev?.phone === phone ? prev.token : tokenFor(phone) };
  saveServerUrl(url);
  setNet({ url, error: undefined });
  saveAccount(account);
  setAccountState(account);
  net.retryNow();
}

export function updateMyName(name: string) {
  const a = getState().account;
  if (!a || !name.trim()) return;
  const account = { ...a, name: name.trim() };
  saveAccount(account);
  setAccountState(account);
  net.send({ type: 'profile', name: account.name });
}

export function signOut() {
  saveAccount(null);
  setAccountState(null);
}

// ---- contacts ------------------------------------------------------------------------------------

/** The real contact for this phone, created (with the name given) if new. */
export function ensureRealContact(phone: string, name?: string, extra: Partial<Contact> = {}): Contact {
  const existing = getState().contacts.find((c) => c.real && c.phone === phone);
  if (existing) return existing;
  const contact: Contact = {
    id: realId(phone),
    name: name?.trim() || '+' + phone,
    phone,
    gender: 'u',
    about: '',
    colors: pickGroupColors(phone),
    online: false,
    lastSeen: 0,
    real: true,
    ...extra,
  };
  addContact(contact);
  return contact;
}

/** Add a person found on the server under the name I chose. */
export function addRealContact(user: RemoteUser, name: string): Contact {
  return ensureRealContact(user.phone, name || user.name, {
    about: user.about ?? '',
    colors: user.colors ?? pickGroupColors(user.phone),
    online: user.online,
    lastSeen: user.lastSeen,
  });
}

/** A group chat described by the server; members are phones (mine is skipped). */
export function realGroupFromServer(id: string, title: string, phones: string[]): Chat {
  const me = net.me?.phone;
  const memberIds = [...new Set(phones)].filter((p) => p !== me).map((p) => ensureRealContact(p).id);
  upsertChat({ id, kind: 'group', title: title || 'Группа', memberIds, colors: pickGroupColors(id), createdAt: Date.now() });
  return getChat(id)!;
}

function watchContacts() {
  const phones = getState().contacts.filter((c) => c.real).map((c) => c.phone);
  if (phones.length) net.send({ type: 'watch', phones });
}

export function lookupPhones(phones: string[]) {
  return net.lookup(phones);
}

// ---- sending -------------------------------------------------------------------------------------

const uploaded = new Set<string>();

/** Send one of my messages to the real members of its chat. Resolves with the server time. */
export async function sendRealMessage(message: Message, chat: Chat): Promise<number> {
  const members = chat.memberIds.map(getContact).filter((c): c is Contact => !!c?.real);
  if (!members.length) return Date.now();
  if (message.media && !uploaded.has(message.media.id)) {
    const blob = await getMedia(message.media.id);
    if (!blob) throw new Error('media missing');
    await net.upload(message.media.id, blob, message.media.mime);
    uploaded.add(message.media.id);
  }
  const phones = members.map((c) => c.phone);
  const { at } = await net.sendMessage({
    id: message.id,
    to: phones,
    text: message.text,
    createdAt: message.createdAt,
    media: message.media,
    chat: chat.kind === 'group' ? { kind: 'group', id: chat.id, title: chat.title, members: phones } : { kind: 'direct' },
  });
  return at;
}

/** I read their messages in this chat: tell the senders. */
export function sendReadReceipts(messages: Message[]) {
  const bySender = new Map<string, string[]>();
  for (const m of messages) {
    const sender = m.senderId ? getContact(m.senderId) : undefined;
    if (!sender?.real || m.call) continue;
    bySender.set(sender.phone, [...(bySender.get(sender.phone) ?? []), m.id]);
  }
  bySender.forEach((ids, to) => net.sendReliable({ type: 'receipt', kind: 'read', ids, to }));
}

let lastTyping = 0;
/** Called while I type; throttled to one signal every 3 s. */
export function notifyTyping(chatId: string) {
  const chat = getChat(chatId);
  if (!chat || !net.isOnline() || Date.now() - lastTyping < 3000) return;
  const to = chat.memberIds.map(getContact).filter((c) => c?.real).map((c) => c!.phone);
  if (!to.length) return;
  lastTyping = Date.now();
  net.send({ type: 'typing', to, chatId: chat.kind === 'group' ? chat.id : null, typing: true });
}

// ---- receiving ------------------------------------------------------------------------------------

const ORDER: Record<Message['status'], number> = { pending: 0, sent: 1, delivered: 2, read: 3 };
const typingTimers = new Map<string, number>();

function handle(m: ServerMsg) {
  switch (m.type) {
    case 'msg':
      return receiveMessage(m);
    case 'receipt': {
      for (const id of m.ids as string[]) {
        const msg = findMessageAnywhere(id);
        if (!msg || msg.author !== 'me') continue;
        if (m.kind === 'delivered' && ORDER[msg.status] < ORDER.delivered) updateMessage(msg.chatId, id, { status: 'delivered', deliveredAt: m.at });
        if (m.kind === 'read' && msg.status !== 'read') updateMessage(msg.chatId, id, { status: 'read', readAt: m.at, deliveredAt: msg.deliveredAt ?? m.at });
      }
      return;
    }
    case 'presence': {
      const c = getState().contacts.find((x) => x.real && x.phone === m.phone);
      if (c) patchContact(c.id, { online: !!m.online, lastSeen: m.lastSeen ?? c.lastSeen, ...(m.about !== undefined ? { about: m.about } : {}) });
      return;
    }
    case 'typing': {
      const c = getState().contacts.find((x) => x.real && x.phone === m.from);
      if (!c) return;
      const chatId = m.chatId || c.id;
      setTyping(chatId, m.typing ? c.id : undefined);
      clearTimeout(typingTimers.get(chatId));
      if (m.typing) typingTimers.set(chatId, window.setTimeout(() => setTyping(chatId, undefined), 5000));
      return;
    }
    case 'call':
      return hooks.onCall(m);
    case 'rtc':
      return hooks.onRtc(m);
  }
}

function receiveMessage(m: ServerMsg) {
  const sender = ensureRealContact(m.from, m.fromName);
  let chatId = sender.id;
  if (m.chat?.kind === 'group' && m.chat.id) {
    chatId = realGroupFromServer(m.chat.id, m.chat.title, (m.chat.members ?? []).map((x: { phone: string; name: string }) => {
      ensureRealContact(x.phone, x.name);
      return x.phone;
    })).id;
  } else {
    ensureDirectChat(sender.id);
  }
  net.sendReliable({ type: 'receipt', kind: 'delivered', ids: [m.id], to: m.from });
  if (findMessage(chatId, m.id)) return;
  setTyping(chatId, undefined);
  const media = m.media && m.media.id ? m.media : undefined;
  const message: Message = {
    id: m.id,
    chatId,
    author: 'them',
    senderId: sender.id,
    text: m.text ?? '',
    media,
    createdAt: m.createdAt,
    sentAt: m.sentAt,
    deliveredAt: Date.now(),
    status: 'delivered',
  };
  addMessage(message);
  hooks.onIncoming(message);
  if (media) downloadMedia(media.id);
}

async function downloadMedia(id: string, attempt = 0) {
  try {
    if (await getMedia(id)) return;
    const blob = await net.download(id);
    await putMedia(id, blob);
    window.dispatchEvent(new CustomEvent(MEDIA_READY_EVENT, { detail: id }));
  } catch {
    if (attempt < 4) window.setTimeout(() => downloadMedia(id, attempt + 1), 2000 * 2 ** attempt);
  }
}

function clearRealTyping() {
  const s = getState();
  for (const [chatId, who] of Object.entries(s.typing)) {
    if (who && getContact(who)?.real) setTyping(chatId, undefined);
  }
}
