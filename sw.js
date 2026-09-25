/* Desk Dashboard — service worker
 * - Shell estático + logos: cache-first
 * - datos.json: network-first (fallback a cache offline)
 * Todas las rutas son relativas al scope (funciona en sub-path de GitHub Pages).
 */
"use strict";

var VERSION = "dd-v11";
var SHELL_CACHE = VERSION + "-shell";
var DATA_CACHE = VERSION + "-data";

var SHELL_ASSETS = [
  "./",
  "index.html",
  "styles.css?v=16",
  "app.js?v=11",
  "manifest.webmanifest",
  "assets/logo.svg?v=7",
  "assets/favicon.ico?v=7",
  "assets/favicon-32.png?v=7",
  "assets/favicon-16.png?v=7",
  "assets/apple-touch-icon.png?v=7",
  "assets/icon-192.png",
  "assets/icon-512.png",
  "assets/icon-maskable-512.png",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(function (cache) {
      return cache.addAll(SHELL_ASSETS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) {
          return k.indexOf("dd-") === 0 && k !== SHELL_CACHE && k !== DATA_CACHE;
        }).map(function (k) { return caches.delete(k); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function isDataRequest(url) {
  return /\/datos\.json$/.test(url.pathname);
}

function networkFirstData(request) {
  // Clave normalizada sin ?ts= para que el fallback offline funcione.
  var key = new URL("datos.json", self.registration.scope).href;
  return fetch(request, { cache: "no-store" }).then(function (resp) {
    if (resp && resp.ok) {
      var copy = resp.clone();
      caches.open(DATA_CACHE).then(function (c) { c.put(key, copy); });
    }
    return resp;
  }).catch(function () {
    return caches.open(DATA_CACHE).then(function (c) {
      return c.match(key);
    }).then(function (hit) {
      return hit || new Response(JSON.stringify({ error: "offline" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      });
    });
  });
}

function cacheFirst(request) {
  return caches.match(request).then(function (hit) {
    if (hit) return hit;
    return fetch(request).then(function (resp) {
      if (resp && resp.ok && resp.type === "basic") {
        var copy = resp.clone();
        caches.open(SHELL_CACHE).then(function (c) { c.put(request, copy); });
      }
      return resp;
    });
  });
}

function networkFirstPage(request) {
  // Navegación: intenta red (HTML fresco), cae al shell cacheado offline.
  return fetch(request).then(function (resp) {
    if (resp && resp.ok) {
      var copy = resp.clone();
      caches.open(SHELL_CACHE).then(function (c) { c.put("index.html", copy); });
    }
    return resp;
  }).catch(function () {
    return caches.match("index.html").then(function (hit) {
      return hit || caches.match("./");
    });
  });
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // fuentes externas: red directa

  if (isDataRequest(url)) {
    event.respondWith(networkFirstData(req));
  } else if (req.mode === "navigate") {
    event.respondWith(networkFirstPage(req));
  } else {
    event.respondWith(cacheFirst(req));
  }
});
