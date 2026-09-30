// Relay server for «Связь».
//
// What it does:
//  - accounts by phone number (no SMS: a device proves it owns a number with a secret
//    token it generated when it first registered that number);
//  - finds which phone numbers use the app (adding friends, importing the phone book);
//  - store-and-forward for messages and receipts: delivered right away to online
//    devices, queued for offline ones and handed over when they connect;
//  - presence ("в сети" / "был в сети") and "печатает…";
//  - photo/video/voice upload for messages (kept until 14 days old);
//  - WebRTC call signaling (invite/accept/decline/end + SDP/ICE relay).
//
// The server doesn't keep chat history: once a message is delivered it is gone from here;
// history lives on the devices. State (accounts, undelivered queue) is saved to DATA_DIR.
//
// Environment:
//   PORT              port to listen on (Render sets it)
//   DATA_DIR          where state.json and media/ live (default ./data)
//   ALLOWED_ORIGINS   comma-separated origins allowed to connect, or * (default *)
//   TURN_URLS         optional comma-separated TURN urls (turn:host:3478,turns:host:443)
//   TURN_USERNAME, TURN_CREDENTIAL   credentials for TURN_URLS
import http from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream, createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { WebSocketServer } from 'ws';

const PORT = Number(process.env.PORT) || 8080;
const DATA_DIR = process.env.DATA_DIR || './data';
const MEDIA_DIR = join(DATA_DIR, 'media');
const STATE_FILE = join(DATA_DIR, 'state.json');
const ORIGINS = (process.env.ALLOWED_ORIGINS || '*').split(',').map((s) => s.trim()).filter(Boolean);
const MAX_MEDIA = 25 * 1024 * 1024;
const MEDIA_TTL = 14 * 24 * 3600 * 1000;
const MAX_QUEUE = 2000;

const ICE_SERVERS = [{ urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] }];
if (process.env.TURN_URLS) {
  ICE_SERVERS.push({
    urls: process.env.TURN_URLS.split(',').map((s) => s.trim()),
    username: process.env.TURN_USERNAME || undefined,
    credential: process.env.TURN_CREDENTIAL || undefined,
  });
}

mkdirSync(MEDIA_DIR, { recursive: true });

// ---- state -------------------------------------------------------------------------------

/** @type {Map<string, {phone:string,name:string,about:string,colors?:string[],tokenHash:string,lastSeen:number,createdAt:number}>} */
const users = new Map();
/** Undelivered envelopes per phone. @type {Map<string, object[]>} */
const queues = new Map();
/** Open connections per phone. @type {Map<string, Set<import('ws').WebSocket>>} */
const sockets = new Map();
/** phone → phones that want its presence. @type {Map<string, Set<string>>} */
const watchers = new Map();

function load() {
  try {
    const data = JSON.parse(readFileSync(STATE_FILE, 'utf8'));
    for (const u of data.users ?? []) users.set(u.phone, u);
    for (const [phone, list] of Object.entries(data.queues ?? {})) queues.set(phone, list);
    log(`loaded ${users.size} accounts`);
  } catch {
    log('starting with empty state');
  }
}

let saveTimer = null;
function save() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    const data = { users: [...users.values()], queues: Object.fromEntries(queues) };
    try {
      writeFileSync(STATE_FILE + '.tmp', JSON.stringify(data));
      renameSync(STATE_FILE + '.tmp', STATE_FILE);
    } catch (e) {
      log('save failed: ' + e.message);
    }
  }, 500);
}

const hash = (s) => createHash('sha256').update(String(s)).digest('hex');
const log = (msg) => console.log(new Date().toISOString(), msg);
const isOnline = (phone) => (sockets.get(phone)?.size ?? 0) > 0;

/** "+7 (999) 123-45-67" → "79991234567"; null if invalid. */
function normPhone(p) {
  if (typeof p !== 'string' && typeof p !== 'number') return null;
  let d = String(p).replace(/\D/g, '');
  if (d.length === 11 && d[0] === '8') d = '7' + d.slice(1);
  if (d.length === 10 && d[0] === '9') d = '7' + d;
  return d.length >= 10 && d.length <= 15 ? d : null;
}

const str = (v, max) => (typeof v === 'string' ? v.slice(0, max) : '');
const phones = (list, max = 50) => (Array.isArray(list) ? [...new Set(list.slice(0, max).map(normPhone).filter(Boolean))] : []);

