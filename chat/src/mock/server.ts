// A fake chat backend that lives in the page. It behaves like a real one from the
// client's point of view: accepts messages, reports delivery and reading, keeps
// contacts' presence, and makes contacts reply. While the client is offline,
// everything the "server" wants to tell it is queued and arrives after reconnecting.
import type { Contact, Message } from '../types';
import { pick, rand, uid } from '../utils';

export type ServerEvent =
  | { type: 'delivered'; chatId: string; id: string; at: number }
  | { type: 'read'; chatId: string; ids: string[]; at: number }
  | { type: 'message'; message: Message }
  | { type: 'presence'; contactId: string; online: boolean; at: number }
  | { type: 'typing'; chatId: string; typing: boolean };

interface Outgoing {
  chatId: string;
  id: string;
  text: string;
  media?: Message['media'];
}

/** How likely a contact is to be online at any moment. */
const ONLINE_CHANCE: Record<string, number> = { anna: 0.7, mom: 0.8, kate: 0.6, max: 0.5, dima: 0.4, sofia: 0.5, igor: 0.15 };

const OfflineError = () => new Error('offline');

export class MockServer {
  private clientOnline = false;
  private queue: ServerEvent[] = [];
  private handler: (e: ServerEvent) => void = () => {};
  private contacts = new Map<string, Contact>();
  private undelivered = new Map<string, Outgoing[]>();
  private unread = new Map<string, Outgoing[]>();
  private readTimers = new Map<string, number>();
  private busy = new Set<string>();
  private timers = new Set<number>();
  private flushing = false;
  private inflight = new Set<(e: Error) => void>();

  start(contacts: Contact[], messages: Record<string, Message[]>, handler: (e: ServerEvent) => void) {
    this.stop();
    this.handler = handler;
    this.contacts = new Map(contacts.map((c) => [c.id, { ...c }]));

    // Pick up where we left off before the page was reloaded.
    for (const list of Object.values(messages)) {
      for (const m of list) {
        if (m.author !== 'me') continue;
        const item: Outgoing = { chatId: m.chatId, id: m.id, text: m.text, media: m.media };
        if (m.status === 'sent') this.push(this.undelivered, m.chatId, item);
        if (m.status === 'delivered') this.push(this.unread, m.chatId, item);
      }
    }
    for (const c of this.contacts.values()) {
      if (c.online) this.later(rand(1500, 3500), () => this.arrive(c.id));
    }
    this.schedulePresence();
    this.scheduleSpontaneous();
  }

  stop() {
    this.timers.forEach((t) => clearTimeout(t));
    this.timers.clear();
    this.readTimers.clear();
    this.undelivered.clear();
    this.unread.clear();
    this.busy.clear();
    this.queue = [];
    this.flushing = false;
    this.inflight.forEach((reject) => reject(new Error('reset')));
    this.inflight.clear();
  }

  setClientOnline(online: boolean) {
    this.clientOnline = online;
    if (online) this.flushQueue();
  }

  /** Upload a message. Resolves with the time the server accepted it; rejects when offline. */
  send(message: Message): Promise<number> {
    if (!this.clientOnline) return Promise.reject(OfflineError());
    // Media takes longer, as if it were really uploaded (~4 MB/s, capped).
    const upload = message.media ? Math.min(3500, 300 + message.media.size / 4000) : 0;
    return new Promise((resolve, reject) => {
      this.inflight.add(reject);
      this.later(rand(250, 650) + upload, () => {
        this.inflight.delete(reject);
        if (!this.clientOnline) return reject(OfflineError());
        resolve(Date.now());
        this.accept({ chatId: message.chatId, id: message.id, text: message.text, media: message.media });
      });
    });
  }

  // ---- internals ------------------------------------------------------------------

  private accept(item: Outgoing) {
    this.push(this.undelivered, item.chatId, item);
    if (this.contacts.get(item.chatId)?.online) this.later(rand(300, 900), () => this.arrive(item.chatId));
  }

