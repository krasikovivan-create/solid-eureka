// A tiny global store (no Redux): state + subscribe, used via useSyncExternalStore.
// Every change to contacts/chats/messages/drafts is written to localStorage right away.
import { useSyncExternalStore } from 'react';
import type { ActiveCall, AppState, Chat, Contact, Message, Toast } from './types';
import { loadAccount, loadServerUrl, loadShowDemo, loadSimulatedOffline, loadState, saveState } from './storage/local';
import { createSeedState } from './mock/seed';
import { pickGroupColors, uid } from './utils';

const persisted = loadState() ?? createSeedState();

let state: AppState = {
  ...persisted,
  typing: {},
  connection: {
    browserOnline: typeof navigator === 'undefined' ? true : navigator.onLine,
    simulatedOffline: loadSimulatedOffline(),
    syncing: 0,
  },
  toasts: [],
  call: null,
  account: loadAccount(),
  net: { url: loadServerUrl(), status: 'off' },
  showDemo: loadShowDemo(),
};

const listeners = new Set<() => void>();
let saveWarned = false;

export function getState() {
  return state;
}

export function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setState(next: AppState) {
  const prev = state;
  state = next;
  if (prev.contacts !== next.contacts || prev.chats !== next.chats || prev.messages !== next.messages || prev.drafts !== next.drafts) {
    const ok = saveState({ contacts: next.contacts, chats: next.chats, messages: next.messages, drafts: next.drafts });
    if (!ok && !saveWarned) {
      saveWarned = true;
      queueMicrotask(() => showToast('Хранилище браузера переполнено — новые сообщения могут не сохраниться', 'warning'));
    }
  }
  listeners.forEach((l) => l());
}

export function useAppState<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state));
}

export function isOnline(s: AppState = state) {
  return s.connection.browserOnline && !s.connection.simulatedOffline;
}

export function getContact(id: string): Contact | undefined {
  return state.contacts.find((c) => c.id === id);
}

export function getChat(id: string): Chat | undefined {
  return state.chats.find((c) => c.id === id);
}

// ---- contacts & chats ---------------------------------------------------------

export function findContactByPhone(phone: string) {
  return state.contacts.find((c) => c.phone === phone);
}

export function addContact(contact: Contact) {
  if (state.contacts.some((c) => c.id === contact.id)) return;
  setState({ ...state, contacts: [...state.contacts, contact] });
}

/** The direct chat with a contact, created on first use. */
export function ensureDirectChat(contactId: string): Chat {
  const existing = getChat(contactId);
  if (existing) return existing;
  const chat: Chat = { id: contactId, kind: 'direct', memberIds: [contactId], createdAt: Date.now() };
  setState({ ...state, chats: [...state.chats, chat] });
  return chat;
}

export function createGroup(title: string, memberIds: string[]): Chat {
  const id = 'g-' + uid().slice(0, 8);
  const now = Date.now();
  const chat: Chat = { id, kind: 'group', title: title.trim(), memberIds, colors: pickGroupColors(id), createdAt: now };
  const names = memberIds.map((m) => getContact(m)?.name.split(' ')[0]).filter(Boolean).join(', ');
  const first: Message = { id: uid(), chatId: id, author: 'system', text: `Вы создали группу «${chat.title}» · ${names}`, createdAt: now, status: 'read' };
  setState({ ...state, chats: [...state.chats, chat], messages: { ...state.messages, [id]: [first] } });
  return chat;
}

export function addGroupMembers(chatId: string, memberIds: string[]) {
  const chat = getChat(chatId);
  if (!chat || chat.kind !== 'group') return;
  const added = memberIds.filter((m) => !chat.memberIds.includes(m));
  if (!added.length) return;
  const names = added.map((m) => getContact(m)?.name).filter(Boolean).join(', ');
  setState({ ...state, chats: state.chats.map((c) => (c.id === chatId ? { ...c, memberIds: [...c.memberIds, ...added] } : c)) });
  addMessage({ id: uid(), chatId, author: 'system', text: `Вы добавили: ${names}`, createdAt: Date.now(), status: 'read' });
}

// ---- messages -------------------------------------------------------------

export function addMessage(message: Message) {
  const list = state.messages[message.chatId] ?? [];
  if (list.some((m) => m.id === message.id)) return;
  // Keep chronological order even if a message arrives late (e.g. after sync).
  const next = [...list, message].sort((a, b) => a.createdAt - b.createdAt);
  setState({ ...state, messages: { ...state.messages, [message.chatId]: next } });
}

export function updateMessage(chatId: string, id: string, patch: Partial<Message>) {
  const list = state.messages[chatId];
  if (!list) return;
  const idx = list.findIndex((m) => m.id === id);
  if (idx < 0) return;
  const next = list.slice();
  next[idx] = { ...list[idx], ...patch };
  setState({ ...state, messages: { ...state.messages, [chatId]: next } });
}

