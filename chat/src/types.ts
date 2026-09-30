export type MessageStatus = 'pending' | 'sent' | 'delivered' | 'read';

export type MediaKind = 'image' | 'video';

/** Metadata of a photo/video; the file itself lives in IndexedDB under `id`. */
export interface MediaRef {
  id: string;
  kind: MediaKind;
  mime: string;
  name: string;
  size: number;
  width?: number;
  height?: number;
  /** Video length in seconds. */
  duration?: number;
}

export interface Message {
  id: string;
  chatId: string;
  author: 'me' | 'them';
  text: string;
  media?: MediaRef;
  /** When the message was written (also shown in the bubble). */
  createdAt: number;
  /** When the server accepted it. */
  sentAt?: number;
  /** When it reached the recipient's device. */
  deliveredAt?: number;
  /** When the recipient opened it. */
  readAt?: number;
  status: MessageStatus;
}

export interface Contact {
  id: string;
  name: string;
  gender: 'm' | 'f';
  about: string;
  /** Two colors of the avatar gradient. */
  colors: [string, string];
  online: boolean;
  lastSeen: number;
}

export interface Toast {
  id: string;
  text: string;
  kind: 'info' | 'success' | 'warning' | 'message';
  chatId?: string;
}

export interface Connection {
  /** navigator.onLine */
  browserOnline: boolean;
  /** "Airplane mode" switch in the menu, to try offline mode without turning off the network. */
  simulatedOffline: boolean;
  /** Number of messages being sent right now by the sync engine. */
  syncing: number;
}

export interface AppState {
  contacts: Contact[];
  /** chatId → messages, oldest first. */
  messages: Record<string, Message[]>;
  drafts: Record<string, string>;
  /** chatId → the contact is typing (not persisted). */
  typing: Record<string, boolean>;
  connection: Connection;
  toasts: Toast[];
}
