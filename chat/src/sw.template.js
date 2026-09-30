// Service worker for «Связь».
// The version and precache list below are filled in by vite.config.ts at build time.
const VERSION = '__VERSION__';
const CACHE = 'svyaz-' + VERSION;
const PRECACHE = __PRECACHE__;
const INDEX = new URL('./index.html', self.location).href;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('svyaz-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // App shell: every navigation gets the cached index.html, so the app opens offline.
  // The cache is versioned per build, so a new deploy brings a new shell.
  if (request.mode === 'navigate') {
    event.respondWith(
      caches.match(INDEX).then((cached) => cached || fetch(request))
        .catch(() => new Response('Нет подключения', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }))
    );
    return;
  }

  // Static files: cache first, then network (and remember what came from the network).
  event.respondWith(
    caches.match(request, { ignoreSearch: true }).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok && response.type === 'basic') {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    })
  );
});