function publicUser(u) {
  return { phone: u.phone, name: u.name, about: u.about, colors: u.colors, online: isOnline(u.phone), lastSeen: u.lastSeen };
}

function authorized(phone, token) {
  const u = users.get(phone);
  return !!u && typeof token === 'string' && u.tokenHash === hash(token);
}

// ---- delivery ---------------------------------------------------------------------------

function sendTo(ws, obj) {
  if (ws.readyState === 1) ws.send(JSON.stringify(obj));
}

/** Live-only: to every open connection of `phone`; returns true if anyone got it. */
function push(phone, obj) {
  const set = sockets.get(phone);
  if (!set?.size) return false;
  set.forEach((ws) => sendTo(ws, obj));
  return true;
}

/** Store-and-forward: deliver now, or keep until `phone` connects. */
function deliver(phone, obj) {
  if (push(phone, obj)) return;
  const q = queues.get(phone) ?? [];
  q.push(obj);
  if (q.length > MAX_QUEUE) q.splice(0, q.length - MAX_QUEUE);
  queues.set(phone, q);
  save();
}

function broadcastPresence(phone) {
  const u = users.get(phone);
  if (!u) return;
  const event = { type: 'presence', phone, online: isOnline(phone), lastSeen: u.lastSeen };
  watchers.get(phone)?.forEach((w) => push(w, event));
}

// ---- WebSocket protocol ---------------------------------------------------------------------

function onHello(ws, m) {
  const phone = normPhone(m.phone);
  if (!phone || typeof m.token !== 'string' || m.token.length < 16) return sendTo(ws, { type: 'error', code: 'bad-hello' });
  const existing = users.get(phone);
  if (existing && existing.tokenHash !== hash(m.token)) {
    sendTo(ws, { type: 'error', code: 'phone-taken' });
    return ws.close(4001, 'phone-taken');
  }
  const now = Date.now();
  const user = existing ?? { phone, tokenHash: hash(m.token), createdAt: now, lastSeen: now, name: '', about: '' };
  user.name = str(m.name, 60).trim() || user.name || formatPhone(phone);
  user.about = str(m.about, 140);
  if (Array.isArray(m.colors) && m.colors.length === 2) user.colors = m.colors.map((c) => str(c, 20));
  user.lastSeen = now;
  users.set(phone, user);
  save();

  ws.phone = phone;
  const set = sockets.get(phone) ?? new Set();
  const wasOnline = set.size > 0;
  set.add(ws);
  sockets.set(phone, set);
  sendTo(ws, { type: 'welcome', me: publicUser(user), iceServers: ICE_SERVERS, time: now });

  // Everything that arrived while this number was offline.
  const q = queues.get(phone);
  if (q?.length) {
    queues.delete(phone);
    q.forEach((obj) => sendTo(ws, obj));
    save();
  }
  if (!wasOnline) broadcastPresence(phone);
  log(`hello ${mask(phone)} (${set.size} conn)`);
}

