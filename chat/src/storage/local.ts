// Messages, contacts, chats and drafts are kept in localStorage.
import type { Chat, Contact, Message } from '../types';
import { SEED_PHONES, seedGroupMessages, seedGroups } from '../mock/seed';

const KEY = 'svyaz.state.v2';
const KEY_V1 = 'svyaz.state.v1';
const OFFLINE_KEY = 'svyaz.simulatedOffline';

export interface PersistedState {
  contacts: Contact[];
  chats: Chat[];
  messages: Record<string, Message[]>;
  drafts: Record<string, string>;
}

export function loadState(): PersistedState | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const data = JSON.parse(raw) as PersistedState;
      if (Array.isArray(data.contacts) && Array.isArray(data.chats) && typeof data.messages === 'object') {
        return { contacts: data.contacts, chats: data.chats, messages: data.messages, drafts: data.drafts ?? {} };
      }
    }
    return migrateV1();
  } catch {
    return null;
  }
}

/**
 * The first version had no chats (every contact was a chat) and no phone numbers.
 * Keep the user's history and add what is new: numbers, chat records and the demo groups.
 */
function migrateV1(): PersistedState | null {
  const raw = localStorage.getItem(KEY_V1);
  if (!raw) return null;
  const old = JSON.parse(raw) as { contacts?: Contact[]; messages?: Record<string, Message[]>; drafts?: Record<string, string> };
  if (!Array.isArray(old.contacts) || typeof old.messages !== 'object') return null;
  const now = Date.now();
  const contacts = old.contacts.map((c) => ({ ...c, phone: c.phone ?? SEED_PHONES[c.id] ?? '7900' + String(Math.floor(Math.random() * 1e7)).padStart(7, '0') }));
  const messages: Record<string, Message[]> = { ...seedGroupMessages(now) };
  for (const [chatId, list] of Object.entries(old.messages)) {
    messages[chatId] = list.map((m) => (m.author === 'them' && !m.senderId ? { ...m, senderId: chatId } : m));
  }
  const chats: Chat[] = [...contacts.map((c): Chat => ({ id: c.id, kind: 'direct', memberIds: [c.id], createdAt: now })), ...seedGroups(now)];
  const state = { contacts, chats, messages, drafts: old.drafts ?? {} };
  if (saveState(state)) localStorage.removeItem(KEY_V1);
  return state;
}

/** Returns false when the browser refused to save (e.g. storage is full). */
export function saveState(state: PersistedState): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

export function clearState() {
  try {
    localStorage.removeItem(KEY);
    localStorage.removeItem(KEY_V1);
  } catch {
    /* ignore */
  }
}

export function loadSimulatedOffline(): boolean {
  try {
    return localStorage.getItem(OFFLINE_KEY) === '1';
  } catch {
    return false;
  }
}

export function saveSimulatedOffline(value: boolean) {
  try {
    if (value) localStorage.setItem(OFFLINE_KEY, '1');
    else localStorage.removeItem(OFFLINE_KEY);
  } catch {
    /* ignore */
  }
}
