// Keeps all bot data in memory and saves it as one JSON document.
//
// Two backends:
//  - file   — DATA_DIR/db.json (default; fine on your own computer or a server with a disk);
//  - Upstash Redis over its REST API — used when UPSTASH_REDIS_REST_URL and
//    UPSTASH_REDIS_REST_TOKEN are set. Needed on hosts without a persistent disk
//    (Render's free plan wipes local files every time the service restarts or sleeps).
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

function fileBackend(dir) {
  const file = join(dir, 'db.json');
  return {
    name: `file ${file}`,
    async load() {
      return existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : null;
    },
    async save(json) {
      mkdirSync(dir, { recursive: true });
      writeFileSync(`${file}.tmp`, json);
      renameSync(`${file}.tmp`, file);
    },
  };
}

function upstashBackend(url, token, key) {
  async function command(args) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify(args),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(`Upstash: ${data.error || res.status}`);
    return data.result;
  }
  return {
    name: `Upstash Redis key "${key}"`,
    async load() {
      const raw = await command(['GET', key]);
      return raw ? JSON.parse(raw) : null;
    },
    async save(json) {
      await command(['SET', key, json]);
    },
  };
}

export function backendFromEnv(env = process.env) {
  if (env.UPSTASH_REDIS_REST_URL && env.UPSTASH_REDIS_REST_TOKEN) {
    return upstashBackend(env.UPSTASH_REDIS_REST_URL, env.UPSTASH_REDIS_REST_TOKEN, env.UPSTASH_KEY || 'telegram-bot:db');
  }
  return fileBackend(env.DATA_DIR || './data');
}

export function memoryBackend(initial = null) {
  let saved = initial && JSON.stringify(initial);
  return {
    name: 'memory',
    async load() { return saved ? JSON.parse(saved) : null; },
    async save(json) { saved = json; },
    get saved() { return saved && JSON.parse(saved); },
  };
}

/**
 * db = { users: { [chatId]: User }, nextId }
 * User = { id, name, username, joinedAt, notes: [{ id, text, at }],
 *          reminders: [{ id, text, at, createdAt }], state: null | { type, ... } }
 */
export async function createStore(backend, { saveDelayMs = 300 } = {}) {
  const db = (await backend.load()) || {};
  db.users ||= {};
  db.nextId ||= 1;

  let timer = null;
  let saving = Promise.resolve();

  function flush() {
    clearTimeout(timer);
    timer = null;
    const json = JSON.stringify(db);
    saving = saving
      .then(() => backend.save(json))
      .catch((err) => console.error('Failed to save data:', err.message));
    return saving;
  }

  return {
    backendName: backend.name,
    db,
    newId() {
      return db.nextId++;
    },
    user(chat, from = {}) {
      const id = String(chat.id ?? chat);
      let u = db.users[id];
      if (!u) {
        u = db.users[id] = { id, joinedAt: Date.now(), notes: [], reminders: [], state: null };
      }
      if (from.first_name) u.name = [from.first_name, from.last_name].filter(Boolean).join(' ');
      if (from.username) u.username = from.username;
      return u;
    },
    users() {
      return Object.values(db.users);
    },
    changed() {
      if (!timer) timer = setTimeout(flush, saveDelayMs);
    },
    flush,
  };
}
