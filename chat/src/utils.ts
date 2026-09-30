import type { CallLog, Chat, Contact, Message } from './types';

export function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

export const rand = (min: number, max: number) => min + Math.random() * (max - min);
export const pick = <T,>(items: readonly T[]): T => items[Math.floor(Math.random() * items.length)];

const MIN = 60_000;
const DAY = 24 * 60 * MIN;

const timeFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
const timeSecFmt = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const weekdayFmt = new Intl.DateTimeFormat('ru-RU', { weekday: 'short' });
const shortDateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
const dayFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' });
const dayYearFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

function startOfDay(ts: number) {
  const d = new Date(ts);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** Whole days between the two dates' calendar days. */
function daysAgo(ts: number, now = Date.now()) {
  return Math.round((startOfDay(now) - startOfDay(ts)) / DAY);
}

export const formatTime = (ts: number) => timeFmt.format(ts);
export const formatTimeSec = (ts: number) => timeSecFmt.format(ts);

/** Time in the chat list: 14:05 / вчера / пн / 12.09.26 */
export function formatListTime(ts: number) {
  const d = daysAgo(ts);
  if (d <= 0) return timeFmt.format(ts);
  if (d === 1) return 'вчера';
  if (d < 7) return weekdayFmt.format(ts);
  return shortDateFmt.format(ts);
}

/** Date separator in a chat. */
export function formatDay(ts: number) {
  const d = daysAgo(ts);
  if (d <= 0) return 'Сегодня';
  if (d === 1) return 'Вчера';
  return new Date(ts).getFullYear() === new Date().getFullYear() ? dayFmt.format(ts) : dayYearFmt.format(ts);
}

/** Full moment for the delivery details: "сегодня в 14:05:12" */
export function formatMoment(ts: number) {
  const d = daysAgo(ts);
  const prefix = d <= 0 ? 'сегодня' : d === 1 ? 'вчера' : dayFmt.format(ts);
  return `${prefix} в ${timeSecFmt.format(ts)}`;
}

export function formatLastSeen(contact: Contact, now = Date.now()) {
  const was = contact.gender === 'f' ? 'была' : 'был';
  const diff = now - contact.lastSeen;
  if (diff < MIN) return `${was} в сети только что`;
  if (diff < 60 * MIN) return `${was} в сети ${Math.floor(diff / MIN)} мин назад`;
  const d = daysAgo(contact.lastSeen, now);
  if (d <= 0) return `${was} в сети сегодня в ${timeFmt.format(contact.lastSeen)}`;
  if (d === 1) return `${was} в сети вчера в ${timeFmt.format(contact.lastSeen)}`;
  return `${was} в сети ${dayFmt.format(contact.lastSeen)}`;
}

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

export function formatDuration(sec: number) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('');
}

export function callLabel(call: CallLog) {
  const what = call.kind === 'video' ? 'видеозвонок' : 'звонок';
  switch (call.outcome) {
    case 'answered':
      return call.direction === 'out' ? `Исходящий ${what}` : `Входящий ${what}`;
    case 'missed':
      return `Пропущенный ${what}`;
    case 'declined':
      return call.direction === 'out' ? `Отклонённый ${what}` : `Вы отклонили ${what}`;
    case 'cancelled':
      return `Отменённый ${what}`;
    case 'unavailable':
      return `${what[0].toUpperCase()}${what.slice(1)} · нет ответа`;
  }
}

export function messagePreview(m: Message) {
  if (m.call) return `${m.call.kind === 'video' ? '📹' : '📞'} ${callLabel(m.call)}`;
  if (m.media) {
    const label = m.media.kind === 'image' ? '📷 Фото' : '🎬 Видео';
    return m.text ? `${label} · ${m.text}` : label;
  }
  return m.text;
}

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// ---- chats ---------------------------------------------------------------------------

const GROUP_COLORS: [string, string][] = [
  ['#667eea', '#764ba2'],
  ['#f093fb', '#f5576c'],
  ['#4facfe', '#00c6fb'],
  ['#fa709a', '#fee140'],
  ['#30cfd0', '#330867'],
  ['#5ee7df', '#b490ca'],
];

export function pickGroupColors(seed: string): [string, string] {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return GROUP_COLORS[h % GROUP_COLORS.length];
}

/** Name and avatar colors of a chat: the contact for a direct chat, the group itself otherwise. */
export function chatLook(chat: Chat, contacts: Contact[]) {
  if (chat.kind === 'direct') {
    const c = contacts.find((x) => x.id === chat.memberIds[0]);
    return { name: c?.name ?? 'Контакт', colors: c?.colors ?? (['#c3cad8', '#9aa4b5'] as [string, string]), contact: c };
  }
  return { name: chat.title || 'Группа', colors: chat.colors ?? pickGroupColors(chat.id), contact: undefined };
}

// ---- phone numbers ---------------------------------------------------------------------

/** "8 (999) 123-45-67" → "79991234567"; null if it doesn't look like a phone number. */
export function normalizePhone(input: string): string | null {
  let d = input.replace(/\D/g, '');
  if (d.length === 11 && d[0] === '8') d = '7' + d.slice(1);
  if (d.length === 10 && d[0] === '9') d = '7' + d;
  return d.length >= 10 && d.length <= 15 ? d : null;
}

/** "79991234567" → "+7 999 123-45-67" */
export function formatPhone(digits: string) {
  if (digits.length === 11 && digits[0] === '7') {
    return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
  }
  return '+' + digits;
}

/** Formats the phone field while typing. */
export function formatPhoneInput(input: string) {
  let d = input.replace(/\D/g, '').slice(0, 15);
  if (!d) return input.trim().startsWith('+') ? '+' : '';
  if (d[0] === '8') d = '7' + d.slice(1);
  if (d[0] === '9') d = '7' + d;
  if (d[0] !== '7') return '+' + d;
  const p = [d.slice(1, 4), d.slice(4, 7), d.slice(7, 9), d.slice(9, 11)];
  let out = '+7';
  if (p[0]) out += ' ' + p[0];
  if (p[1]) out += ' ' + p[1];
  if (p[2]) out += '-' + p[2];
  if (p[3]) out += '-' + p[3];
  return out;
}

export function isSameDay(a: number, b: number) {
  return startOfDay(a) === startOfDay(b);
}
