// Minimal Telegram Bot API client on top of built-in fetch (Node 20+), no dependencies.
// Docs: https://core.telegram.org/bots/api

export class TelegramError extends Error {
  constructor(method, data) {
    super(`${method}: ${data.description || 'unknown error'}`);
    this.code = data.error_code;
    this.retryAfter = data.parameters?.retry_after;
  }
}

export function createApi(token, { baseUrl = 'https://api.telegram.org' } = {}) {
  const root = `${baseUrl}/bot${token}`;

  async function call(method, params = {}, { signal } = {}) {
    const res = await fetch(`${root}/${method}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(params),
      signal,
    });
    const data = await res.json().catch(() => ({ ok: false, description: `HTTP ${res.status}` }));
    if (!data.ok) throw new TelegramError(method, data);
    return data.result;
  }

  return { call };
}
