const VERSION = 'v2';
const SHELL = ['mobile.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open('anchor-shell-' + VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== 'anchor-shell-' + VERSION).map((k) => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return;
  // 外壳资源：缓存优先；其余（音频等）：直连
  if (SHELL.some((p) => url.pathname === '/' + p || url.pathname === p)) {
    e.respondWith(caches.open('anchor-shell-' + VERSION).then((c) =>
      c.match(e.request).then((hit) => hit || fetch(e.request).then((resp) => {
        c.put(e.request, resp.clone());
        return resp;
      }))));
  }
});