  /** The contact's device is reachable: deliver everything waiting, then they read it. */
  private arrive(contactId: string) {
    const waiting = this.undelivered.get(contactId) ?? [];
    this.undelivered.delete(contactId);
    const now = Date.now();
    waiting.forEach((item, i) => {
      this.emit({ type: 'delivered', chatId: contactId, id: item.id, at: now + i * 40 });
      this.push(this.unread, contactId, item);
    });
    this.scheduleRead(contactId);
  }

  private scheduleRead(contactId: string) {
    if (this.readTimers.has(contactId) || !this.unread.get(contactId)?.length) return;
    const t = this.later(rand(1500, 4500), () => {
      this.readTimers.delete(contactId);
      if (!this.contacts.get(contactId)?.online) return; // will read when back online
      const items = this.unread.get(contactId) ?? [];
      this.unread.delete(contactId);
      if (!items.length) return;
      this.emit({ type: 'read', chatId: contactId, ids: items.map((i) => i.id), at: Date.now() });
      if (Math.random() < 0.85) this.reply(contactId, items[items.length - 1]);
    });
    this.readTimers.set(contactId, t);
  }

  private reply(contactId: string, to: Outgoing) {
    const contact = this.contacts.get(contactId);
    if (!contact || this.busy.has(contactId)) return;
    this.busy.add(contactId);
    const text = replyTo(contact, to);
    this.later(rand(500, 1400), () => {
      this.emit({ type: 'typing', chatId: contactId, typing: true });
      this.later(Math.min(4000, 900 + text.length * 45), () => {
        this.emit({ type: 'typing', chatId: contactId, typing: false });
        this.busy.delete(contactId);
        this.incoming(contactId, text);
      });
    });
  }

  private incoming(contactId: string, text: string) {
    const now = Date.now();
    this.emit({
      type: 'message',
      message: { id: uid(), chatId: contactId, author: 'them', text, createdAt: now, sentAt: now, deliveredAt: now, status: 'delivered' },
    });
  }

  /** Contacts come and go every 12–25 s. */
  private schedulePresence() {
    this.later(rand(12_000, 25_000), () => {
      const contact = pick([...this.contacts.values()]);
      const online = Math.random() < (ONLINE_CHANCE[contact.id] ?? 0.5);
      if (online !== contact.online && !this.busy.has(contact.id)) {
        const at = Date.now();
        contact.online = online;
        contact.lastSeen = at;
        this.emit({ type: 'presence', contactId: contact.id, online, at });
        if (online) this.later(rand(600, 1500), () => this.arrive(contact.id));
      }
      this.schedulePresence();
    });
  }

  /** Now and then someone who is online writes first. */
  private scheduleSpontaneous() {
    this.later(rand(40_000, 80_000), () => {
      const candidates = [...this.contacts.values()].filter((c) => c.online && !this.busy.has(c.id));
      if (candidates.length) {
        const contact = pick(candidates);
        const text = pick(SPONTANEOUS[contact.id] ?? ['Привет! Как дела?']);
        this.busy.add(contact.id);
        this.emit({ type: 'typing', chatId: contact.id, typing: true });
        this.later(Math.min(3500, 900 + text.length * 40), () => {
          this.emit({ type: 'typing', chatId: contact.id, typing: false });
          this.busy.delete(contact.id);
          this.incoming(contact.id, text);
        });
      }
      this.scheduleSpontaneous();
    });
  }

  private emit(event: ServerEvent) {
    if (this.clientOnline && !this.flushing) this.handler(event);
    else if (event.type !== 'typing' || !event.typing) this.queue.push(event); // "typing…" is live-only
  }

  /** Replays what happened while the client was offline, a bit apart so it is visible. */
  private flushQueue() {
    if (this.flushing || !this.queue.length) return;
    this.flushing = true;
    const step = () => {
      if (!this.clientOnline) return void (this.flushing = false);
      const event = this.queue.shift();
      if (!event) return void (this.flushing = false);
      this.handler(event);
      this.later(120, step);
    };
    this.later(300, step);
  }

