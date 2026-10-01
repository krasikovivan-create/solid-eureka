// Understands reminder times written the way people type them in Russian:
//   «через 10 минут позвонить маме», «через час и 30 минут …», «через полчаса …», «15м …», «2ч …»
//   «в 18:30 …», «18:30 …», «в 9 вечера …», «завтра в 9 …», «послезавтра …»
//   «в пятницу в 19:00 …», «05.10 в 12:00 …», «05.10.2027 …»
// The time can also stand at the end: «позвонить маме завтра в 10».
// Wall-clock times are read in the bot's time zone (an IANA name such as Europe/Moscow).

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

const UNIT_RE =
  /^(\d+(?:[.,]\d+)?)?\s*(полчаса|минут[аыу]?|мин|м|min|m|час(?:а|ов)?|ч|h|дн(?:я|ей)|день|д|d|недел[юиья]|нед|w)(?=[\s,.!:;-]|$)/;

function unitMs(unit) {
  if (unit === 'полчаса') return 30 * MIN;
  if (/^(м|m)/.test(unit)) return MIN;
  if (/^(ч|h)/.test(unit)) return HOUR;
  if (/^(н|w)/.test(unit)) return 7 * DAY;
  return DAY;
}

const WEEKDAYS = {
  понедельник: 1, пн: 1,
  вторник: 2, вт: 2,
  среда: 3, среду: 3, ср: 3,
  четверг: 4, чт: 4,
  пятница: 5, пятницу: 5, пт: 5,
  суббота: 6, субботу: 6, сб: 6,
  воскресенье: 0, вс: 0,
};

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

// ---- time zone helpers (Intl only, no libraries) ----

const formatters = new Map();
function formatter(tz) {
  if (!formatters.has(tz)) {
    formatters.set(tz, new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hourCycle: 'h23', weekday: 'short',
      year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric',
    }));
  }
  return formatters.get(tz);
}

const WD = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

/** Wall-clock parts of `date` in time zone `tz`. */
export function zonedParts(date, tz) {
  const p = {};
  for (const { type, value } of formatter(tz).formatToParts(date)) p[type] = value;
  return {
    year: +p.year, month: +p.month, day: +p.day,
    hour: +p.hour, minute: +p.minute, second: +p.second,
    weekday: WD[p.weekday],
  };
}

function offsetAt(ts, tz) {
  const p = zonedParts(new Date(ts), tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - (ts - (((ts % 1000) + 1000) % 1000));
}

/** The moment when the clock in `tz` shows the given wall time. */
export function zonedToUtc({ year, month, day, hour = 0, minute = 0 }, tz) {
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  const first = offsetAt(guess, tz);
  let ts = guess - first;
  const second = offsetAt(ts, tz);
  if (second !== first) ts = guess - second;
  return new Date(ts);
}

function addDays({ year, month, day }, n) {
  const d = new Date(Date.UTC(year, month - 1, day + n));
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

function dayNumber({ year, month, day }) {
  return Date.UTC(year, month - 1, day) / DAY;
}

// ---- parsing ----

function parseRelative(s, now) {
  const via = s.match(/^через\s+/);
  let pos = via ? via[0].length : 0;
  let total = 0;
  let count = 0;
  for (;;) {
    const u = s.slice(pos).match(UNIT_RE);
    if (!u) break;
    const [, num, unit] = u;
    if (unit === 'полчаса' && num) break;
    if (!num && unit !== 'полчаса' && !(via && count === 0)) break;
    total += (num ? parseFloat(num.replace(',', '.')) : 1) * unitMs(unit);
    count++;
    pos += u[0].length;
    pos += s.slice(pos).match(/^\s*(?:и\s+)?/)[0].length;
  }
  if (!count) return null;
  if (total < MIN) return { error: 'when' };
  if (total > 366 * DAY) return { error: 'far' };
  return { at: new Date(now.getTime() + Math.round(total / 1000) * 1000), consumed: pos };
}

function parseAbsolute(s, now, tz) {
  const today = zonedParts(now, tz);
  let pos = 0;
  const eat = (re) => {
    const m = s.slice(pos).match(re);
    if (m) pos += m[0].length;
    return m;
  };

  let date = null;
  let kind = null; // 'rel-day' | 'weekday' | 'date' | 'date-year'
  let r;
  if ((r = eat(/^(сегодня|завтра|послезавтра)(?=[\s,]|$)\s*/))) {
    date = addDays(today, { сегодня: 0, завтра: 1, послезавтра: 2 }[r[1]]);
    kind = 'rel-day';
  } else if ((r = eat(new RegExp(`^(?:во?\\s+)?(${Object.keys(WEEKDAYS).join('|')})(?=[\\s,]|$)\\s*`)))) {
    date = addDays(today, (WEEKDAYS[r[1]] - today.weekday + 7) % 7);
    kind = 'weekday';
  } else if ((r = eat(/^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?=[\s,]|$)\s*/))) {
    const day = +r[1];
    const month = +r[2];
    let year = r[3] ? +r[3] : today.year;
    if (r[3] && r[3].length === 2) year += 2000;
    const check = new Date(Date.UTC(year, month - 1, day));
    if (month < 1 || month > 12 || check.getUTCDate() !== day) return { error: 'date' };
    date = { year, month, day };
    kind = r[3] ? 'date-year' : 'date';
  }

  let time = null;
  if (
    (r = eat(/^(?:в|к)\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*(утра|дня|вечера|ночи))?(?=[\s,.!]|$)\s*/)) ||
    (r = eat(/^(\d{1,2}):(\d{2})(?:\s*(утра|дня|вечера|ночи))?(?=[\s,.!]|$)\s*/))
  ) {
    let hour = +r[1];
    const minute = r[2] ? +r[2] : 0;
    if (hour > 23 || minute > 59) return { error: 'when' };
    if ((r[3] === 'вечера' || r[3] === 'дня') && hour < 12) hour += 12;
    if (r[3] === 'ночи' && hour === 12) hour = 0;
    time = { hour, minute };
  }

  if (!date && !time) return null;
  time ||= { hour: 9, minute: 0 };
  date ||= today;

  let at = zonedToUtc({ ...date, ...time }, tz);
  if (at <= now) {
    if (!kind) at = zonedToUtc({ ...addDays(date, 1), ...time }, tz);
    else if (kind === 'weekday') at = zonedToUtc({ ...addDays(date, 7), ...time }, tz);
    else if (kind === 'date') at = zonedToUtc({ ...date, year: date.year + 1, ...time }, tz);
    else return { error: 'past' };
  }
  if (at - now > 366 * DAY) return { error: 'far' };
  return { at, consumed: pos };
}

