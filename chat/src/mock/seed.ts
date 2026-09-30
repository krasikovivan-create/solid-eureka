// Demo data: contacts and a short history, created on the first launch.
import type { Contact, Message } from '../types';
import type { PersistedState } from '../storage/local';
import { getMedia, MEDIA_READY_EVENT, putMedia } from '../storage/media';

const MIN = 60_000;
const HOUR = 60 * MIN;

export const SEED_PHOTO_ID = 'seed-sunset-photo';

export function createSeedState(): PersistedState {
  const now = Date.now();
  const contacts: Contact[] = [
    { id: 'anna', name: 'Анна Смирнова', gender: 'f', about: 'Дизайнер, любит закаты', colors: ['#ff9a8b', '#ff6a88'], online: true, lastSeen: now },
    { id: 'max', name: 'Максим Орлов', gender: 'm', about: 'Бэкенд-разработчик', colors: ['#56ccf2', '#2f80ed'], online: false, lastSeen: now - 25 * MIN },
    { id: 'mom', name: 'Мама', gender: 'f', about: '❤️', colors: ['#f6d365', '#fda085'], online: true, lastSeen: now },
    { id: 'dima', name: 'Дмитрий Ковалёв', gender: 'm', about: 'Футбол по четвергам ⚽', colors: ['#84fab0', '#2bb673'], online: false, lastSeen: now - 3 * HOUR },
    { id: 'kate', name: 'Екатерина Волкова', gender: 'f', about: 'Менеджер проекта', colors: ['#a18cd1', '#7b61ff'], online: true, lastSeen: now },
    { id: 'igor', name: 'Игорь Петров', gender: 'm', about: 'В отпуске до понедельника', colors: ['#fccb90', '#d57eeb'], online: false, lastSeen: now - 26 * HOUR },
    { id: 'sofia', name: 'София Лебедева', gender: 'f', about: 'Фотограф', colors: ['#43e97b', '#38f9d7'], online: false, lastSeen: now - 50 * MIN },
  ];

  let n = 0;
  const msg = (chatId: string, author: 'me' | 'them', text: string, ago: number, extra: Partial<Message> = {}): Message => {
    const createdAt = now - ago;
    const base: Message = { id: `seed-${chatId}-${n++}`, chatId, author, text, createdAt, status: 'read' };
    if (author === 'me') {
      base.sentAt = createdAt + 400;
      base.deliveredAt = createdAt + 900;
      base.readAt = createdAt + 2 * MIN;
    } else {
      base.readAt = createdAt + MIN;
    }
    return { ...base, ...extra };
  };

  const messages: Record<string, Message[]> = {
    anna: [
      msg('anna', 'them', 'Привет! Как выходные? 😊', 26 * HOUR),
      msg('anna', 'me', 'Привет! Отлично, ездили за город', 25.9 * HOUR),
      msg('anna', 'them', 'Смотри, какой закат вчера был 🌅', 12 * MIN, {
        status: 'delivered',
        readAt: undefined,
        media: { id: SEED_PHOTO_ID, kind: 'image', mime: 'image/jpeg', name: 'sunset.jpg', size: 86_000, width: 960, height: 640 },
      }),
      msg('anna', 'them', 'Кстати, встреча завтра в 11, не забудь', 11 * MIN, { status: 'delivered', readAt: undefined }),
    ],
    max: [
      msg('max', 'them', 'Задеплоил новую версию API', 5 * HOUR),
      msg('max', 'me', 'Супер, проверю вечером', 4.8 * HOUR),
      msg('max', 'me', 'Всё работает 👍 Спасибо!', 40 * MIN, { status: 'delivered', readAt: undefined }),
    ],
    mom: [
      msg('mom', 'them', 'Как дела? Не забудь пообедать 🙂', 2 * HOUR),
      msg('mom', 'me', 'Всё хорошо, мам ❤️', 1.9 * HOUR),
      msg('mom', 'them', 'Позвони, как будет минутка', 1.5 * HOUR),
    ],
    dima: [
      msg('dima', 'them', 'В четверг играем в 19:00, ты с нами?', 28 * HOUR),
      msg('dima', 'me', 'Конечно, буду!', 27 * HOUR),
    ],
    kate: [
      msg('kate', 'them', 'Скинешь макеты до пятницы?', 3 * HOUR),
      msg('kate', 'me', 'Да, почти готово', 2.9 * HOUR),
      msg('kate', 'them', 'Отлично, жду 🙌', 2.8 * HOUR),
    ],
    igor: [msg('igor', 'me', 'Как отпуск? Где отдыхаешь?', 30 * HOUR, { status: 'sent', deliveredAt: undefined, readAt: undefined })],
    sofia: [
      msg('sofia', 'them', 'Фотосессия переносится на субботу', 3 * 24 * HOUR),
      msg('sofia', 'me', 'Хорошо, договорились', 3 * 24 * HOUR - 10 * MIN),
    ],
  };

  return { contacts, messages, drafts: {} };
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