  private push(map: Map<string, Outgoing[]>, key: string, item: Outgoing) {
    const list = map.get(key) ?? [];
    if (!list.some((i) => i.id === item.id)) list.push(item);
    map.set(key, list);
  }

  private later(ms: number, fn: () => void): number {
    const t = window.setTimeout(() => {
      this.timers.delete(t);
      fn();
    }, ms);
    this.timers.add(t);
    return t;
  }
}

// ---- what contacts say ------------------------------------------------------------------

const g = (c: Contact, m: string, f: string) => (c.gender === 'f' ? f : m);

function replyTo(c: Contact, to: Outgoing): string {
  const text = to.text.toLowerCase();
  if (to.media?.kind === 'image') return pick(['Какое классное фото! 😍', 'Вау, красота!', `${g(c, 'Сохранил', 'Сохранила')} себе 🙂`, 'Где это? Очень красиво']);
  if (to.media?.kind === 'video') return pick([`${g(c, 'Посмотрел', 'Посмотрела')}, огонь 🔥`, 'Ха-ха, отличное видео!', 'Пересмотрю ещё раз 😄']);
  if (/привет|здравств|хай|добр(ое|ый)/.test(text)) return pick(['Привет! 👋', 'Привет-привет!', 'Привет! Рада слышать'.replace('Рада', g(c, 'Рад', 'Рада'))]);
  if (/спасиб|благодар/.test(text)) return pick(['Не за что! 😊', 'Обращайся!', 'Всегда пожалуйста']);
  if (/пока|до завтра|спокойной/.test(text)) return pick(['Пока! 👋', 'До связи!', 'Хорошего вечера!']);
  if (text.includes('?')) return pick(['Хороший вопрос 🤔 Дай подумать', 'Думаю, да!', 'Скорее нет, чем да', 'Давай вечером обсудим?', `Пока не ${g(c, 'уверен', 'уверена')}, уточню`]);
  return pick(REPLIES[c.id] ?? DEFAULT_REPLIES);
}

const DEFAULT_REPLIES = ['Ага 👍', 'Понятно!', 'Звучит отлично', 'Договорились', 'Ок, на связи'];

const REPLIES: Record<string, string[]> = {
  anna: ['Ахаха, точно 😄', 'Согласна!', 'Слушай, отличная идея', 'Ок, до завтра на встрече 😉'],
  max: ['Ок, гляну', 'Принял 👌', 'Сейчас в деплое, отвечу чуть позже', 'Логично'],
  mom: ['Хорошо ❤️', 'Береги себя!', 'Целую 😘', 'Позвони вечером'],
  dima: ['Го! ⚽', 'Красава!', 'Ха, ну ты даёшь', 'Давай'],
  kate: ['Отлично, спасибо!', 'Принято, внесу в план', 'Супер, так и сделаем', 'Ок, обсудим на созвоне'],
  igor: ['Я на пляже, отвечу позже 🏖️', 'Тут связь так себе 😅', 'Вернусь — расскажу'],
  sofia: ['Класс!', 'Договорились 📸', 'Ок, жду', 'Ура!'],
};

const SPONTANEOUS: Record<string, string[]> = {
  anna: ['Слушай, есть минутка?', 'Нашла классную кофейню, сходим? ☕', 'Смотри, что нашла — позже покажу 😊'],
  max: ['Глянь PR, когда будет время', 'Сервер опять упал 😅 уже чиню', 'Есть идея для пет-проекта'],
  mom: ['Как дела?', 'Не забудь тепло одеться, на улице холодно', 'Позвони бабушке ❤️'],
  dima: ['Кто в четверг на футбол?', 'Вчерашний матч — просто огонь 🔥', 'Бронирую поле на 19:00'],
  kate: ['Напоминаю про созвон в 15:00', 'Клиент доволен макетами 🎉', 'Можешь глянуть документ?'],
  igor: ['Привет из отпуска! 🏖️', 'Тут море +24, красота'],
  sofia: ['Сделала пару новых кадров, скоро покажу 📸', 'Суббота в силе?'],
};

export const server = new MockServer();
