// Service worker mínimo de Anguera TV: permite instalar la app y abrirla sin conexión.
// Solo toca la navegación de la propia web; vídeos, Drive y FCF pasan sin tocar.
const CACHE = 'atv-v1';
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(['./', 'icons/escudo.png'])).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.mode !== 'navigate' || new URL(r.url).origin !== location.origin) return;
  e.respondWith(fetch(r).then(res => { const copy = res.clone(); caches.open(CACHE).then(c => c.put('./', copy)); return res; }).catch(() => caches.match('./')));
});
