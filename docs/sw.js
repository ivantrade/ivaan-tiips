// Service worker mínimo — só o necessário pra qualificar como app instalável.
// Não guarda cache agressivo de propósito: o painel muda todo dia, então
// preferimos sempre buscar a versão mais nova em vez de mostrar uma velha.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