function parseWhen(s, now, tz) {
  return parseRelative(s, now) || parseAbsolute(s, now, tz);
}

function cleanText(text) {
  return text
    .replace(/^[\s,.:;—–-]+|[\s,:;—–-]+$/g, '')
    .replace(/^(?:что(?:бы)?|о|об)\s+/i, '')
    .trim();
}

/**
 * Splits «через 10 минут позвонить маме» into the moment and the text.
 * Returns { at: Date, text } or { error: 'when' | 'text' | 'past' | 'far' | 'date' }.
 */
export function parseReminder(input, now = new Date(), tz = 'Europe/Moscow') {
  let s = input.trim().replace(/\s+/g, ' ');
  const prefix = s.toLowerCase().match(/^напомн(?:и|ить)(?:,?\s*пожалуйста)?(?:\s+мне)?[\s,]*/);
  if (prefix) s = s.slice(prefix[0].length);
  // toLowerCase and ё→е keep the length, so offsets in `lower` are valid in `s`.
  const lower = s.toLowerCase().replace(/ё/g, 'е');

  let found = parseWhen(lower, now, tz);
  let text;
  if (found) {
    text = s.slice(found.consumed || 0);
  } else {
    // The time may stand at the end: take the longest tail that is entirely a time.
    for (let i = 1; i < lower.length; i++) {
      if (lower[i - 1] !== ' ') continue;
      const tail = lower.slice(i);
      const w = parseWhen(tail, now, tz);
      if (w && !w.error && w.consumed >= tail.trimEnd().length) {
        found = w;
        text = s.slice(0, i);
        break;
      }
    }
  }

  if (!found) return { error: 'when' };
  if (found.error) return { error: found.error };
  text = cleanText(text);
  if (!text) return { error: 'text' };
  return { at: found.at, text };
}

/** «сегодня в 14:20», «завтра в 09:00», «3 окт в 10:00», «3 окт 2027 в 10:00». */
export function formatWhen(at, tz, now = new Date()) {
  const p = zonedParts(at, tz);
  const n = zonedParts(now, tz);
  const diff = dayNumber(p) - dayNumber(n);
  const hhmm = `${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}`;
  const day =
    diff === 0 ? 'сегодня'
    : diff === 1 ? 'завтра'
    : diff === 2 ? 'послезавтра'
    : `${p.day} ${MONTHS[p.month - 1]}${p.year !== n.year ? ` ${p.year}` : ''}`;
  return `${day} в ${hhmm}`;
}
