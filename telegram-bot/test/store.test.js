import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { backendFromEnv, createStore } from '../src/store.js';

test('file backend: data survives a restart', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bot-'));
  try {
    const a = await createStore(backendFromEnv({ DATA_DIR: dir }));
    a.user(1).notes.push({ id: a.newId(), text: 'привет' });
    a.changed();
    await a.flush();
    const b = await createStore(backendFromEnv({ DATA_DIR: dir }));
    assert.equal(b.user(1).notes[0].text, 'привет');
    assert.equal(b.newId(), 2);
  } finally {
    rmSync(dir, { recursive: true });
  }
});

test('Upstash backend speaks the REST protocol', async () => {
  const kv = new Map();
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      if (req.headers.authorization !== 'Bearer tok') return res.writeHead(401).end('{"error":"unauthorized"}');
      const [cmd, key, value] = JSON.parse(body);
      if (cmd === 'SET') kv.set(key, value);
      res.end(JSON.stringify({ result: cmd === 'GET' ? kv.get(key) ?? null : 'OK' }));
    });
  });
  await new Promise((r) => server.listen(0, r));
  const env = { UPSTASH_REDIS_REST_URL: `http://127.0.0.1:${server.address().port}`, UPSTASH_REDIS_REST_TOKEN: 'tok' };
  try {
    const a = await createStore(backendFromEnv(env));
    assert.match(a.backendName, /Upstash/);
    a.user(5).notes.push({ id: a.newId(), text: 'в облаке' });
    await a.flush();
    assert.ok(kv.has('telegram-bot:db'));
    const b = await createStore(backendFromEnv(env));
    assert.equal(b.user(5).notes[0].text, 'в облаке');
  } finally {
    server.close();
  }
});
