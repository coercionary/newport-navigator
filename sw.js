// Newport Navigator service worker — offline app shell
const CACHE = 'newport-nav-v121';
const REQUIRED = ['index.html', 'family-sync.js', 'data/places.json'];
const OPTIONAL = [
  '.', 'manifest.webmanifest',
  'data/irish-directions.json', 'data/greenway.json',
  'icons/icon.svg', 'icons/icon-maskable.svg',
  'icons/icon-192.png', 'icons/icon-512.png',
  'icons/icon-maskable-192.png', 'icons/icon-maskable-512.png',
  'icons/apple-touch-icon.png'
];

function bust(url) {
  return url + (url.includes('?') ? '&' : '?') + 'sw=' + encodeURIComponent(CACHE);
}

async function precache() {
  const cache = await caches.open(CACHE);
  for (const url of REQUIRED) {
    const resp = await fetch(bust(url), {cache: 'reload'});
    if (!resp.ok) throw new Error('precache failed: ' + url);
    await cache.put(url, resp.clone());
    if (url === 'index.html') {
      await cache.put('.', resp.clone());
      await cache.put('/', resp.clone());
    }
  }
  await Promise.all(OPTIONAL.map(async url => {
    try {
      const resp = await fetch(bust(url), {cache: 'reload'});
      if (resp.ok) await cache.put(url, resp.clone());
    } catch (err) {}
  }));
}

self.addEventListener('install', e => {
  e.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE && k.startsWith('newport-nav-')).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('message', e => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});

async function matchCached(cache, request) {
  const url = new URL(request.url);
  const opts = {ignoreSearch: true, ignoreVary: true};
  const path = url.pathname.replace(/^\//, '');
  return (await cache.match(request, opts))
    || (await cache.match(url.pathname, opts))
    || (path ? await cache.match(path, opts) : null)
    || ((url.pathname === '/' || url.pathname === '')
      ? ((await cache.match('index.html', opts)) || (await cache.match('.', opts)))
      : null);
}

function wantsNetwork(request) {
  return request.cache === 'reload' || request.cache === 'no-store';
}

function remember(cache, request, resp) {
  if (!resp || !resp.ok) return;
  const url = new URL(request.url);
  const path = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\//, '');
  cache.put(request, resp.clone()).catch(() => {});
  if (path) cache.put(path, resp.clone()).catch(() => {});
  if (url.pathname === '/' || path === 'index.html') {
    cache.put('index.html', resp.clone()).catch(() => {});
    cache.put('.', resp.clone()).catch(() => {});
    cache.put('/', resp.clone()).catch(() => {});
  }
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await matchCached(cache, e.request);
    const fromNet = fetch(e.request).then(resp => {
      remember(cache, e.request, resp);
      return resp;
    }).catch(() => null);

    if (wantsNetwork(e.request)) {
      const resp = await fromNet;
      if (resp && resp.ok) return resp;
      if (cached) return cached;
    } else if (cached) {
      fromNet.catch(() => {});
      return cached;
    } else {
      const resp = await fromNet;
      if (resp) return resp;
    }

    if (e.request.mode === 'navigate') {
      const page = (await cache.match('index.html')) || (await cache.match('.'));
      if (page) return page;
    }
    return new Response('Offline', {status: 503, statusText: 'Offline'});
  })());
});
