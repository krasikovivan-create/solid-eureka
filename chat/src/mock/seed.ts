// Demo data: contacts, chats (including two groups) and a short history, created on the first launch.
import type { Chat, Contact, Message } from '../types';
import type { PersistedState } from '../storage/local';
import { getMedia, MEDIA_READY_EVENT, putMedia } from '../storage/media';

const MIN = 60_000;
const HOUR = 60 * MIN;

export const SEED_PHOTO_ID = 'seed-sunset-photo';

/** Phone numbers of the demo contacts (also used to upgrade data saved by the first version). */
export const SEED_PHONES: Record<string, string> = {
  anna: '79161112233',
  max: '79262223344',
  mom: '79031234567',
  dima: '79853334455',
  kate: '79154445566',
  igor: '79995556677',
  sofia: '79206667788',
};

type Profile = Pick<Contact, 'name' | 'phone' | 'gender' | 'about' | 'colors'>;

/** People "registered" on the demo server who are not in your contacts yet — try adding them by number. */
export const DIRECTORY: Profile[] = [
  { name: 'Ольга Никитина', phone: '79161234567', gender: 'f', about: 'Йога и путешествия ✈️', colors: ['#ffecd2', '#fcb69f'] },
  { name: 'Артём Соколов', phone: '79035550101', gender: 'm', about: 'Играю на гитаре 🎸', colors: ['#89f7fe', '#66a6ff'] },
  { name: 'Полина Морозова', phone: '79267778899', gender: 'f', about: 'Учусь на журфаке', colors: ['#fbc2eb', '#a6c1ee'] },
];

export function createSeedState(): PersistedState {
  const now = Date.now();
  const contacts: Contact[] = [
    { id: 'anna', name: 'Анна Смирнова', phone: SEED_PHONES.anna, gender: 'f', about: 'Дизайнер, любит закаты', colors: ['#ff9a8b', '#ff6a88'], online: true, lastSeen: now },
    { id: 'max', name: 'Максим Орлов', phone: SEED_PHONES.max, gender: 'm', about: 'Бэкенд-разработчик', colors: ['#56ccf2', '#2f80ed'], online: false, lastSeen: now - 25 * MIN },
    { id: 'mom', name: 'Мама', phone: SEED_PHONES.mom, gender: 'f', about: '❤️', colors: ['#f6d365', '#fda085'], online: true, lastSeen: now },
    { id: 'dima', name: 'Дмитрий Ковалёв', phone: SEED_PHONES.dima, gender: 'm', about: 'Футбол по четвергам ⚽', colors: ['#84fab0', '#2bb673'], online: false, lastSeen: now - 3 * HOUR },
    { id: 'kate', name: 'Екатерина Волкова', phone: SEED_PHONES.kate, gender: 'f', about: 'Менеджер проекта', colors: ['#a18cd1', '#7b61ff'], online: true, lastSeen: now },
    { id: 'igor', name: 'Игорь Петров', phone: SEED_PHONES.igor, gender: 'm', about: 'В отпуске до понедельника', colors: ['#fccb90', '#d57eeb'], online: false, lastSeen: now - 26 * HOUR },
    { id: 'sofia', name: 'София Лебедева', phone: SEED_PHONES.sofia, gender: 'f', about: 'Фотограф', colors: ['#43e97b', '#38f9d7'], online: false, lastSeen: now - 50 * MIN },
  ];

  const chats: Chat[] = [
    ...contacts.map((c): Chat => ({ id: c.id, kind: 'direct', memberIds: [c.id], createdAt: now - 30 * 24 * HOUR })),
    ...seedGroups(now),
  ];

  const messages: Record<string, Message[]> = {
    ...seedGroupMessages(now),
    anna: [
      msg(now, 'anna', 'them', 'Привет! Как выходные? 😊', 26 * HOUR),
      msg(now, 'anna', 'me', 'Привет! Отлично, ездили за город', 25.9 * HOUR),
      msg(now, 'anna', 'me', '', 25 * HOUR, { call: { kind: 'video', direction: 'out', outcome: 'answered', duration: 734 } }),
      msg(now, 'anna', 'them', 'Смотри, какой закат вчера был 🌅', 12 * MIN, {
        status: 'delivered',
        readAt: undefined,
        media: { id: SEED_PHOTO_ID, kind: 'image', mime: 'image/jpeg', name: 'sunset.jpg', size: 86_000, width: 960, height: 640 },
      }),
      msg(now, 'anna', 'them', 'Кстати, встреча завтра в 11, не забудь', 11 * MIN, { status: 'delivered', readAt: undefined }),
    ],
    max: [
      msg(now, 'max', 'them', 'Задеплоил новую версию API', 5 * HOUR),
      msg(now, 'max', 'me', 'Супер, проверю вечером', 4.8 * HOUR),
      msg(now, 'max', 'me', 'Всё работает 👍 Спасибо!', 40 * MIN, { status: 'delivered', readAt: undefined }),
    ],
    mom: [
      msg(now, 'mom', 'them', 'Как дела? Не забудь пообедать 🙂', 2 * HOUR),
      msg(now, 'mom', 'me', 'Всё хорошо, мам ❤️', 1.9 * HOUR),
      msg(now, 'mom', 'them', '', 1.55 * HOUR, { call: { kind: 'audio', direction: 'in', outcome: 'missed' } }),
      msg(now, 'mom', 'them', 'Позвони, как будет минутка', 1.5 * HOUR),
    ],
    dima: [
      msg(now, 'dima', 'them', 'В четверг играем в 19:00, ты с нами?', 28 * HOUR),
      msg(now, 'dima', 'me', 'Конечно, буду!', 27 * HOUR),
    ],
    kate: [
      msg(now, 'kate', 'them', 'Скинешь макеты до пятницы?', 3 * HOUR),
      msg(now, 'kate', 'me', 'Да, почти готово', 2.9 * HOUR),
      msg(now, 'kate', 'them', 'Отлично, жду 🙌', 2.8 * HOUR),
    ],
    igor: [msg(now, 'igor', 'me', 'Как отпуск? Где отдыхаешь?', 30 * HOUR, { status: 'sent', deliveredAt: undefined, readAt: undefined })],
    sofia: [
      msg(now, 'sofia', 'them', 'Фотосессия переносится на субботу', 3 * 24 * HOUR),
      msg(now, 'sofia', 'me', 'Хорошо, договорились', 3 * 24 * HOUR - 10 * MIN),
    ],
  };

  return { contacts, chats, messages, drafts: {} };
}

