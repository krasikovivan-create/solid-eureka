// A tiny global store (no Redux): state + subscribe, used via useSyncExternalStore.
// Every change to contacts/messages/drafts is written to localStorage right away.
import { useSyncExternalStore } from 'react';
import type { AppState, Contact, Message, Toast } from './types';
import { loadSimulatedOffline, loadState, saveState } from './storage/local';
import { createSeedState } from './mock/seed';
import { uid } from './utils';

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
  if (prev.contacts !== next.contacts || prev.messages !== next.messages || prev.drafts !== next.drafts) {
    const ok = saveState({ contacts: next.contacts, messages: next.messages, drafts: next.drafts });
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

/** Marks the contact's messages in this chat as read by me. */
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

// ---- drafts, contacts, typing ------------------------------------------------

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

export function setTyping(chatId: string, typing: boolean) {
  if (!!state.typing[chatId] === typing) return;
  setState({ ...state, typing: { ...state.typing, [chatId]: typing } });
}

// ---- connection ---------------------------------------------------------------

export function setConnection(patch: Partial<AppState['connection']>) {
  setState({ ...state, connection: { ...state.connection, ...patch } });
}

// ---- toasts ---------------------------------------------------------------------

export function showToast(text: string, kind: Toast['kind'] = 'info', chatId?: string) {
  const toast: Toast = { id: uid(), text, kind, chatId };
  setState({ ...state, toasts: [...state.toasts.slice(-2), toast] });
  setTimeout(() => dismissToast(toast.id), kind === 'warning' ? 6000 : 4000);
}

export function dismissToast(id: string) {
  if (!state.toasts.some((t) => t.id === id)) return;
  setState({ ...state, toasts: state.toasts.filter((t) => t.id !== id) });
}

// ---- demo reset --------------------------------------------------------------------

export function replaceData(data: Pick<AppState, 'contacts' | 'messages' | 'drafts'>) {
  setState({ ...state, ...data, typing: {}, toasts: [] });
}
