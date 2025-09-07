// File: static/sw.js
const CACHE_NAME = 'poddar-ent-cache-v3'; // Bumped version to ensure update
const urlsToCache = [
  '/',
  '/login',
  '/static/style.css',
  '/static/img/logo.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css'
];

// Install event: opens a cache and adds the assets to it
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache and caching app shell');
        return cache.addAll(urlsToCache);
      })
  );
});

// Activate event: remove old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            console.log('Service Worker: clearing old cache');
            return caches.delete(cache);
          }
        })
      );
    })
  );
});

// --- THE FIX: Updated Fetch Event to handle redirects properly ---
self.addEventListener('fetch', event => {
  // We only want to handle GET requests
  if (event.request.method !== 'GET') { return; }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // --- FIX FOR SAFARI ---
        // If it's a redirect, don't cache it, just return it for the browser to handle.
        if (response.status === 0 || response.redirected) {
          return response;
        }

        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
        });

        return response;
      })
      .catch(() => {
        // Network request failed, try to get it from the cache.
        return caches.match(event.request);
      })
  );
});

