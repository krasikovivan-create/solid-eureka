import test from 'node:test';
import assert from 'node:assert/strict';
import { formatWhen, parseReminder, zonedToUtc } from '../src/timeparse.js';

const TZ = 'Europe/Moscow';
// Thursday 1 Oct 2026, 13:00 in Moscow.
const NOW = new Date('2026-10-01T10:00:00Z');

function when(input) {
  const r = parseReminder(input, NOW, TZ);
  return r.error ? `ERR ${r.error}` : `${formatWhen(r.at, TZ, NOW)} | ${r.text}`;
}

test('relative times', () => {
  assert.equal(when('через 10 минут позвонить маме'), 'сегодня в 13:10 | позвонить маме');
  assert.equal(when('через час и 30 минут чай'), 'сегодня в 14:30 | чай');
  assert.equal(when('через полчаса выйти'), 'сегодня в 13:30 | выйти');
  assert.equal(when('через час спать'), 'сегодня в 14:00 | спать');
  assert.equal(when('15м проверить'), 'сегодня в 13:15 | проверить');
  assert.equal(when('2ч спать'), 'сегодня в 15:00 | спать');
  assert.equal(when('через 1 минуту чай'), 'сегодня в 13:01 | чай');
  assert.equal(when('через 2 дня оплатить'), 'послезавтра в 13:00 | оплатить');
  assert.equal(when('через неделю отчёт'), '8 окт в 13:00 | отчёт');
});

test('clock times', () => {
  assert.equal(when('в 18:30 ужин'), 'сегодня в 18:30 | ужин');
  assert.equal(when('18:30 ужин'), 'сегодня в 18:30 | ужин');
  assert.equal(when('в 9 вечера кино'), 'сегодня в 21:00 | кино');
  assert.equal(when('в 10 утра купить молоко'), 'завтра в 10:00 | купить молоко'); // 10:00 has passed today
  assert.equal(when('завтра в 9 бег'), 'завтра в 09:00 | бег');
  assert.equal(when('послезавтра бег'), 'послезавтра в 09:00 | бег');
  assert.equal(when('в пятницу в 19:00 бокс'), 'завтра в 19:00 | бокс');
  assert.equal(when('в четверг в 12:00 отчёт'), '8 окт в 12:00 | отчёт');
  assert.equal(when('в четверг в 18:00 отчёт'), 'сегодня в 18:00 | отчёт');
  assert.equal(when('05.10 в 12:00 врач'), '5 окт в 12:00 | врач');
  assert.equal(when('01.09 в 12:00 школа'), '1 сен 2027 в 12:00 | школа');
});

test('time at the end and the «напомни» prefix', () => {
  assert.equal(when('позвонить маме завтра в 10'), 'завтра в 10:00 | позвонить маме');
  assert.equal(when('напомни мне через 5 минут что надо выключить плиту'), 'сегодня в 13:05 | надо выключить плиту');
  assert.equal(when('Напомни, пожалуйста, в 20:00 полить цветы'), 'сегодня в 20:00 | полить цветы');
});

test('errors', () => {
  assert.equal(when('купить 2 хлеба'), 'ERR when');
  assert.equal(when('сегодня в 8:00 зарядка'), 'ERR past');
  assert.equal(when('через 10 минут'), 'ERR text');
  assert.equal(when('в 25:00 x'), 'ERR when');
  assert.equal(when('31.02 в 10:00 x'), 'ERR date');
  assert.equal(when('через 2 года x'), 'ERR when');
});

test('keeps the original letter case of the text', () => {
  assert.equal(parseReminder('через 5 минут Позвонить Ане', NOW, TZ).text, 'Позвонить Ане');
});

test('time zones and DST', () => {
  assert.equal(zonedToUtc({ year: 2026, month: 10, day: 1, hour: 9, minute: 0 }, 'Europe/Moscow').toISOString(), '2026-10-01T06:00:00.000Z');
  assert.equal(zonedToUtc({ year: 2026, month: 7, day: 1, hour: 9, minute: 0 }, 'Europe/Berlin').toISOString(), '2026-07-01T07:00:00.000Z');
  assert.equal(zonedToUtc({ year: 2026, month: 1, day: 1, hour: 9, minute: 0 }, 'Europe/Berlin').toISOString(), '2026-01-01T08:00:00.000Z');
  const r = parseReminder('завтра в 9 бег', NOW, 'Asia/Novosibirsk');
  assert.equal(r.at.toISOString(), '2026-10-02T02:00:00.000Z');
});
