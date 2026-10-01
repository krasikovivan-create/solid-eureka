// Everything the bot says and does. Transport-agnostic: index.js feeds it updates
// (from long polling or a webhook) and calls checkReminders() on a timer.
import { formatWhen, parseReminder } from './timeparse.js';
import defaultFaq from './faq.js';

const MAX_NOTES = 200;
const MAX_NOTE_LEN = 2000;
const MAX_REMINDERS = 50;
const NOTES_PER_PAGE = 8;
const PREVIEW_LEN = 200;
const KEEP_FIRED = 20;

const BTN = {
  notes: '📝 Заметки',
  reminders: '⏰ Напоминания',
  faq: '❓ Вопросы',
  help: 'ℹ️ Помощь',
};

const MAIN_KEYBOARD = {
  keyboard: [
    [{ text: BTN.notes }, { text: BTN.reminders }],
    [{ text: BTN.faq }, { text: BTN.help }],
  ],
  resize_keyboard: true,
  is_persistent: true,
};

export const COMMANDS = [
  { command: 'menu', description: 'Главное меню' },
  { command: 'note', description: 'Новая заметка: /note текст' },
  { command: 'notes', description: 'Мои заметки' },
  { command: 'remind', description: 'Напомнить: /remind через 10 минут чай' },
  { command: 'reminders', description: 'Мои напоминания' },
  { command: 'faq', description: 'Частые вопросы' },
  { command: 'tz', description: 'Мой часовой пояс' },
  { command: 'cancel', description: 'Отменить текущее действие' },
  { command: 'help', description: 'Что умеет бот' },
];

const WHEN_ERRORS = {
  when:
    'Не понял, когда напомнить 🤔 Напиши, например:\n' +
    '• <code>через 20 минут выключить духовку</code>\n' +
    '• <code>в 18:30 тренировка</code>\n' +
    '• <code>завтра в 9 позвонить врачу</code>\n' +
    '• <code>в пятницу в 19:00 кино</code>\n' +
    '• <code>05.10 в 12:00 оплатить интернет</code>',
  text: 'Время понял, а о чём напомнить? Напиши время и текст вместе, например: <code>через час позвонить маме</code>',
  past: 'Это время уже прошло ⌛ Укажи время в будущем.',
  far: 'Слишком далеко — напоминания ставятся не больше чем на год вперёд.',
  date: 'Такой даты нет 📅 Пиши день и месяц через точку, например <code>05.10</code>.',
};

export function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function preview(text, len = PREVIEW_LEN) {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > len ? `${flat.slice(0, len - 1)}…` : flat;
}

function chunk(items, size) {
  const rows = [];
  for (let i = 0; i < items.length; i += size) rows.push(items.slice(i, i + size));
  return rows;
}