function onMessage(ws, m) {
  const from = ws.phone;
  switch (m.type) {
    case 'ping':
      return sendTo(ws, { type: 'pong' });

    case 'profile': {
      const u = users.get(from);
      if (!u) return;
      if (typeof m.name === 'string' && m.name.trim()) u.name = str(m.name, 60).trim();
      if (typeof m.about === 'string') u.about = str(m.about, 140);
      save();
      return;
    }

    case 'lookup': {
      const found = phones(m.phones, 2000)
        .map((p) => users.get(p))
        .filter(Boolean)
        .map(publicUser);
      return sendTo(ws, { type: 'lookup-result', reqId: m.reqId, users: found });
    }

    case 'watch': {
      for (const p of phones(m.phones, 2000)) {
        const set = watchers.get(p) ?? new Set();
        set.add(from);
        watchers.set(p, set);
        const u = users.get(p);
        if (u) sendTo(ws, { type: 'presence', phone: p, online: isOnline(p), lastSeen: u.lastSeen, name: u.name, about: u.about, colors: u.colors });
      }
      return;
    }

    case 'msg': {
      const to = phones(m.to, 100).filter((p) => p !== from);
      const id = str(m.id, 64);
      if (!id || !to.length) return;
      const chat = m.chat && typeof m.chat === 'object' ? m.chat : { kind: 'direct' };
      const members = chat.kind === 'group' ? phones(chat.members, 100) : undefined;
      const envelope = {
        type: 'msg',
        id,
        from,
        fromName: users.get(from)?.name ?? '',
        text: str(m.text, 10000),
        createdAt: Number(m.createdAt) || Date.now(),
        sentAt: Date.now(),
        media: m.media && typeof m.media === 'object' ? sanitizeMedia(m.media) : undefined,
        chat:
          chat.kind === 'group'
            ? {
                kind: 'group',
                id: str(chat.id, 64),
                title: str(chat.title, 80),
                members: [...new Set([from, ...members])].map((p) => ({ phone: p, name: users.get(p)?.name ?? '' })),
              }
            : { kind: 'direct' },
      };
      const unknown = [];
      for (const p of to) {
        if (users.has(p)) deliver(p, envelope);
        else unknown.push(p);
      }
      return sendTo(ws, { type: 'ack', id, at: envelope.sentAt, unknown });
    }

    case 'receipt': {
      const to = normPhone(m.to);
      const ids = Array.isArray(m.ids) ? m.ids.slice(0, 500).map((i) => str(i, 64)).filter(Boolean) : [];
      if (!to || !ids.length || (m.kind !== 'delivered' && m.kind !== 'read')) return;
      return deliver(to, { type: 'receipt', kind: m.kind, ids, from, at: Date.now() });
    }

    case 'typing': {
      for (const p of phones(m.to, 100)) push(p, { type: 'typing', from, chatId: str(m.chatId, 64) || null, typing: !!m.typing });
      return;
    }

    case 'call': {
      const action = str(m.action, 20);
      const callId = str(m.callId, 64);
      if (!callId || !action) return;
      const event = {
        type: 'call',
        action,
        callId,
        from,
        fromName: users.get(from)?.name ?? '',
        kind: m.kind === 'video' ? 'video' : 'audio',
        cameraOn: !!m.cameraOn,
        muted: !!m.muted,
      };
      if (m.chat && typeof m.chat === 'object') {
        event.chat = { kind: m.chat.kind === 'group' ? 'group' : 'direct', id: str(m.chat.id, 64), title: str(m.chat.title, 80), members: phones(m.chat.members, 20) };
      }
      for (const p of phones(m.to, 20)) {
        if (p === from) continue;
        const got = push(p, event);
        // Tell the caller right away that this person can't be reached.
        if (!got && action === 'invite') sendTo(ws, { type: 'call', action: 'unavailable', callId, from: p, registered: users.has(p) });
      }
      return;
    }

    case 'rtc': {
      const to = normPhone(m.to);
      if (!to || typeof m.data !== 'object') return;
      return void push(to, { type: 'rtc', callId: str(m.callId, 64), from, data: m.data });
    }
  }
}

function sanitizeMedia(media) {
  const mime = str(media.mime, 80);
  if (!/^(image|video|audio)\//.test(mime)) return undefined;
  const waveform = Array.isArray(media.waveform) ? media.waveform.slice(0, 64).map((v) => Math.max(0, Math.min(1, Number(v) || 0))) : undefined;
  return {
    id: str(media.id, 64),
    kind: mime.startsWith('image/') ? 'image' : mime.startsWith('audio/') ? 'audio' : 'video',
    round: media.round === true || undefined,
    waveform,
    mime,
    name: str(media.name, 120),
    size: Number(media.size) || 0,
    width: Number(media.width) || undefined,
    height: Number(media.height) || undefined,
    duration: Number(media.duration) || undefined,
  };
}

const formatPhone = (p) => '+' + p;
const mask = (p) => p.slice(0, 4) + '…' + p.slice(-2);

// ---- HTTP: health, media upload/download ------------------------------------------------------

function allowOrigin(req, res) {
  const origin = req.headers.origin;
  if (!origin) return true;
  const ok = ORIGINS.includes('*') || ORIGINS.includes(origin);
  if (ok) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Phone, X-Token');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Max-Age', '86400');
  }
  return ok;
}

