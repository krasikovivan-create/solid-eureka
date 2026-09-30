// Messages, contacts and drafts are kept in localStorage.
import type { Contact, Message } from '../types';

const KEY = 'svyaz.state.v1';
const OFFLINE_KEY = 'svyaz.simulatedOffline';

export interface PersistedState {
  contacts: Contact[];
  messages: Record<string, Message[]>;
  drafts: Record<string, string>;
}

export function loadState(): PersistedState | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as PersistedState;
    if (!Array.isArray(data.contacts) || typeof data.messages !== 'object') return null;
    return { contacts: data.contacts, messages: data.messages, drafts: data.drafts ?? {} };
  } catch {
    return null;
  }
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
