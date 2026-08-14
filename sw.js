// Newport Navigator service worker — offline app shell
const CACHE = 'newport-nav-v85';
const ASSETS = [
  '.', 'index.html', 'manifest.webmanifest', 'data/places.json',
  'family-sync.js', 'data/irish-directions.json',
  'data/greenway.json',
  'icons/icon.svg', 'icons/icon-maskable.svg'
];
self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(ASSETS.map(url => cache.add(url).catch(() => {})));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('message', e => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  const isJson = url.pathname.endsWith('.json');
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(e.request);
    if (isJson) {
      try {
        const resp = await fetch(e.request);
        if (resp && resp.ok) cache.put(e.request, resp.clone()).catch(() => {});
        return resp;
      } catch (err) {
        if (cached) return cached;
        throw err;
      }
    }
    const fetched = fetch(e.request).then(resp => {
      if (resp && resp.ok) cache.put(e.request, resp.clone()).catch(() => {});
      return resp;
    }).catch(() => cached || cache.match('index.html'));
    return cached || fetched;
  })());
});
