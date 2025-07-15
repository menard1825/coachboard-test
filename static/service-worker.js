// A minimal service worker to allow the app to be installed.
self.addEventListener('fetch', (event) => {
  // This service worker doesn't do any caching for now.
  // It just exists to make the app installable (PWA).
  return;
});