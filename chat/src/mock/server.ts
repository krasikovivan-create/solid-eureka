// A fake chat backend that lives in the page. It behaves like a real one from the
// client's point of view: accepts messages, reports delivery and reading, keeps
// contacts' presence, makes contacts reply (also in groups), finds people by phone
// number and simulates calls. While the client is offline, everything the "server"
// wants to tell it is queued and arrives after reconnecting (calls are live-only).
import type { CallKind, Chat, Contact, Message } from '../types';
import { DIRECTORY } from './seed';
import { pick, rand, uid } from '../utils';

export type ServerEvent =
  | { type: 'delivered'; chatId: string; id: string; at: number }
  | { type: 'read'; chatId: string; ids: string[]; at: number }
  | { type: 'message'; message: Message }
  | { type: 'presence'; contactId: string; online: boolean; at: number }
  | { type: 'typing'; chatId: string; contactId?: string }
  | { type: 'call-state'; callId: string; contactId: string; state: 'connected' | 'declined' | 'left' }
  | { type: 'call-incoming'; callId: string; chatId: string; contactId: string; kind: CallKind }
  | { type: 'call-cancelled'; callId: string };

export type Profile = Pick<Contact, 'name' | 'phone' | 'gender' | 'about' | 'colors'>;

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
  private chats = new Map<string, Chat>();
  private undelivered = new Map<string, Outgoing[]>();
  private unread = new Map<string, Outgoing[]>();
  private readTimers = new Map<string, number>();
  /** Contacts that are typing or on a call right now. */
  private busy = new Set<string>();
  private timers = new Set<number>();
  private callTimers = new Map<string, Set<number>>();
  private flushing = false;
  private inflight = new Set<(e: Error) => void>();
  /** Demo contacts hidden: no spontaneous messages or calls. */
  private quiet = false;

  setQuiet(quiet: boolean) {
    this.quiet = quiet;
  }

  start(contacts: Contact[], chats: Chat[], messages: Record<string, Message[]>, handler: (e: ServerEvent) => void) {
    this.stop();
    this.handler = handler;
    this.contacts = new Map(contacts.map((c) => [c.id, { ...c }]));
    this.chats = new Map(chats.map((c) => [c.id, c]));

    // Pick up where we left off before the page was reloaded.
    for (const list of Object.values(messages)) {
      for (const m of list) {
        if (m.author !== 'me' || m.call) continue;
        const item: Outgoing = { chatId: m.chatId, id: m.id, text: m.text, media: m.media };
        if (m.status === 'sent') this.push(this.undelivered, m.chatId, item);
        if (m.status === 'delivered') this.push(this.unread, m.chatId, item);
      }
    }
    for (const chat of this.chats.values()) {
      if (this.anyOnline(chat.id)) this.later(rand(1500, 3500), () => this.arrive(chat.id));
    }
    this.schedulePresence();
    this.scheduleSpontaneous();
    this.scheduleIncomingCall();
  }

  stop() {
    this.timers.forEach((t) => clearTimeout(t));
    this.timers.clear();
    this.callTimers.clear();
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

  /** A contact was added on the client (found by number). */
  registerContact(contact: Contact) {
    if (!this.contacts.has(contact.id)) this.contacts.set(contact.id, { ...contact });
  }

  /** A chat was created or changed on the client (new direct chat, new group, new members). */
  registerChat(chat: Chat) {
    this.chats.set(chat.id, chat);
  }

  /** Upload a message. Resolves with the time the server accepted it; rejects when offline. */
  send(message: Message, chat: Chat): Promise<number> {
    if (!this.clientOnline) return Promise.reject(OfflineError());
    // A group created offline becomes known to the server with its first message.
    this.chats.set(chat.id, chat);
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

  /** Find a user by phone number. Resolves null when nobody uses the app with this number. */
  lookup(phone: string): Promise<Profile | null> {
    if (!this.clientOnline) return Promise.reject(OfflineError());
    return new Promise((resolve, reject) => {
      this.later(rand(600, 1200), () => {
        if (!this.clientOnline) return reject(OfflineError());
        resolve(findProfile(phone));
      });
    });
  }

  // ---- calls ---------------------------------------------------------------------

  /** I call a chat: each online member rings, then answers or declines. Offline members never answer. */
  placeCall(callId: string, chatId: string) {
    const chat = this.chats.get(chatId);
    if (!chat || !this.clientOnline) return;
    for (const id of chat.memberIds) {
      const contact = this.contacts.get(id);
      if (!contact?.online) continue;
      if (this.busy.has(id) && chat.kind === 'direct') {
        this.callLater(callId, rand(1500, 2500), () => this.emit({ type: 'call-state', callId, contactId: id, state: 'declined' }));
        continue;
      }
      const answers = Math.random() < (chat.kind === 'direct' ? 0.85 : 0.75);
      this.callLater(callId, rand(2500, 7000), () => {
        if (!answers) return this.emit({ type: 'call-state', callId, contactId: id, state: 'declined' });
        this.busy.add(id);
        this.emit({ type: 'call-state', callId, contactId: id, state: 'connected' });
        // People don't talk forever: after a few minutes they say goodbye.
        this.callLater(callId, rand(120_000, 420_000), () => {
          this.busy.delete(id);
          this.emit({ type: 'call-state', callId, contactId: id, state: 'left' });
        });
      });
    }
  }

  /** I accepted an incoming call: the caller stays on the line for a while. */
  answerCall(callId: string, contactId: string) {
    this.clearCall(callId);
    this.busy.add(contactId);
    this.callLater(callId, rand(90_000, 300_000), () => {
      this.busy.delete(contactId);
      this.emit({ type: 'call-state', callId, contactId, state: 'left' });
    });
  }

  /** I hung up or declined. */
  endCall(callId: string, memberIds: string[]) {
    this.clearCall(callId);
    memberIds.forEach((id) => this.busy.delete(id));
  }

  /** Every 3–6 minutes someone online calls me. */
  private scheduleIncomingCall() {
    this.later(rand(180_000, 360_000), () => {
      if (!this.quiet) this.ringMe();
      this.scheduleIncomingCall();
    });
  }

  /** Someone online (from a direct chat) calls me now. Returns false if nobody can. */
  ringMe(kind?: CallKind): boolean {
    const candidates = [...this.contacts.values()].filter((c) => c.online && !this.busy.has(c.id) && this.chats.get(c.id)?.kind === 'direct');
    if (!candidates.length || !this.clientOnline) return false;
    const contact = pick(candidates);
    const callId = uid();
    this.emit({ type: 'call-incoming', callId, chatId: contact.id, contactId: contact.id, kind: kind ?? (Math.random() < 0.4 ? 'video' : 'audio') });
    // Nobody picks up → the caller gives up after 30 s.
    this.callLater(callId, 30_000, () => this.emit({ type: 'call-cancelled', callId }));
    return true;
  }

  private callLater(callId: string, ms: number, fn: () => void) {
    const set = this.callTimers.get(callId) ?? new Set<number>();
    const t = this.later(ms, () => {
      set.delete(t);
      fn();
    });
    set.add(t);
    this.callTimers.set(callId, set);
  }

  private clearCall(callId: string) {
    this.callTimers.get(callId)?.forEach((t) => {
      clearTimeout(t);
      this.timers.delete(t);
    });
    this.callTimers.delete(callId);
  }

  // ---- messages ----------------------------------------------------------------------

  private anyOnline(chatId: string) {
    return !!this.chats.get(chatId)?.memberIds.some((id) => this.contacts.get(id)?.online);
  }

  private onlineMembers(chatId: string) {
    return (this.chats.get(chatId)?.memberIds ?? []).map((id) => this.contacts.get(id)).filter((c): c is Contact => !!c?.online);
  }

  private accept(item: Outgoing) {
    this.push(this.undelivered, item.chatId, item);
    if (this.anyOnline(item.chatId)) this.later(rand(300, 900), () => this.arrive(item.chatId));
  }

  /** A recipient's device is reachable: deliver everything waiting, then they read it. */
  private arrive(chatId: string) {
    const waiting = this.undelivered.get(chatId) ?? [];
    this.undelivered.delete(chatId);
    const now = Date.now();
    waiting.forEach((item, i) => {
      this.emit({ type: 'delivered', chatId, id: item.id, at: now + i * 40 });
      this.push(this.unread, chatId, item);
    });
    this.scheduleRead(chatId);
  }

  private scheduleRead(chatId: string) {
    if (this.readTimers.has(chatId) || !this.unread.get(chatId)?.length) return;
    const t = this.later(rand(1500, 4500), () => {
      this.readTimers.delete(chatId);
      const readers = this.onlineMembers(chatId);
      if (!readers.length) return; // will read when someone is back online
      const items = this.unread.get(chatId) ?? [];
      this.unread.delete(chatId);
      if (!items.length) return;
      this.emit({ type: 'read', chatId, ids: items.map((i) => i.id), at: Date.now() });
      const group = this.chats.get(chatId)?.kind === 'group';
      // Someone who isn't busy typing elsewhere answers.
      const free = readers.filter((r) => !this.busy.has(r.id));
      if (free.length && Math.random() < (group ? 0.8 : 0.85)) this.reply(chatId, pick(free), items[items.length - 1]);
    });
    this.readTimers.set(chatId, t);
  }

  private reply(chatId: string, contact: Contact, to: Outgoing) {
    if (this.busy.has(contact.id)) return;
    this.busy.add(contact.id);
    const text = replyTo(contact, to);
    this.later(rand(500, 1400), () => {
      this.emit({ type: 'typing', chatId, contactId: contact.id });
      this.later(Math.min(4000, 900 + text.length * 45), () => {
        this.emit({ type: 'typing', chatId });
        this.busy.delete(contact.id);
        this.incoming(chatId, contact.id, text);
      });
    });
  }

  private incoming(chatId: string, senderId: string, text: string) {
    const now = Date.now();
    this.emit({
      type: 'message',
      message: { id: uid(), chatId, author: 'them', senderId, text, createdAt: now, sentAt: now, deliveredAt: now, status: 'delivered' },
    });
  }

  /** Contacts come and go every 12–25 s. */
  private schedulePresence() {
    this.later(rand(12_000, 25_000), () => {
      const all = [...this.contacts.values()];
      const contact = all.length ? pick(all) : null;
      if (contact) {
        const online = Math.random() < (ONLINE_CHANCE[contact.id] ?? 0.5);
        if (online !== contact.online && !this.busy.has(contact.id)) {
          const at = Date.now();
          contact.online = online;
          contact.lastSeen = at;
          this.emit({ type: 'presence', contactId: contact.id, online, at });
          if (online) {
            for (const chat of this.chats.values()) {
              if (chat.memberIds.includes(contact.id)) this.later(rand(600, 1500), () => this.arrive(chat.id));
            }
          }
        }
      }
      this.schedulePresence();
    });
  }

  /** Now and then someone who is online writes first — to you or to a group. */
  private scheduleSpontaneous() {
    this.later(rand(40_000, 80_000), () => {
      const candidates = [...this.contacts.values()].filter((c) => c.online && !this.busy.has(c.id));
      if (candidates.length && !this.quiet) {
        const contact = pick(candidates);
        const groups = [...this.chats.values()].filter((c) => c.kind === 'group' && c.memberIds.includes(contact.id));
        const inGroup = groups.length > 0 && Math.random() < 0.35;
        const chatId = inGroup ? pick(groups).id : contact.id;
        const text = inGroup ? pick(GROUP_SPONTANEOUS[chatId] ?? GROUP_SPONTANEOUS.default) : pick(SPONTANEOUS[contact.id] ?? ['Привет! Как дела?', 'Есть минутка?']);
        this.busy.add(contact.id);
        this.emit({ type: 'typing', chatId, contactId: contact.id });
        this.later(Math.min(3500, 900 + text.length * 40), () => {
          this.emit({ type: 'typing', chatId });
          this.busy.delete(contact.id);
          this.incoming(chatId, contact.id, text);
        });
      }
      this.scheduleSpontaneous();
    });
  }

  private emit(event: ServerEvent) {
    const live = event.type === 'typing' || event.type.startsWith('call-');
    if (this.clientOnline && !this.flushing) this.handler(event);
    else if (!live || (event.type === 'typing' && !event.contactId)) this.queue.push(event); // "typing…" and calls are live-only
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

// ---- the phone directory ------------------------------------------------------------------

const FIRST_M = ['Алексей', 'Сергей', 'Никита', 'Роман', 'Егор', 'Павел', 'Илья', 'Кирилл'];
const FIRST_F = ['Мария', 'Дарья', 'Алина', 'Виктория', 'Ксения', 'Юлия', 'Вера', 'Ева'];
const LAST = ['Иванов', 'Кузнецов', 'Попов', 'Васильев', 'Новиков', 'Фёдоров', 'Михайлов', 'Зайцев'];
const ABOUT = ['Привет! Я пользуюсь Связью', 'На связи 📱', 'Люблю кофе ☕', 'Бегаю по утрам 🏃', 'Читаю, путешествую', 'Работаю, не беспокоить 🙂'];
const COLORS: [string, string][] = [
  ['#f6d365', '#fda085'],
  ['#a1c4fd', '#c2e9fb'],
  ['#d4fc79', '#96e6a1'],
  ['#fbc2eb', '#a6c1ee'],
  ['#ff9a9e', '#fecfef'],
  ['#84fab0', '#8fd3f4'],
];

/**
 * Known demo users come from DIRECTORY; any other number resolves to a stable made-up
 * person (the same number always gives the same person), except every 5th-ish number,
 * which "isn't registered" — to show the invite flow.
 */
function findProfile(phone: string): Profile | null {
  const known = DIRECTORY.find((p) => p.phone === phone);
  if (known) return known;
  let h = 7;
  for (const ch of phone) h = (h * 131 + ch.charCodeAt(0)) >>> 0;
  if (h % 5 === 0) return null;
  const female = h % 2 === 0;
  const first = (female ? FIRST_F : FIRST_M)[(h >>> 3) % 8];
  const last = LAST[(h >>> 7) % LAST.length] + (female ? 'а' : '');
  return { name: `${first} ${last}`, phone, gender: female ? 'f' : 'm', about: ABOUT[(h >>> 11) % ABOUT.length], colors: COLORS[(h >>> 13) % COLORS.length] };
}

// ---- what contacts say ------------------------------------------------------------------

const g = (c: Contact, m: string, f: string) => (c.gender === 'f' ? f : m);

function replyTo(c: Contact, to: Outgoing): string {
  const text = to.text.toLowerCase();
  if (to.media?.kind === 'image') return pick(['Какое классное фото! 😍', 'Вау, красота!', `${g(c, 'Сохранил', 'Сохранила')} себе 🙂`, 'Где это? Очень красиво']);
  if (to.media?.kind === 'video') return pick([`${g(c, 'Посмотрел', 'Посмотрела')}, огонь 🔥`, 'Ха-ха, отличное видео!', 'Пересмотрю ещё раз 😄']);
  if (/привет|здравств|хай|добр(ое|ый)/.test(text)) return pick(['Привет! 👋', 'Привет-привет!', `Привет! ${g(c, 'Рад', 'Рада')} слышать`]);
  if (/спасиб|благодар/.test(text)) return pick(['Не за что! 😊', 'Обращайся!', 'Всегда пожалуйста']);
  if (/пока|до завтра|спокойной/.test(text)) return pick(['Пока! 👋', 'До связи!', 'Хорошего вечера!']);
  if (/позвон|созвон|звонок/.test(text)) return pick(['Давай, звони 📞', 'Сейчас не могу, через полчаса?', 'Ок, набери меня']);
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

const GROUP_SPONTANEOUS: Record<string, string[]> = {
  'g-football': ['Кто в четверг? Отметьтесь 🙋', 'Мяч у кого остался?', 'Может, в субботу ещё сыграем?'],
  'g-alpha': ['Коллеги, созвон переносится на 16:00', 'Обновила задачи на доске', 'Клиент прислал правки, гляньте'],
  default: ['Всем привет! 👋', 'Какие планы на выходные?', 'Как у всех дела? 😄'],
};

export const server = new MockServer();
