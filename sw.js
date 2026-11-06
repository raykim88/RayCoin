// Minimal service worker so Chrome offers "Install" for RayCoin.
// Network-only and cache-bypassing: the app always loads the latest page and live data.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const sameOrigin = new URL(e.request.url).origin === self.location.origin;
  e.respondWith(sameOrigin ? fetch(e.request, { cache: "no-store" }) : fetch(e.request));
});
