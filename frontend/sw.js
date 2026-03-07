// Service Worker — deregistriert sich selbst
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil(self.registration.unregister());
});
