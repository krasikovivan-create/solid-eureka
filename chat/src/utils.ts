import type { Contact, Message } from './types';

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

export function messagePreview(m: Message) {
  if (m.media) {
    const label = m.media.kind === 'image' ? '📷 Фото' : '🎬 Видео';
    return m.text ? `${label} · ${m.text}` : label;
  }
  return m.text;
}

export function isSameDay(a: number, b: number) {
  return startOfDay(a) === startOfDay(b);
}
