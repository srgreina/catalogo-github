"use strict";

/* Service worker: permite instalar la web como aplicación y que abra sin conexión con
   los últimos datos que se descargaron.

   Estrategia «red primero»: siempre se intenta bajar la versión nueva (la web se
   actualiza una vez al mes y no debe quedarse una copia vieja) y solo si no hay red se
   usa la copia guardada. Cada respuesta buena se guarda, salvo que sea idéntica a la
   que ya hay (se compara el ETag), para no reescribir 13 MB de datos en cada visita. */

const CACHE = "catalogo-v1";
const BASICOS = ["./", "estilo.css", "app.js", "glosario.json", "icono.svg",
                 "icono-192.png", "icono-512.png", "manifest.webmanifest"];

self.addEventListener("install", (ev) => {
  self.skipWaiting();
  // Si algún fichero falla no se bloquea la instalación: se irán guardando al usarlos.
  ev.waitUntil(caches.open(CACHE).then((c) => Promise.allSettled(BASICOS.map((u) => c.add(u)))));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

async function guardar(peticion, respuesta) {
  const cache = await caches.open(CACHE);
  const previa = await cache.match(peticion);
  const etag = respuesta.headers.get("etag");
  if (previa && etag && previa.headers.get("etag") === etag) return;     // no ha cambiado
  await cache.put(peticion, respuesta);
}

self.addEventListener("fetch", (ev) => {
  const peticion = ev.request;
  if (peticion.method !== "GET" || new URL(peticion.url).origin !== self.location.origin) return;
  ev.respondWith(
    fetch(peticion)
      .then((respuesta) => {
        if (respuesta.status === 200) ev.waitUntil(guardar(peticion, respuesta.clone()).catch(() => {}));
        return respuesta;
      })
      .catch(async () => {
        const guardada = await caches.match(peticion);
        if (guardada) return guardada;
        if (peticion.mode === "navigate") return (await caches.match("./")) || Response.error();
        return Response.error();
      }));
});
