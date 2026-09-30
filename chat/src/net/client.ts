// Connection to the real server (chat/server): one WebSocket that reconnects by itself,
// plus HTTP for photos/videos. Knows nothing about chats — sync.ts and real.ts do.
import type { Account } from '../types';

export interface RemoteUser {
  phone: string;
  name: string;
  about?: string;
  colors?: [string, string];
  online: boolean;
  lastSeen: number;
}

export type ServerMsg = { type: string } & Record<string, any>;

type Status = 'off' | 'connecting' | 'online' | 'offline' | 'error';

interface Callbacks {
  onStatus: (status: Status, error?: string) => void;
  onMessage: (m: ServerMsg) => void;
  onWelcome: (me: RemoteUser) => void;
}

const DEFAULT_ICE: RTCIceServer[] = [{ urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] }];

/** "svyaz.onrender.com" / "https://…/" → "https://svyaz.onrender.com" */
export function normalizeServerUrl(input: string) {
  let url = input.trim().replace(/\/+$/, '');
  if (!url) return '';
  if (!/^[a-z]+:\/\//i.test(url)) url = (/^(localhost|127\.|192\.168\.|10\.)/.test(url) ? 'http://' : 'https://') + url;
  return url.replace(/^ws(s?):/i, 'http$1:');
}

export class NetClient {
  private ws: WebSocket | null = null;
  private url = '';
  private account: Account | null = null;
  private wanted = false;
  private retry = 0;
  private retryTimer: number | undefined;
  private pingTimer: number | undefined;
  private reqId = 0;
  private lookups = new Map<number, { resolve: (u: RemoteUser[]) => void; reject: (e: Error) => void; timer: number }>();
  private acks = new Map<string, { resolve: (r: { at: number; unknown: string[] }) => void; reject: (e: Error) => void; timer: number }>();
  /** Receipts etc. that must survive a reconnect. */
  private later: object[] = [];
  status: Status = 'off';
  iceServers: RTCIceServer[] = DEFAULT_ICE;

  constructor(private cb: Callbacks) {}

  get httpBase() {
    return this.url;
  }

  get me() {
    return this.account;
  }

  /** Connect (or stay connected) with this server and account; null → disconnect. */
  configure(url: string, account: Account | null, networkUp: boolean) {
    const want = !!url && !!account && networkUp;
    const changed = url !== this.url || account?.phone !== this.account?.phone || account?.token !== this.account?.token;
    this.url = url;
    this.account = account;
    if (!want) {
      this.wanted = false;
      this.close();
      this.setStatus(url && account ? 'offline' : 'off');
      return;
    }
    if (changed) this.close();
    this.wanted = true;
    if (!this.ws) this.connect();
  }

  /** Forget the error (e.g. after the user fixed the number) and try again. */
  retryNow() {
    this.retry = 0;
    this.close();
    if (this.url && this.account) {
      this.wanted = true;
      this.connect();
    }
  }

  isOnline() {
    return this.status === 'online';
  }

  send(obj: object): boolean {
    if (this.status !== 'online' || !this.ws) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  /** Send now, or as soon as we are connected again. */
  sendReliable(obj: object) {
    if (!this.send(obj)) this.later.push(obj);
  }

  /** Send a chat message; resolves with the server time once it has taken it. */
  sendMessage(payload: { id: string; [key: string]: unknown }): Promise<{ at: number; unknown: string[] }> {
    if (!this.send({ type: 'msg', ...payload })) return Promise.reject(new Error('offline'));
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.acks.delete(payload.id);
        reject(new Error('timeout'));
      }, 15_000);
      this.acks.set(payload.id, { resolve, reject, timer });
    });
  }

  /** Which of these numbers use the app. */
  lookup(phones: string[]): Promise<RemoteUser[]> {
    const reqId = ++this.reqId;
    if (!this.send({ type: 'lookup', reqId, phones })) return Promise.reject(new Error('offline'));
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.lookups.delete(reqId);
        reject(new Error('timeout'));
      }, 15_000);
      this.lookups.set(reqId, { resolve, reject, timer });
    });
  }

  // ---- media over HTTP --------------------------------------------------------------------

  private authHeaders(): Record<string, string> {
    return this.account ? { 'X-Phone': this.account.phone, 'X-Token': this.account.token } : {};
  }

  async upload(id: string, blob: Blob, mime: string) {
    const res = await fetch(`${this.url}/media/${encodeURIComponent(id)}`, { method: 'POST', headers: { ...this.authHeaders(), 'Content-Type': mime }, body: blob });
    if (!res.ok) throw new Error(`upload ${res.status}`);
  }

  async download(id: string): Promise<Blob> {
    const res = await fetch(`${this.url}/media/${encodeURIComponent(id)}`, { headers: this.authHeaders() });
    if (!res.ok) throw new Error(`download ${res.status}`);
    return res.blob();
  }

  // ---- connection ---------------------------------------------------------------------------

  private connect() {
    if (!this.account) return;
    this.setStatus('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url.replace(/^http/i, 'ws'));
    } catch {
      this.setStatus('error', 'Неверный адрес сервера');
      this.wanted = false;
      return;
    }
    this.ws = ws;
    const account = this.account;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', phone: account.phone, token: account.token, name: account.name }));
    ws.onmessage = (e) => {
      let m: ServerMsg;
      try {
        m = JSON.parse(String(e.data));
      } catch {
        return;
      }
      this.handle(m);
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.ws = null;
      clearInterval(this.pingTimer);
      this.failPending();
      if (e.code === 4001) {
        this.wanted = false;
        this.setStatus('error', 'Этот номер уже зарегистрирован на другом устройстве');
        return;
      }
      if (!this.wanted) return;
      this.setStatus('offline');
      // Back off: 1 s, 2 s, 4 s … up to 30 s (a sleeping free server needs ~a minute to wake up).
      const delay = Math.min(30_000, 1000 * 2 ** this.retry++) + Math.random() * 500;
      this.retryTimer = window.setTimeout(() => this.wanted && !this.ws && this.connect(), delay);
    };
  }

  private handle(m: ServerMsg) {
    switch (m.type) {
      case 'welcome':
        this.retry = 0;
        if (Array.isArray(m.iceServers) && m.iceServers.length) this.iceServers = m.iceServers;
        this.setStatus('online');
        clearInterval(this.pingTimer);
        this.pingTimer = window.setInterval(() => this.send({ type: 'ping' }), 25_000);
        this.cb.onWelcome(m.me);
        for (const obj of this.later.splice(0)) this.sendReliable(obj);
        return;
      case 'pong':
        return;
      case 'ack': {
        const a = this.acks.get(m.id);
        if (!a) return;
        clearTimeout(a.timer);
        this.acks.delete(m.id);
        a.resolve({ at: m.at, unknown: Array.isArray(m.unknown) ? m.unknown : [] });
        return;
      }
      case 'lookup-result': {
        const l = this.lookups.get(m.reqId);
        if (!l) return;
        clearTimeout(l.timer);
        this.lookups.delete(m.reqId);
        l.resolve(m.users ?? []);
        return;
      }
      case 'error':
        if (m.code === 'phone-taken') this.setStatus('error', 'Этот номер уже зарегистрирован на другом устройстве');
        return;
      default:
        this.cb.onMessage(m);
    }
  }

  private failPending() {
    const err = new Error('disconnected');
    this.acks.forEach((a) => (clearTimeout(a.timer), a.reject(err)));
    this.acks.clear();
    this.lookups.forEach((l) => (clearTimeout(l.timer), l.reject(err)));
    this.lookups.clear();
  }

  private close() {
    clearTimeout(this.retryTimer);
    clearInterval(this.pingTimer);
    const ws = this.ws;
    this.ws = null;
    this.failPending();
    if (ws) {
      ws.onclose = null;
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }

  private setStatus(status: Status, error?: string) {
    this.status = status;
    this.cb.onStatus(status, error);
  }
}
