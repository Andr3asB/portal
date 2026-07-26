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
