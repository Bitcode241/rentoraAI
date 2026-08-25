/* Rentora service worker — receives booking notifications even when the app
   is closed, and opens the admin when the notification is tapped. */

self.addEventListener('push', function(event){
  let data = {title: 'Rentora', body: 'Nova rezervacija', url: '/admin'};
  try { if (event.data) data = Object.assign(data, event.data.json()); }
  catch(e){ if (event.data) data.body = event.data.text(); }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      vibrate: [200, 100, 200],
      tag: 'rentora-booking',
      renotify: true,
      requireInteraction: true,      // stays on screen until tapped
      data: { url: data.url || '/admin' }
    })
  );
});

self.addEventListener('notificationclick', function(event){
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/admin';
  event.waitUntil(
    clients.matchAll({type: 'window', includeUncontrolled: true}).then(function(list){
      // focus an already-open tab if there is one
      for (const c of list){
        if (c.url.indexOf(url) > -1 && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
