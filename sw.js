// Minimal service worker so Chrome offers "Install" for RayCoin.
// Network-only: never caches, so the dashboard always shows live data.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => e.respondWith(fetch(e.request)));