const validMediaId = (id) => /^[\w-]{8,64}$/.test(id);

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (!allowOrigin(req, res)) {
    res.writeHead(403).end('origin not allowed');
    return;
  }
  if (req.method === 'OPTIONS') return void res.writeHead(204).end();
  if (url.pathname === '/health') {
    return void res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true, users: users.size, online: sockets.size }));
  }
  if (url.pathname === '/') return void res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' }).end('Связь — сервер работает');

  const media = /^\/media\/([^/]+)$/.exec(url.pathname);
  if (media) {
    const id = media[1];
    const phone = normPhone(req.headers['x-phone']);
    if (!validMediaId(id)) return void res.writeHead(400).end('bad id');
    if (!phone || !authorized(phone, req.headers['x-token'])) return void res.writeHead(401).end('unauthorized');
    const file = join(MEDIA_DIR, id);

    if (req.method === 'POST') {
      const mime = String(req.headers['content-type'] || '');
      if (!/^(image|video|audio)\//.test(mime)) return void res.writeHead(415).end('only photos, videos and voice');
      if (Number(req.headers['content-length'] || 0) > MAX_MEDIA) return void res.writeHead(413).end('too large');
      let size = 0;
      const tmp = file + '.' + randomUUID() + '.part';
      const out = createWriteStream(tmp);
      req.on('data', (chunk) => {
        size += chunk.length;
        if (size > MAX_MEDIA) {
          req.destroy();
          out.destroy();
          safeUnlink(tmp);
          if (!res.headersSent) res.writeHead(413).end('too large');
        }
      });
      req.pipe(out);
      out.on('finish', () => {
        if (size > MAX_MEDIA) return;
        renameSync(tmp, file);
        writeFileSync(file + '.json', JSON.stringify({ mime, size, owner: phone, createdAt: Date.now() }));
        res.writeHead(201, { 'Content-Type': 'application/json' }).end(JSON.stringify({ id, size }));
      });
      out.on('error', () => {
        safeUnlink(tmp);
        if (!res.headersSent) res.writeHead(500).end('write failed');
      });
      return;
    }

    if (req.method === 'GET') {
      if (!existsSync(file)) return void res.writeHead(404).end('not found');
      let meta = { mime: 'application/octet-stream' };
      try {
        meta = JSON.parse(readFileSync(file + '.json', 'utf8'));
      } catch {
        /* no meta */
      }
      res.writeHead(200, { 'Content-Type': meta.mime, 'Content-Length': statSync(file).size, 'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff' });
      createReadStream(file).pipe(res);
      return;
    }
  }
  res.writeHead(404).end('not found');
});

function safeUnlink(f) {
  try {
    unlinkSync(f);
  } catch {
    /* already gone */
  }
}

// Old media is removed so the disk doesn't fill up.
setInterval(() => {
  const now = Date.now();
  for (const name of readdirSync(MEDIA_DIR)) {
    const f = join(MEDIA_DIR, name);
    try {
      if (now - statSync(f).mtimeMs > MEDIA_TTL) unlinkSync(f);
    } catch {
      /* ignore */
    }
  }
}, 3600 * 1000).unref();

// ---- WebSocket server ------------------------------------------------------------------------

const wss = new WebSocketServer({
  server,
  maxPayload: 512 * 1024,
  verifyClient: ({ origin }) => !origin || ORIGINS.includes('*') || ORIGINS.includes(origin),
});

wss.on('connection', (ws) => {
  ws.isAlive = true;
  ws.on('pong', () => (ws.isAlive = true));
  ws.on('message', (raw) => {
    let m;
    try {
      m = JSON.parse(raw.toString());
    } catch {
      return;
    }
    if (!m || typeof m !== 'object') return;
    if (m.type === 'hello') return onHello(ws, m);
    if (!ws.phone) return sendTo(ws, { type: 'error', code: 'not-registered' });
    try {
      onMessage(ws, m);
    } catch (e) {
      log('error handling ' + m.type + ': ' + e.message);
    }
  });
  ws.on('close', () => {
    const phone = ws.phone;
    if (!phone) return;
    const set = sockets.get(phone);
    set?.delete(ws);
    if (!set?.size) {
      sockets.delete(phone);
      const u = users.get(phone);
      if (u) {
        u.lastSeen = Date.now();
        save();
      }
      broadcastPresence(phone);
    }
  });
});

// Drop dead connections (phones that lost the network without closing the socket).
setInterval(() => {
  wss.clients.forEach((ws) => {
    if (!ws.isAlive) return ws.terminate();
    ws.isAlive = false;
    ws.ping();
  });
}, 30_000).unref();

load();
server.listen(PORT, () => log(`Связь server on :${PORT}, origins: ${ORIGINS.join(', ')}`));
