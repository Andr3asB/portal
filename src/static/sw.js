// v2 wegen Wunsch #140, Stufe 4: Der Namenswechsel raeumt beim ersten Start
// nach der Auslieferung einmal alles weg, was noch unter Token-Adressen im
// Cache lag.
const CACHE_NAME = 'portal-cache-v2';

// Wunsch #140, Stufe 4: Merker, WESSEN Seiten im Cache liegen.
//
// Bis Stufe 3 trennte der Token die Cache-Schluessel von selbst - die Seiten
// zweier Nutzer lagen unter verschiedenen Adressen. Token-frei ist
// `/a/einkauf/` fuer alle dieselbe Adresse. Auf einem geteilten Geraet
// (Familien-iPad, Kioskbildschirm) wuerde der naechste Nutzer sonst offline
// die Einkaufsliste des vorigen sehen. Deshalb: Beim Nutzerwechsel den
// Seiten-Cache komplett wegwerfen.
//
// Der Merker ist selbst ein (leerer) Cache, weil ein Service Worker jederzeit
// beendet und neu gestartet wird - eine Variable im Modul waere nach dem
// naechsten Start weg, `caches.keys()` ueberlebt.
const NUTZER_PRAEFIX = 'portal-nutzer-';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME && !k.startsWith(NUTZER_PRAEFIX))
            .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function nutzerPruefen(id) {
  const schluessel = await caches.keys();
  const alt = schluessel.find(k => k.startsWith(NUTZER_PRAEFIX));
  const neu = NUTZER_PRAEFIX + id;
  if (alt === neu) return;
  if (alt) {
    await caches.delete(alt);
    await caches.delete(CACHE_NAME);   // fremde Seiten wegwerfen
  }
  await caches.open(neu);
}

// Jede Seite meldet nach dem Laden, wer sie sieht (siehe base.html).
self.addEventListener('message', event => {
  const d = event.data || {};
  if (d.typ === 'nutzer' && d.id) {
    event.waitUntil(nutzerPruefen(String(d.id)));
  }
});

// Network-first mit Cache-Fallback fuer eigene GET-Seiten. Schreibende
// Requests (POST etc.) werden nie abgefangen, laufen immer direkt durch.
// Ob eine App offline sinnvoll nutzbar ist, entscheidet das offline_faehig-
// Flag auf der Startseite (graue/gesperrte Kacheln), nicht dieser Handler -
// der cached grundsaetzlich jede besuchte eigene Seite, unabhaengig vom
// Flag. Rein technisch harmlos: zeigt hoechstens einen alten Stand.
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(req).then(resp => {
      if (resp.ok) {
        const kopie = resp.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(req, kopie));
      }
      return resp;
    }).catch(() =>
      caches.match(req).then(cached => cached || new Response(
        '<!doctype html><meta charset="utf-8" name="viewport" content="width=device-width">' +
        '<body style="font-family:sans-serif;text-align:center;padding:60px 20px;color:#666">' +
        '📡 Keine Verbindung<br><small>Diese Seite wurde noch nie geladen, solange Empfang da war.</small></body>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
      ))
    )
  );
});

self.addEventListener('push', event => {
  if (!event.data) return;
  let d = {};
  try { d = event.data.json(); } catch(e) { d = { title: 'Portal', body: event.data.text() }; }
  event.waitUntil(
    self.registration.showNotification(d.title || 'Portal', {
      body:  d.body  || '',
      icon:  '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data:  { url: d.url || '/' },
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data || {}).url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(wins => {
      for (const w of wins) {
        if (w.url === url && 'focus' in w) return w.focus();
      }
      return clients.openWindow(url);
    })
  );
});
