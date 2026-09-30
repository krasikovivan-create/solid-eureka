// Offline support for the boxing app at the site root.
// Pages are network-first (updates show up right away), other files cache-first.
const CACHE = 'boxing-combo-v2';
const ASSETS = ['./', './index.html', './manifest.webmanifest', './icons/icon-180.png', './icons/icon-192.png', './icons/icon-512.png'];
const ROOT = new URL('./', self.location).pathname;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('boxing-combo-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Only handle this app's own files, not other apps living in subfolders (e.g. ai-academy/).
function isOwn(url) {
  if (url.origin !== location.origin || !url.pathname.startsWith(ROOT)) return false;
  const rest = url.pathname.slice(ROOT.length);
  return !rest.includes('/') || rest.startsWith('icons/');
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || !isOwn(url)) return;
  const put = (res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  };
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).then(put).catch(() => caches.match(e.request).then((r) => r || caches.match('./index.html'))));
    return;
  }
  e.respondWith(caches.match(e.request).then((cached) => cached || fetch(e.request).then(put)));
});
