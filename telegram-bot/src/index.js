// Telegram helper bot: notes, reminders, FAQ. No dependencies, Node 22+.
//
// Two ways to receive messages:
//  - long polling (default) — just run it on your computer, nothing else needed;
//  - webhook — when WEBHOOK_URL is set (or RENDER_EXTERNAL_URL, which Render sets by itself):
//    Telegram POSTs updates to <url>/telegram, and an idle free Render service wakes up on them.
//
// Environment (a .env file next to package.json is read too):
//   BOT_TOKEN                 token from @BotFather (required)
//   BOT_TZ                    default time zone for reminders (default Europe/Moscow)
//   ADMIN_IDS                 comma-separated Telegram user ids allowed to use /stats
//   PORT                      HTTP port for /health and the webhook (Render sets it; default 8080)
//   WEBHOOK_URL               public https address of this server → webhook mode
//   WEBHOOK_SECRET            secret Telegram sends back in a header (default: derived from the token)
//   DATA_DIR                  where db.json lives (default ./data)
//   UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN   keep data in Upstash Redis instead of a file
//   TELEGRAM_API_URL          another Bot API server (a self-hosted one, or a fake one in tests)
import http from 'node:http';
import { createHash } from 'node:crypto';
import { createApi } from './telegram.js';
import { backendFromEnv, createStore } from './store.js';
import { createBot } from './bot.js';

const env = process.env;
const TOKEN = env.BOT_TOKEN?.trim();
if (!TOKEN) {
  console.error('BOT_TOKEN is not set. Get a token from @BotFather and put it into .env (see .env.example).');
  process.exit(1);
}

const TZ = env.BOT_TZ || 'Europe/Moscow';
const PORT = Number(env.PORT) || 8080;
const PUBLIC_URL = (env.WEBHOOK_URL || env.RENDER_EXTERNAL_URL || '').replace(/\/+$/, '');
const SECRET = env.WEBHOOK_SECRET || createHash('sha256').update(`webhook:${TOKEN}`).digest('hex').slice(0, 48);
const ALLOWED_UPDATES = ['message', 'callback_query'];

const api = createApi(TOKEN, { baseUrl: env.TELEGRAM_API_URL || undefined });
const store = await createStore(backendFromEnv(env));
const bot = createBot({
  api,
  store,
  tz: TZ,
  adminIds: (env.ADMIN_IDS || '').split(',').map((s) => s.trim()).filter(Boolean),
});

// Handle updates one at a time so two quick taps can't race each other.
let queue = Promise.resolve();
function enqueue(update) {
  queue = queue
    .then(() => bot.handleUpdate(update))
    .catch((err) => console.error('Update failed:', err.message));
  return queue;
}

const me = await api.call('getMe');
console.log(`@${me.username} started · data: ${store.backendName} · time zone: ${TZ}`);
await bot.setup().catch((err) => console.error('setMyCommands failed:', err.message));

// ---- HTTP: health check + webhook ----

const server = http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/telegram' && PUBLIC_URL) {
    if (req.headers['x-telegram-bot-api-secret-token'] !== SECRET) {
      res.writeHead(401).end();
      return;
    }
    let body = '';
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > 1_000_000) req.destroy();
      else body += chunk;
    });
    req.on('end', () => {
      res.writeHead(200).end();
      try {
        enqueue(JSON.parse(body));
      } catch {
        console.error('Bad webhook body');
      }
    });
    return;
  }
  if (req.method === 'GET' && (req.url === '/' || req.url === '/health')) {
    res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8' }).end(`ok @${me.username}`);
    return;
  }
  res.writeHead(404).end();
});
server.listen(PORT, () => console.log(`HTTP on :${PORT}`));

// ---- receiving updates ----

let stopped = false;

if (PUBLIC_URL) {
  await api.call('setWebhook', { url: `${PUBLIC_URL}/telegram`, secret_token: SECRET, allowed_updates: ALLOWED_UPDATES });
  console.log(`Webhook: ${PUBLIC_URL}/telegram`);
} else {
  await api.call('deleteWebhook');
  console.log('Long polling — write to the bot in Telegram');
  poll();
}

async function poll() {
  let offset = 0;
  while (!stopped) {
    try {
      const updates = await api.call('getUpdates', { offset, timeout: 30, allowed_updates: ALLOWED_UPDATES });
      for (const update of updates) {
        offset = update.update_id + 1;
        enqueue(update);
      }
    } catch (err) {
      if (stopped) break;
      console.error('getUpdates:', err.message);
      if (err.code === 409) console.error('Another copy of the bot is running with this token (or a webhook is set).');
      await new Promise((r) => setTimeout(r, err.retryAfter ? err.retryAfter * 1000 : 3000));
    }
  }
}

// ---- reminders ----

const timer = setInterval(() => {
  bot.checkReminders().catch((err) => console.error('Reminders:', err.message));
}, 15_000);
bot.checkReminders().catch((err) => console.error('Reminders:', err.message));

// ---- shutdown ----

async function shutdown(signal) {
  console.log(`${signal}: saving and exiting`);
  stopped = true;
  clearInterval(timer);
  server.close();
  await queue;
  await store.flush();
  process.exit(0);
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
