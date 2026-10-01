import test from 'node:test';
import assert from 'node:assert/strict';
import { createBot } from '../src/bot.js';
import { createStore, memoryBackend } from '../src/store.js';

const CHAT = 42;

// Fake Telegram API: records calls, returns a message id for sendMessage.
function fakeApi() {
  const calls = [];
  let nextMessage = 100;
  return {
    calls,
    failNext: null,
    async call(method, params) {
      if (this.failNext) {
        const err = this.failNext;
        this.failNext = null;
        throw err;
      }
      calls.push({ method, ...params });
      return method === 'sendMessage' ? { message_id: nextMessage++ } : true;
    },
    sent() {
      return calls.filter((c) => c.method === 'sendMessage');
    },
    last(method = 'sendMessage') {
      return calls.filter((c) => c.method === method).at(-1);
    },
  };
}

async function setup() {
  const clock = { t: new Date('2026-10-01T10:00:00Z').getTime() }; // 13:00 Moscow
  const backend = memoryBackend();
  const store = await createStore(backend, { saveDelayMs: 0 });
  const api = fakeApi();
  const bot = createBot({ api, store, adminIds: ['7'], now: () => new Date(clock.t) });
  const from = { id: CHAT, first_name: 'Иван' };
  const say = (text) => bot.handleUpdate({ message: { message_id: 1, chat: { id: CHAT, type: 'private' }, from, text } });
  const tap = (data, messageId = 100) =>
    bot.handleUpdate({ callback_query: { id: 'cq', from, data, message: { message_id: messageId, chat: { id: CHAT }, text: '' } } });
  const buttons = (call) => call.reply_markup.inline_keyboard.flat().map((b) => b.callback_data);
  return { clock, store, backend, api, bot, say, tap, buttons };
}

test('/start shows the menu keyboard', async () => {
  const { api, say } = await setup();
  await say('/start');
  const m = api.last();
  assert.match(m.text, /Привет, Иван/);
  assert.equal(m.reply_markup.keyboard[0][0].text, '📝 Заметки');
});

test('notes: add via button flow, list, delete', async () => {
  const { api, store, say, tap, buttons } = await setup();
  await say('📝 Заметки');
  assert.match(api.last().text, /Заметок пока нет/);

  await tap('note:new');
  await say('купить молоко <и хлеб>');
  assert.match(api.last().text, /Заметка сохранена/);

  await say('/note позвонить Пете');
  const u = store.user(CHAT);
  assert.deepEqual(u.notes.map((n) => n.text), ['купить молоко <и хлеб>', 'позвонить Пете']);

  await say('/notes');
  const list = api.last();
  assert.match(list.text, /1\.<\/b> позвонить Пете/); // newest first
  assert.match(list.text, /купить молоко &lt;и хлеб&gt;/); // HTML-escaped

  const del = buttons(list).find((d) => d.startsWith('note:del:'));
  await tap(del);
  assert.equal(u.notes.length, 1);
  assert.equal(api.last('editMessageText').message_id, 100);
  assert.equal(api.last('answerCallbackQuery').text, '🗑 Удалено');
});

test('notes paginate by 8', async () => {
  const { api, say, tap, buttons } = await setup();
  for (let i = 1; i <= 10; i++) await say(`/note заметка ${i}`);
  await say('/notes');
  assert.ok(buttons(api.last()).includes('notes:p:1'));
  await tap('notes:p:1');
  const page2 = api.last('editMessageText');
  assert.match(page2.text, /9\.<\/b> заметка 2/);
  assert.match(page2.text, /10\.<\/b> заметка 1/);
});

test('reminders: create, fire on time, snooze, done', async () => {
  const { api, store, bot, clock, say, tap, buttons } = await setup();
  await say('напомни через 10 минут выключить духовку');
  assert.match(api.last().text, /Напомню <b>сегодня в 13:10<\/b>/);
  const u = store.user(CHAT);
  assert.equal(u.reminders.length, 1);

  await bot.checkReminders();
  const before = api.sent().length;
  assert.equal(u.reminders.length, 1, 'not due yet');

  clock.t += 10 * 60_000;
  await bot.checkReminders();
  assert.equal(api.sent().length, before + 1);
  const fired = api.last();
  assert.match(fired.text, /Напоминание<\/b>\n\nвыключить духовку$/);
  assert.equal(u.reminders.length, 0);

  const snooze = buttons(fired).find((d) => d.endsWith(':10'));
  await tap(snooze);
  assert.equal(u.reminders.length, 1);
  assert.match(api.last('editMessageText').text, /Отложено — напомню сегодня в 13:20/);

  clock.t += 10 * 60_000;
  await bot.checkReminders();
  const again = api.last();
  assert.match(again.text, /выключить духовку/);
  await tap(buttons(again).find((d) => d.startsWith('rem:done:')));
  assert.equal(u.fired.length, 0);
});

