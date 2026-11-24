/* Vite prefixes build-specific constants for this source. No runtime API caching. */
const CACHE_PREFIX = 'beads-shell-';
const CACHE_NAME = CACHE_PREFIX + BUILD_ID;
const SHELL = '/index.html';
const assets = new Set(STATIC_PATHS);

function goodResponse(path, response) {
  const mime = (response.headers.get('content-type') || '').toLowerCase();
  if (!response.ok || response.redirected || response.url !== new URL(path, self.location.origin).href) return false;
  if (path === SHELL) return mime.startsWith('text/html');
  if (/\b(?:private|no-store)\b/i.test(response.headers.get('cache-control') || '')) return false;
  if (path.endsWith('.js')) return /^(?:text|application)\/javascript\b/.test(mime);
  if (path.endsWith('.css')) return mime.startsWith('text/css');
  if (path.endsWith('.png')) return mime.startsWith('image/png');
  return /^(?:application\/manifest\+json|application\/json|application\/octet-stream)\b/.test(mime);
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.all([SHELL, ...assets].map(async path => {
      const response = await fetch(path, { credentials: 'omit', cache: 'reload', redirect: 'error' });
      if (!goodResponse(path, response)) throw new Error('Invalid offline build asset: ' + path);
      await cache.put(path, response);
    }));
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.search) return;
  if (request.mode === 'navigate' && (url.pathname === '/' || url.pathname === SHELL)) {
    event.respondWith(fetch(request).catch(async () => {
      const cached = await (await caches.open(CACHE_NAME)).match(SHELL);
      return cached ?? new Response('当前离线，尚无可用的离线页面。', { status: 503, headers: {'Content-Type': 'text/plain;charset=utf-8'} });
    }));
  } else if (assets.has(url.pathname)) {
    event.respondWith((async () => {
      const cached = await (await caches.open(CACHE_NAME)).match(url.pathname);
      return cached ?? fetch(request);
    })());
  }
});
