/* Service worker — deliberately almost empty.
 *
 * It exists for two reasons and no others:
 *
 *   1. iOS will not let a web app be added to the Home Screen as a real app,
 *      and will not deliver Web Push to it, without one registered.
 *   2. It is where push notifications will arrive when notify.py lands.
 *
 * It caches nothing. iOS evicts PWA storage after roughly a week of disuse,
 * offers no Background Sync and no Periodic Background Sync, so an offline
 * cache here would be a stale schedule that lies to you in a car park — which
 * is worse than a spinner. The server is the source of truth; the phone
 * renders it.
 */

self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

// Push arrives here once notify.py is built. Harmless until then.
self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  event.waitUntil(self.registration.showNotification(
    data.title || 'Kid Logistics',
    {
      body: data.body || '',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data: { url: data.url || '/' },
      tag: data.tag || undefined
    }
  ));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(function (list) {
        for (var i = 0; i < list.length; i++) {
          if ('focus' in list[i]) { list[i].navigate(url); return list[i].focus(); }
        }
        return self.clients.openWindow(url);
      })
  );
});