test('reminders: waiting mode retries on a bad time, /cancel leaves it', async () => {
  const { api, store, say, tap } = await setup();
  await tap('rem:new');
  await say('когда-нибудь потом');
  assert.match(api.last().text, /Не понял, когда напомнить/);
  assert.equal(store.user(CHAT).state.type, 'reminder');
  await say('завтра в 9 позвонить врачу');
  assert.match(api.last().text, /Напомню <b>завтра в 09:00<\/b>/);
  assert.equal(store.user(CHAT).state, null);

  await say('/remind');
  await say('/cancel');
  assert.match(api.last().text, /Отменено/);
  assert.equal(store.user(CHAT).state, null);
});

test('reminders: list and cancel', async () => {
  const { api, store, say, tap, buttons } = await setup();
  await say('/remind завтра в 9 бег');
  await say('/remind через 5 минут чай');
  await say('/reminders');
  const list = api.last();
  assert.match(list.text, /1\.<\/b> сегодня в 13:05 — чай\n<b>2\.<\/b> завтра в 09:00 — бег/);
  await tap(buttons(list)[0]);
  assert.deepEqual(store.user(CHAT).reminders.map((r) => r.text), ['бег']);
});

test('a reminder for a user who blocked the bot is dropped', async () => {
  const { api, store, bot, clock, say } = await setup();
  await say('/remind через 1 минуту тест');
  clock.t += 60_000;
  api.failNext = Object.assign(new Error('Forbidden: bot was blocked by the user'), { code: 403 });
  await bot.checkReminders();
  const u = store.user(CHAT);
  assert.equal(u.reminders.length, 0);
  assert.equal(u.blocked, true);
});

test('a reminder survives a network error and is sent later', async () => {
  const { api, store, bot, clock, say } = await setup();
  await say('/remind через 1 минуту тест');
  clock.t += 60_000;
  api.failNext = new Error('fetch failed');
  await bot.checkReminders();
  assert.equal(store.user(CHAT).reminders.length, 1);
  await bot.checkReminders();
  assert.equal(store.user(CHAT).reminders.length, 0);
  assert.match(api.last().text, /тест/);
});

test('FAQ: buttons and free-text questions', async () => {
  const { api, say, tap } = await setup();
  await say('❓ Вопросы');
  assert.ok(api.last().reply_markup.inline_keyboard.length >= 3);
  await tap('faq:0');
  assert.match(api.last('editMessageText').text, /Бокс · Комбо/);
  await say('как установить на айфон?');
  assert.match(api.last().text, /На экран Домой/);
});

test('unknown text: offer to save as a note or a reminder', async () => {
  const { api, store, say, tap } = await setup();
  await say('паспорт лежит в верхнем ящике');
  assert.match(api.last().text, /Не совсем понял/);
  await tap('pending:note');
  assert.deepEqual(store.user(CHAT).notes.map((n) => n.text), ['паспорт лежит в верхнем ящике']);
  await tap('pending:note');
  assert.equal(api.last('answerCallbackQuery').text, 'Сообщение уже обработано');
});

test('/tz changes the time zone used for reminders', async () => {
  const { api, store, say } = await setup();
  await say('/tz Mars/Olympus');
  assert.match(api.last().text, /Не знаю такого/);
  await say('/tz Asia/Novosibirsk');
  assert.equal(store.user(CHAT).tz, 'Asia/Novosibirsk');
  await say('/remind в 18:00 ужин'); // 17:00 now in Novosibirsk
  assert.equal(store.user(CHAT).reminders[0].at, new Date('2026-10-01T11:00:00Z').getTime());
});

test('/forget wipes the data after confirmation', async () => {
  const { store, say, tap } = await setup();
  await say('/note a');
  await say('/remind через час b');
  await say('/forget');
  await tap('forget:yes');
  const u = store.user(CHAT);
  assert.equal(u.notes.length + u.reminders.length, 0);
});

test('/stats only for admins', async () => {
  const { api, say, bot } = await setup();
  await say('/stats');
  assert.match(api.last().text, /Не знаю такой команды/);
  await bot.handleUpdate({ message: { chat: { id: 7, type: 'private' }, from: { id: 7 }, text: '/stats' } });
  assert.match(api.last().text, /Пользователей: 2/);
});

test('data is saved to the backend', async () => {
  const { backend, store, say } = await setup();
  await say('/note сохрани меня');
  await store.flush();
  assert.equal(backend.saved.users[CHAT].notes[0].text, 'сохрани меня');
  const reopened = await createStore(backend);
  assert.equal(reopened.user(CHAT).notes[0].text, 'сохрани меня');
});