export function seedGroups(now: number): Chat[] {
  return [
    { id: 'g-football', kind: 'group', title: 'Футбол по четвергам ⚽', memberIds: ['dima', 'max', 'igor'], colors: ['#84fab0', '#2f80ed'], createdAt: now - 10 * 24 * HOUR },
    { id: 'g-alpha', kind: 'group', title: 'Проект «Альфа»', memberIds: ['kate', 'anna', 'max'], colors: ['#a18cd1', '#fbc2eb'], createdAt: now - 7 * 24 * HOUR },
  ];
}

export function seedGroupMessages(now: number): Record<string, Message[]> {
  return {
    'g-football': [
      msg(now, 'g-football', 'system', 'Дмитрий создал группу «Футбол по четвергам ⚽»', 10 * 24 * HOUR),
      msg(now, 'g-football', 'them', 'Бронь на четверг подтвердили, 19:00 🙌', 29 * HOUR, { senderId: 'dima' }),
      msg(now, 'g-football', 'them', 'Я буду', 28.8 * HOUR, { senderId: 'max' }),
      msg(now, 'g-football', 'me', '+1, возьму мяч', 28.5 * HOUR),
      msg(now, 'g-football', 'them', 'Я пропускаю, в отпуске 🏖️', 26 * HOUR, { senderId: 'igor' }),
    ],
    'g-alpha': [
      msg(now, 'g-alpha', 'system', 'Екатерина создала группу «Проект «Альфа»»', 7 * 24 * HOUR),
      msg(now, 'g-alpha', 'them', 'Коллеги, созвон сегодня в 15:00', 4 * HOUR, { senderId: 'kate' }),
      msg(now, 'g-alpha', 'them', 'Макеты скинула в общую папку', 3.5 * HOUR, { senderId: 'anna' }),
      msg(now, 'g-alpha', 'me', 'Отлично, посмотрю до созвона', 3.4 * HOUR),
      msg(now, 'g-alpha', 'them', 'Бэкенд готов к демо 🚀', 20 * MIN, { senderId: 'max', status: 'delivered', readAt: undefined }),
    ],
  };
}

let n = 0;
function msg(now: number, chatId: string, author: Message['author'], text: string, ago: number, extra: Partial<Message> = {}): Message {
  const createdAt = now - ago;
  const base: Message = { id: `seed-${chatId}-${n++}`, chatId, author, text, createdAt, status: 'read' };
  if (author === 'me') {
    base.sentAt = createdAt + 400;
    base.deliveredAt = createdAt + 900;
    base.readAt = createdAt + 2 * MIN;
  } else if (author === 'them') {
    base.senderId = chatId;
    base.readAt = createdAt + MIN;
  }
  return { ...base, ...extra };
}

/** The demo photo is drawn on a canvas once and stored in IndexedDB like any other photo. */
export async function ensureSeedMedia() {
  try {
    if (await getMedia(SEED_PHOTO_ID)) return;
    const blob = await drawSunset(960, 640);
    if (!blob) return;
    await putMedia(SEED_PHOTO_ID, blob);
    window.dispatchEvent(new CustomEvent(MEDIA_READY_EVENT, { detail: SEED_PHOTO_ID }));
  } catch {
    /* no IndexedDB — the bubble shows a placeholder */
  }
}

function drawSunset(w: number, h: number): Promise<Blob | null> {
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);

  const sky = ctx.createLinearGradient(0, 0, 0, h);
  sky.addColorStop(0, '#2b1055');
  sky.addColorStop(0.45, '#d53369');
  sky.addColorStop(0.7, '#ffb347');
  sky.addColorStop(1, '#ffcc70');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, w, h);

  const sun = ctx.createRadialGradient(w * 0.5, h * 0.66, 10, w * 0.5, h * 0.66, 140);
  sun.addColorStop(0, 'rgba(255,250,220,1)');
  sun.addColorStop(0.35, 'rgba(255,220,120,0.95)');
  sun.addColorStop(1, 'rgba(255,180,80,0)');
  ctx.fillStyle = sun;
  ctx.beginPath();
  ctx.arc(w * 0.5, h * 0.66, 140, 0, Math.PI * 2);
  ctx.fill();

  const ridge = (color: string, base: number, amp: number, seed: number) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let x = 0; x <= w; x += 8) {
      const y = base + Math.sin(x / 90 + seed) * amp + Math.sin(x / 37 + seed * 2) * amp * 0.35;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fill();
  };
  ridge('rgba(90,30,90,0.85)', h * 0.72, 26, 1);
  ridge('rgba(55,20,70,0.92)', h * 0.8, 20, 3);
  ridge('#1e0f33', h * 0.9, 14, 5);

  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.86));
}
