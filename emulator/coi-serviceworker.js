/**
 * Minimal Cross-Origin Isolation service worker.
 * Intercepts all fetches and adds COOP + COEP headers so SharedArrayBuffer
 * is available (required for Pyodide's time.sleep in Web Workers).
 * On first load the page reloads once after the SW activates.
 */
self.addEventListener('install',  () => self.skipWaiting());
self.addEventListener('activate', e  => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Don't intercept opaque requests that can't have headers modified
  if (req.cache === 'only-if-cached' && req.mode !== 'same-origin') return;

  event.respondWith(
    fetch(req).then(res => {
      if (!res || res.status === 0 || res.type === 'opaque') return res;
      const headers = new Headers(res.headers);
      headers.set('Cross-Origin-Opener-Policy',  'same-origin');
      headers.set('Cross-Origin-Embedder-Policy', 'credentialless');
      return new Response(res.body, {
        status: res.status, statusText: res.statusText, headers
      });
    }).catch(() => fetch(req))
  );
});
