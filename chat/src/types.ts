export type MessageStatus = 'pending' | 'sent' | 'delivered' | 'read';

/** audio — voice message; a video with `round` — video note ("кружок"). */
export type MediaKind = 'image' | 'video' | 'audio';

/** Metadata of a photo/video; the file itself lives in IndexedDB under `id`. */
export interface MediaRef {
  id: string;
  kind: MediaKind;
  mime: string;
  name: string;
  size: number;
  width?: number;
  height?: number;
  /** Video/audio length in seconds. */
  duration?: number;
  /** Video note ("кружок"): shown as a circle. */
  round?: boolean;
  /** Voice message: loudness bars 0..1 for the waveform. */
  waveform?: number[];
}

export type CallKind = 'audio' | 'video';
export type CallOutcome = 'answered' | 'missed' | 'declined' | 'cancelled' | 'unavailable';

/** A finished call, shown in the chat history. */
export interface CallLog {
  kind: CallKind;
  direction: 'out' | 'in';
  outcome: CallOutcome;
  /** Seconds of conversation (answered calls only). */
  duration?: number;
}

export interface Message {
  id: string;
  chatId: string;
  /** 'system' — service lines like "Вы создали группу". */
  author: 'me' | 'them' | 'system';
  /** Who wrote it, for messages from others (matters in groups). */
  senderId?: string;
  text: string;
  media?: MediaRef;
  call?: CallLog;
  /** When the message was written (also shown in the bubble). */
  createdAt: number;
  /** When the server accepted it. */
  sentAt?: number;
  /** When it reached the recipient's device (in a group: the first member). */
  deliveredAt?: number;
  /** When the recipient opened it (in a group: the first member). */
  readAt?: number;
  status: MessageStatus;
}

export interface Contact {
  id: string;
  name: string;
  /** Digits only, with country code: "79991234567". */
  phone: string;
  /** 'u' — unknown (real people): "был(а) в сети". */
  gender: 'm' | 'f' | 'u';
  about: string;
  /** Two colors of the avatar gradient. */
  colors: [string, string];
  online: boolean;
  lastSeen: number;
  /** A real person registered on the server (not a demo contact). */
  real?: boolean;
}

export interface Chat {
  /** For a direct chat this equals the contact id. */
  id: string;
  kind: 'direct' | 'group';
  /** Contacts in the chat (without me). */
  memberIds: string[];
  /** Group name. */
  title?: string;
  colors?: [string, string];
  createdAt: number;
}

export interface Toast {
  id: string;
  text: string;
  kind: 'info' | 'success' | 'warning' | 'message';
  chatId?: string;
  /** Whose avatar to show. */
  contactId?: string;
}

export interface Connection {
  /** navigator.onLine */
  browserOnline: boolean;
  /** "Airplane mode" switch in the menu, to try offline mode without turning off the network. */
  simulatedOffline: boolean;
  /** Number of messages being sent right now by the sync engine. */
  syncing: number;
}

export interface CallParticipant {
  contactId: string;
  state: 'ringing' | 'connected' | 'declined' | 'unavailable' | 'left';
  /** Real calls: what we receive from this person over WebRTC. */
  stream?: MediaStream;
  cameraOn?: boolean;
  muted?: boolean;
}

export interface ActiveCall {
  id: string;
  /** demo — the other side is simulated; real — WebRTC through the server. */
  mode: 'demo' | 'real';
  chatId: string;
  kind: CallKind;
  direction: 'out' | 'in';
  /** incoming: ringing on my side; calling: waiting for an answer; ended: the "call ended" screen. */
  phase: 'incoming' | 'calling' | 'connected' | 'ended';
  startedAt: number;
  connectedAt?: number;
  endedAt?: number;
  /** Shown on the ended screen: "Нет ответа", "Звонок завершён"… */
  endText?: string;
  participants: CallParticipant[];
  muted: boolean;
  cameraOn: boolean;
  facing: 'user' | 'environment';
  /** My camera/microphone; null when access was refused. */
  localStream: MediaStream | null;
  mediaError?: string;
  minimized: boolean;
}

/** My registration on the server. The token is a secret that proves this device owns the number. */
export interface Account {
  phone: string;
  name: string;
  token: string;
}

export interface NetState {
  /** Server address (https://…); empty = not configured. */
  url: string;
  status: 'off' | 'connecting' | 'online' | 'offline' | 'error';
  /** Human-readable problem, e.g. "номер занят на другом устройстве". */
  error?: string;
}

export interface AppState {
  contacts: Contact[];
  chats: Chat[];
  /** chatId → messages, oldest first. */
  messages: Record<string, Message[]>;
  drafts: Record<string, string>;
  /** chatId → id of the contact who is typing (not persisted). */
  typing: Record<string, string | undefined>;
  connection: Connection;
  toasts: Toast[];
  call: ActiveCall | null;
  account: Account | null;
  net: NetState;
  /** Show the demo contacts, chats and their simulated activity. */
  showDemo: boolean;
}