export function findMessage(chatId: string, id: string) {
  return state.messages[chatId]?.find((m) => m.id === id);
}

/** Marks the others' messages in this chat as read by me. */
export function markChatRead(chatId: string) {
  const list = state.messages[chatId];
  if (!list || !list.some((m) => m.author === 'them' && m.status !== 'read')) return;
  const now = Date.now();
  const next = list.map((m) => (m.author === 'them' && m.status !== 'read' ? { ...m, status: 'read' as const, readAt: now } : m));
  setState({ ...state, messages: { ...state.messages, [chatId]: next } });
}

export function pendingMessages(): Message[] {
  return Object.values(state.messages)
    .flat()
    .filter((m) => m.author === 'me' && m.status === 'pending')
    .sort((a, b) => a.createdAt - b.createdAt);
}

// ---- drafts, presence, typing ------------------------------------------------

export function setDraft(chatId: string, text: string) {
  if ((state.drafts[chatId] ?? '') === text) return;
  const drafts = { ...state.drafts };
  if (text) drafts[chatId] = text;
  else delete drafts[chatId];
  setState({ ...state, drafts });
}

export function setPresence(contactId: string, online: boolean, at: number) {
  setState({
    ...state,
    contacts: state.contacts.map((c) => (c.id === contactId ? { ...c, online, lastSeen: at } : c)),
  });
}

/** contactId = who is typing; undefined = nobody. */
export function setTyping(chatId: string, contactId: string | undefined) {
  if (state.typing[chatId] === contactId) return;
  setState({ ...state, typing: { ...state.typing, [chatId]: contactId } });
}

// ---- connection ---------------------------------------------------------------

export function setConnection(patch: Partial<AppState['connection']>) {
  setState({ ...state, connection: { ...state.connection, ...patch } });
}

// ---- account & server ------------------------------------------------------------

export function setAccountState(account: AppState['account']) {
  setState({ ...state, account });
}

export function setNet(patch: Partial<AppState['net']>) {
  setState({ ...state, net: { ...state.net, ...patch } });
}

export function setShowDemoState(showDemo: boolean) {
  setState({ ...state, showDemo });
}

/** Is the chat backed by the real server (has at least one real member)? */
export function isRealChat(chat: Chat | undefined) {
  return !!chat?.memberIds.some((id) => getContact(id)?.real);
}

export function findMessageAnywhere(id: string): Message | undefined {
  for (const list of Object.values(state.messages)) {
    const m = list.find((x) => x.id === id);
    if (m) return m;
  }
  return undefined;
}

/** Update a contact (e.g. name/presence from the server). */
export function patchContact(id: string, patch: Partial<Contact>) {
  if (!state.contacts.some((c) => c.id === id)) return;
  setState({ ...state, contacts: state.contacts.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
}

/** Create or update a group chat that came from the server. */
export function upsertChat(chat: Chat) {
  const existing = getChat(chat.id);
  if (existing && existing.title === chat.title && existing.memberIds.join() === chat.memberIds.join()) return;
  setState({ ...state, chats: existing ? state.chats.map((c) => (c.id === chat.id ? { ...c, title: chat.title, memberIds: chat.memberIds } : c)) : [...state.chats, chat] });
}

// ---- call ---------------------------------------------------------------------------

export function setCall(call: ActiveCall | null) {
  setState({ ...state, call });
}

export function patchCall(patch: Partial<ActiveCall>) {
  if (!state.call) return;
  setState({ ...state, call: { ...state.call, ...patch } });
}

// ---- toasts ---------------------------------------------------------------------

export function showToast(text: string, kind: Toast['kind'] = 'info', chatId?: string, contactId?: string) {
  const toast: Toast = { id: uid(), text, kind, chatId, contactId };
  setState({ ...state, toasts: [...state.toasts.slice(-2), toast] });
  setTimeout(() => dismissToast(toast.id), kind === 'warning' ? 6000 : 4000);
}

export function dismissToast(id: string) {
  if (!state.toasts.some((t) => t.id === id)) return;
  setState({ ...state, toasts: state.toasts.filter((t) => t.id !== id) });
}

// ---- demo reset --------------------------------------------------------------------

export function replaceData(data: Pick<AppState, 'contacts' | 'chats' | 'messages' | 'drafts'>) {
  setState({ ...state, ...data, typing: {}, toasts: [] });
}

/** Keep real contacts/chats/messages when the demo data is reset. */
export function realData() {
  const contacts = state.contacts.filter((c) => c.real);
  const chats = state.chats.filter((ch) => ch.memberIds.some((id) => contacts.some((c) => c.id === id)));
  const messages: AppState['messages'] = {};
  for (const ch of chats) if (state.messages[ch.id]) messages[ch.id] = state.messages[ch.id];
  return { contacts, chats, messages };
}