function isValidTz(tz) {
  try {
    new Intl.DateTimeFormat('ru', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

export function createBot({ api, store, tz: defaultTz = 'Europe/Moscow', adminIds = [], faq = defaultFaq, now = () => new Date() }) {
  const admins = new Set(adminIds.map(String));
  const tzOf = (u) => u.tz || defaultTz;

  // ---- sending ----

  function send(chatId, text, extra = {}) {
    return api.call('sendMessage', {
      chat_id: chatId,
      text,
      parse_mode: 'HTML',
      link_preview_options: { is_disabled: true },
      ...extra,
    });
  }

  async function edit(msg, text, extra = {}) {
    try {
      await api.call('editMessageText', {
        chat_id: msg.chat.id,
        message_id: msg.message_id,
        text,
        parse_mode: 'HTML',
        link_preview_options: { is_disabled: true },
        ...extra,
      });
    } catch (err) {
      if (!/not modified/i.test(err.message)) throw err;
    }
  }

  const inline = (rows) => ({ reply_markup: { inline_keyboard: rows } });

  // ---- screens ----

  function welcome(u, firstName) {
    const hello = firstName ? `Привет, ${escapeHtml(firstName)}! 👋` : 'Привет! 👋';
    return send(
      u.id,
      `${hello}\n\nЯ бот-помощник. Умею:\n` +
        '📝 хранить заметки;\n' +
        '⏰ напоминать о делах в нужное время;\n' +
        '❓ отвечать на частые вопросы.\n\n' +
        'Выбирай раздел в меню внизу 👇 или просто напиши мне.',
      { reply_markup: MAIN_KEYBOARD },
    );
  }

  function help(u) {
    return send(
      u.id,
      '<b>Что я умею</b>\n\n' +
        '📝 <b>Заметки</b> — нажми «Заметки» → «Новая заметка» или напиши <code>/note купить молоко</code>. ' +
        'Список — /notes, удалить — кнопкой 🗑.\n\n' +
        '⏰ <b>Напоминания</b> — напиши <code>/remind через 30 минут проверить духовку</code> ' +
        'или начни сообщение со слова «напомни»: <code>напомни завтра в 9 позвонить врачу</code>. ' +
        'Список — /reminders.\n\n' +
        '❓ <b>Вопросы</b> — ответы на частые вопросы (/faq). Можно просто спросить своими словами.\n\n' +
        `🌍 Часовой пояс: <b>${escapeHtml(tzOf(u))}</b> — поменять: /tz\n` +
        '↩️ Передумал — /cancel. Удалить все свои данные — /forget.',
      { reply_markup: MAIN_KEYBOARD },
    );
  }

  function notesView(u, page = 0) {
    const notes = [...u.notes].reverse(); // newest first
    if (!notes.length) {
      return {
        text: '📝 Заметок пока нет.\n\nНажми «➕ Новая заметка» или напиши <code>/note текст</code>.',
        extra: inline([[{ text: '➕ Новая заметка', callback_data: 'note:new' }]]),
      };
    }
    const pages = Math.ceil(notes.length / NOTES_PER_PAGE);
    page = Math.min(Math.max(0, page), pages - 1);
    const start = page * NOTES_PER_PAGE;
    const shown = notes.slice(start, start + NOTES_PER_PAGE);
    const lines = shown.map((n, i) => `<b>${start + i + 1}.</b> ${escapeHtml(preview(n.text))}`);
    const rows = chunk(
      shown.map((n, i) => ({ text: `🗑 ${start + i + 1}`, callback_data: `note:del:${n.id}:${page}` })),
      4,
    );
    if (pages > 1) {
      const nav = [];
      if (page > 0) nav.push({ text: '◀️', callback_data: `notes:p:${page - 1}` });
      nav.push({ text: `${page + 1} / ${pages}`, callback_data: 'noop' });
      if (page < pages - 1) nav.push({ text: '▶️', callback_data: `notes:p:${page + 1}` });
      rows.push(nav);
    }
    rows.push([{ text: '➕ Новая заметка', callback_data: 'note:new' }]);
    return {
      text: `📝 <b>Заметки</b> (${notes.length})\n\n${lines.join('\n\n')}`,
      extra: inline(rows),
    };
  }

  function remindersView(u) {
    const list = [...u.reminders].sort((a, b) => a.at - b.at);
    if (!list.length) {
      return {
        text:
          '⏰ Активных напоминаний нет.\n\nНажми «➕ Новое напоминание» или напиши, например, ' +
          '<code>напомни через 15 минут снять чайник</code>.',
        extra: inline([[{ text: '➕ Новое напоминание', callback_data: 'rem:new' }]]),
      };
    }
    const tz = tzOf(u);
    const lines = list.map(
      (r, i) => `<b>${i + 1}.</b> ${formatWhen(new Date(r.at), tz, now())} — ${escapeHtml(preview(r.text, 150))}`,
    );
    const rows = chunk(list.map((r, i) => ({ text: `❌ ${i + 1}`, callback_data: `rem:del:${r.id}` })), 4);
    rows.push([{ text: '➕ Новое напоминание', callback_data: 'rem:new' }]);
    return { text: `⏰ <b>Напоминания</b> (${list.length})\n\n${lines.join('\n')}`, extra: inline(rows) };
  }

  function faqView() {
    return {
      text: '❓ <b>Частые вопросы</b>\n\nВыбери вопрос или просто спроси своими словами.',
      extra: inline(faq.map((item, i) => [{ text: item.q, callback_data: `faq:${i}` }])),
    };
  }

  const show = (u, view) => send(u.id, view.text, view.extra);

  // ---- actions ----

  async function addNote(u, text) {
    text = text.trim();
    if (!text) return send(u.id, 'Пустую заметку не сохраню 🙂 Напиши текст.');
    if (text.length > MAX_NOTE_LEN) {
      return send(u.id, `Слишком длинно — до ${MAX_NOTE_LEN} символов. Раздели на несколько заметок.`);
    }
    if (u.notes.length >= MAX_NOTES) {
      return send(u.id, `Заметок уже ${MAX_NOTES} — это максимум. Удали ненужные в /notes.`);
    }
    u.notes.push({ id: store.newId(), text, at: now().getTime() });
    u.state = null;
    store.changed();
    return send(u.id, `✅ Заметка сохранена. Всего: ${u.notes.length}.`, inline([[
      { text: '📝 Все заметки', callback_data: 'notes:p:0' },
      { text: '➕ Ещё одна', callback_data: 'note:new' },
    ]]));
  }

  async function addReminder(u, input) {
    if (u.reminders.length >= MAX_REMINDERS) {
      u.state = null;
      store.changed();
      return send(u.id, `Напоминаний уже ${MAX_REMINDERS} — это максимум. Удали лишние в /reminders.`);
    }
    const tz = tzOf(u);
    const r = parseReminder(input, now(), tz);
    if (r.error) {
      // Stay in "waiting for a reminder" mode so the user can just try again.
      u.state = { type: 'reminder' };
      store.changed();
      return send(u.id, `${WHEN_ERRORS[r.error]}\n\n↩️ /cancel — отменить.`);
    }
    const text = r.text.slice(0, MAX_NOTE_LEN);
    const reminder = { id: store.newId(), text, at: r.at.getTime(), createdAt: now().getTime() };
    u.reminders.push(reminder);
    u.state = null;
    store.changed();
    return send(
      u.id,
      `✅ Напомню <b>${formatWhen(r.at, tz, now())}</b>:\n${escapeHtml(text)}`,
      inline([[
        { text: '❌ Отменить', callback_data: `rem:del:${reminder.id}:x` },
        { text: '⏰ Все напоминания', callback_data: 'rem:list' },
      ]]),
    );
  }

  function askNote(u) {
    u.state = { type: 'note' };
    store.changed();
    return send(u.id, '✍️ Напиши текст заметки одним сообщением.\n\n↩️ /cancel — отменить.');
  }

  function askReminder(u) {
    u.state = { type: 'reminder' };
    store.changed();
    return send(
      u.id,
      '⏰ Когда и о чём напомнить? Например:\n' +
        '• <code>через 20 минут выключить духовку</code>\n' +
        '• <code>в 18:30 тренировка</code>\n' +
        '• <code>завтра в 9 позвонить врачу</code>\n\n' +
        '↩️ /cancel — отменить.',
    );
  }

  function setTz(u, arg) {
    arg = arg.trim();
    if (!arg) {
      return send(
        u.id,
        `🌍 Твой часовой пояс: <b>${escapeHtml(tzOf(u))}</b>\n` +
          `Сейчас у тебя ${formatWhen(now(), tzOf(u), now()).replace('сегодня в ', '')}.\n\n` +
          'Поменять: <code>/tz Europe/Moscow</code>, <code>/tz Asia/Yekaterinburg</code>, ' +
          '<code>/tz Europe/Kaliningrad</code>, <code>/tz Asia/Novosibirsk</code>…',
      );
    }
    if (!isValidTz(arg)) {
      return send(u.id, 'Не знаю такого часового пояса 🤷 Пиши как <code>Europe/Moscow</code> или <code>Asia/Almaty</code>.');
    }
    u.tz = arg;
    store.changed();
    return send(u.id, `✅ Часовой пояс: <b>${escapeHtml(arg)}</b>. Сейчас у тебя ${formatWhen(now(), arg, now()).replace('сегодня в ', '')}.`);
  }

  function findFaq(text) {
    const t = ` ${text.toLowerCase().replace(/ё/g, 'е')} `;
    let best = null;
    let bestScore = 0;
    for (const item of faq) {
      const score = (item.keywords || []).filter((k) => t.includes(k)).length;
      if (score > bestScore) {
        best = item;
        bestScore = score;
      }
    }
    return best;
  }

  // ---- incoming messages ----

  async function onCommand(u, msg, cmd, arg) {
    switch (cmd) {
      case 'start':
      case 'menu':
        u.state = null;
        store.changed();
        return welcome(u, msg.from?.first_name);
      case 'help':
        return help(u);
      case 'note':
        return arg.trim() ? addNote(u, arg) : askNote(u);
      case 'notes':
        return show(u, notesView(u));
      case 'remind':
        return arg.trim() ? addReminder(u, arg) : askReminder(u);
      case 'reminders':
        return show(u, remindersView(u));
      case 'faq':
        return show(u, faqView());
      case 'tz':
        return setTz(u, arg);
      case 'cancel':
        if (!u.state) return send(u.id, 'Нечего отменять 🙂', { reply_markup: MAIN_KEYBOARD });
        u.state = null;
        store.changed();
        return send(u.id, '↩️ Отменено.', { reply_markup: MAIN_KEYBOARD });
      case 'forget':
        return send(
          u.id,
          `Удалить все твои заметки (${u.notes.length}) и напоминания (${u.reminders.length})? Это нельзя отменить.`,
          inline([[
            { text: '🗑 Да, удалить всё', callback_data: 'forget:yes' },
            { text: 'Нет', callback_data: 'forget:no' },
          ]]),
        );
      case 'stats':
        if (admins.has(String(msg.from?.id))) return stats(u);
      // falls through for non-admins
      default:
        return send(u.id, 'Не знаю такой команды 🤔 Список — /help');
    }
  }

  function stats(u) {
    const all = store.users();
    const day = now().getTime() - 24 * 3600 * 1000;
    const sum = (f) => all.reduce((s, x) => s + f(x), 0);
    return send(
      u.id,
      '📊 <b>Статистика</b>\n\n' +
        `Пользователей: ${all.length} (новых за сутки: ${all.filter((x) => x.joinedAt > day).length})\n` +
        `Заблокировали бота: ${all.filter((x) => x.blocked).length}\n` +
        `Заметок: ${sum((x) => x.notes.length)}\n` +
        `Активных напоминаний: ${sum((x) => x.reminders.length)}\n` +
        `Хранилище: ${escapeHtml(store.backendName)}`,
    );
  }

  async function onText(u, msg) {
    const text = msg.text;
    const cmd = text.match(/^\/([a-z_]+)(?:@\w+)?(?:\s+([\s\S]*))?$/i);
    if (cmd) return onCommand(u, msg, cmd[1].toLowerCase(), cmd[2] || '');

    const menu = Object.values(BTN).includes(text);
    if (menu && u.state) {
      u.state = null;
      store.changed();
    }
    switch (text) {
      case BTN.notes:
        return show(u, notesView(u));
      case BTN.reminders:
        return show(u, remindersView(u));
      case BTN.faq:
        return show(u, faqView());
      case BTN.help:
        return help(u);
    }

    if (u.state?.type === 'note') return addNote(u, text);
    if (u.state?.type === 'reminder') return addReminder(u, text);
    if (/^напомн(?:и|ить)(?:[\s,!]|$)/i.test(text)) return addReminder(u, text);

    const answer = findFaq(text);
    if (answer) return send(u.id, answer.a, inline([[{ text: '❓ Другие вопросы', callback_data: 'faq:list' }]]));

    // Not sure what this is — offer to keep it.
    u.pending = text.slice(0, MAX_NOTE_LEN);
    store.changed();
    return send(u.id, 'Не совсем понял 🙂 Что сделать с этим сообщением?', inline([
      [{ text: '📝 Сохранить в заметки', callback_data: 'pending:note' }],
      [{ text: '⏰ Сделать напоминанием', callback_data: 'pending:rem' }],
    ]));
  }

  // ---- buttons ----

  async function onCallback(cq) {
    const msg = cq.message;
    const u = store.user(msg?.chat?.id ?? cq.from.id, cq.from);
    const [kind, action, ...rest] = (cq.data || '').split(':');
    let toast = '';

    try {
      if (kind === 'notes' && action === 'p') {
        const view = notesView(u, +rest[0]);
        await edit(msg, view.text, view.extra);
      } else if (kind === 'note' && action === 'new') {
        await askNote(u);
      } else if (kind === 'note' && action === 'del') {
        const before = u.notes.length;
        u.notes = u.notes.filter((n) => n.id !== +rest[0]);
        toast = u.notes.length < before ? '🗑 Удалено' : 'Уже удалено';
        store.changed();
        const view = notesView(u, +rest[1] || 0);
        await edit(msg, view.text, view.extra);
      } else if (kind === 'rem' && action === 'new') {
        await askReminder(u);
      } else if (kind === 'rem' && action === 'list') {
        await show(u, remindersView(u));
      } else if (kind === 'rem' && action === 'del') {
        const r = u.reminders.find((x) => x.id === +rest[0]);
        u.reminders = u.reminders.filter((x) => x !== r);
        store.changed();
        toast = r ? '❌ Напоминание отменено' : 'Уже неактивно';
        if (rest[1] === 'x') {
          // Pressed under the "✅ Напомню …" confirmation.
          if (r) await edit(msg, `<s>${escapeHtml(preview(r.text))}</s>\n❌ Напоминание отменено.`);
        } else {
          const view = remindersView(u);
          await edit(msg, view.text, view.extra);
        }
      } else if (kind === 'rem' && action === 'snooze') {
        const fired = (u.fired || []).find((x) => x.id === +rest[0]);
        if (!fired) {
          toast = 'Не нашёл это напоминание';
        } else {
          const tz = tzOf(u);
          let at;
          if (rest[1] === 'tomorrow') {
            at = parseReminder('завтра в 9 x', now(), tz).at;
          } else {
            at = new Date(now().getTime() + +rest[1] * 60_000);
          }
          u.fired = u.fired.filter((x) => x !== fired);
          u.reminders.push({ ...fired, at: at.getTime() });
          store.changed();
          toast = '⏰ Отложено';
          await edit(msg, `⏰ ${escapeHtml(fired.text)}\n\n<i>Отложено — напомню ${formatWhen(at, tz, now())}.</i>`);
        }
      } else if (kind === 'rem' && action === 'done') {
        u.fired = (u.fired || []).filter((x) => x.id !== +rest[0]);
        store.changed();
        toast = '✅';
        await edit(msg, `✅ <s>${escapeHtml(msg.text?.replace(/^⏰\s*Напоминание\s*/, '') || '')}</s>`);
      } else if (kind === 'faq' && action === 'list') {
        const view = faqView();
        await edit(msg, view.text, view.extra);
      } else if (kind === 'faq') {
        const item = faq[+action];
        if (item) {
          await edit(msg, `<b>${escapeHtml(item.q)}</b>\n\n${item.a}`, inline([[{ text: '◀️ Все вопросы', callback_data: 'faq:list' }]]));
        }
      } else if (kind === 'pending') {
        const text = u.pending;
        u.pending = null;
        store.changed();
        if (!text) {
          toast = 'Сообщение уже обработано';
        } else {
          await api.call('editMessageReplyMarkup', { chat_id: msg.chat.id, message_id: msg.message_id }).catch(() => {});
          if (action === 'note') await addNote(u, text);
          else await addReminder(u, text);
        }
      } else if (kind === 'forget') {
        if (action === 'yes') {
          u.notes = [];
          u.reminders = [];
          u.fired = [];
          u.state = null;
          u.pending = null;
          store.changed();
          await edit(msg, '🗑 Все твои заметки и напоминания удалены.');
        } else {
          await edit(msg, 'Хорошо, ничего не удаляю 🙂');
        }
      }
    } finally {
      // Always stop the button's spinner, even if editing the message failed.
      await api.call('answerCallbackQuery', { callback_query_id: cq.id, text: toast || undefined }).catch(() => {});
    }
  }

  // ---- entry points ----

  async function handleUpdate(update) {
    if (update.callback_query) return onCallback(update.callback_query);

    const msg = update.message;
    if (!msg?.chat) return;
    const u = store.user(msg.chat, msg.from);
    if (u.blocked) {
      u.blocked = false;
      store.changed();
    }
    if (typeof msg.text === 'string') return onText(u, msg);
    if (msg.caption && u.state?.type === 'note') return addNote(u, msg.caption);
    if (msg.chat.type === 'private') {
      return send(u.id, 'Я понимаю только текст ✍️ Напиши словами или выбери раздел в меню.', { reply_markup: MAIN_KEYBOARD });
    }
  }

  let checking = false;
  async function checkReminders() {
    if (checking) return;
    checking = true;
    try {
      const t = now().getTime();
      for (const u of store.users()) {
        const due = u.reminders.filter((r) => r.at <= t);
        for (const r of due) {
          const lateMin = Math.round((t - r.at) / 60_000);
          const late = lateMin >= 3 ? `\n\n<i>С опозданием на ${lateMin} мин — бот был недоступен.</i>` : '';
          try {
            await send(u.id, `⏰ <b>Напоминание</b>\n\n${escapeHtml(r.text)}${late}`, inline([
              [
                { text: '+10 мин', callback_data: `rem:snooze:${r.id}:10` },
                { text: '+1 час', callback_data: `rem:snooze:${r.id}:60` },
                { text: 'Завтра', callback_data: `rem:snooze:${r.id}:tomorrow` },
              ],
              [{ text: '✅ Готово', callback_data: `rem:done:${r.id}` }],
            ]));
          } catch (err) {
            if (err.code === 403 || err.code === 400) {
              // Bot blocked or chat gone: drop the reminder, nobody can receive it.
              if (err.code === 403) u.blocked = true;
            } else {
              r.attempts = (r.attempts || 0) + 1;
              console.error(`Reminder ${r.id} for ${u.id} failed (${r.attempts}):`, err.message);
              if (r.attempts < 5) continue;
            }
          }
          u.reminders = u.reminders.filter((x) => x !== r);
          u.fired = [...(u.fired || []), { id: r.id, text: r.text, createdAt: r.createdAt }].slice(-KEEP_FIRED);
          store.changed();
        }
      }
    } finally {
      checking = false;
    }
  }

  async function setup() {
    await api.call('setMyCommands', { commands: COMMANDS });
  }

  return { handleUpdate, checkReminders, setup };
}
