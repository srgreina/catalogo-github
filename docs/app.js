"use strict";

const TIPOS = { mcp: "Servidor MCP", skill: "Skill", programa: "Programa", lista: "Lista awesome" };
const DOMINIOS = {
  construccion_energia: "Construcción y energía",
  finanzas_inversion: "Finanzas",
  deporte_geodatos: "Deporte y geodatos",
  documentos_productividad: "Documentos y productividad",
};
const LICENCIAS = { libre: "uso libre", otra: "revisar licencia", sin_licencia: "sin licencia: no reutilizable" };
const SEMAFORO = { v: "verde", a: "ámbar", r: "rojo" };
const FUENTES = { github: "búsqueda de GitHub", "registro-mcp": "registro oficial MCP", awesome: "listas awesome" };
const POR_TANDA = 50;

const $ = (sel) => document.querySelector(sel);
const estado = {
  datos: null,
  pestana: "catalogo",
  texto: "",
  orden: "estrellas",
  ordenSkills: "estrellas",
  filtros: { tipo: new Set(), dominio: new Set(), semaforo: new Set(), fuente: new Set() },
  estrellas: 0,
  actividad: 0,
  licencia: "",
  resultado: [],
  mostrados: 0,
};
const hoy = Date.now();

/* ---------- Utilidades ---------- */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const normalizar = (s) => String(s ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

const numero = (n) => Number(n || 0).toLocaleString("es-ES");

function fecha(iso) {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function dias(iso) {
  return iso ? Math.floor((hoy - Date.parse(iso)) / 86400000) : Infinity;
}

function hace(iso) {
  const n = dias(iso);
  if (n === Infinity) return "sin fecha";
  if (n < 1) return "hoy";
  if (n === 1) return "ayer";
  if (n < 31) return `hace ${n} días`;
  if (n < 365) return `hace ${Math.round(n / 30)} ${Math.round(n / 30) === 1 ? "mes" : "meses"}`;
  const anios = Math.round(n / 365);
  return `hace ${anios} ${anios === 1 ? "año" : "años"}`;
}

/* ---------- Carga ---------- */

async function cargar() {
  try {
    const resp = await fetch("datos.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    estado.datos = await resp.json();
  } catch (err) {
    $("#actualizado").textContent = "No se han podido cargar los datos.";
    $("#lista").innerHTML = `<li class="vacio">No se ha podido leer <code>datos.json</code> (${esc(err.message)}). Recarga la página; si sigue fallando, la actualización semanal puede estar en curso.</li>`;
    return;
  }
  for (const r of estado.datos.repos) {
    r._q = normalizar(r.n + " " + r.d);
  }
  const generado = new Date(estado.datos.generado);
  $("#actualizado").textContent = "Actualizado el " + generado.toLocaleString("es-ES", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const novedades = estado.datos.repos.filter((r) => r.nv).length;
  $("#num-novedades").textContent = novedades ? numero(novedades) : "";
  actualizar();
}

/* ---------- Filtrado y orden ---------- */

function filtrar() {
  const { filtros, estrellas, actividad, licencia, pestana } = estado;
  const palabras = normalizar(estado.texto).split(/\s+/).filter(Boolean);
  return estado.datos.repos.filter((r) => {
    if (pestana === "novedades" && !r.nv) return false;
    if (pestana === "skills" && !r.t.includes("skill")) return false;
    if (pestana === "skills" && estado.ordenSkills === "subida" && !(r.sb > 0)) return false;
    if (filtros.tipo.size && !r.t.some((t) => filtros.tipo.has(t))) return false;
    if (filtros.dominio.size && !r.m.some((d) => filtros.dominio.has(d))) return false;
    if (filtros.semaforo.size && !filtros.semaforo.has(r.sm)) return false;
    if (filtros.fuente.size && !r.fu.some((f) => filtros.fuente.has(f))) return false;
    if (estrellas && r.s < estrellas) return false;
    if (actividad && dias(r.p) > actividad) return false;
    if (licencia && r.lt !== licencia) return false;
    return palabras.every((p) => r._q.includes(p));
  });
}

function ordenar(lista) {
  const orden = estado.pestana === "skills" ? estado.ordenSkills : estado.orden;
  const porEstrellas = (a, b) => b.s - a.s;
  const criterios = {
    estrellas: porEstrellas,
    subida: (a, b) => (b.sb || 0) - (a.sb || 0) || porEstrellas(a, b),
    actividad: (a, b) => (b.p || "").localeCompare(a.p || ""),
    nuevos: (a, b) => (b.c || "").localeCompare(a.c || ""),
    nombre: (a, b) => a.n.localeCompare(b.n, "es", { sensitivity: "base" }),
  };
  return lista.sort(criterios[orden] || porEstrellas);
}

function actualizar() {
  if (!estado.datos) return;
  estado.resultado = ordenar(filtrar());
  estado.mostrados = 0;
  $("#lista").innerHTML = "";
  pintarAviso();
  pintarResumen();
  if (!estado.resultado.length) {
    $("#lista").innerHTML = `<li class="vacio">${mensajeVacio()}</li>`;
    return;
  }
  pintarTanda();
}

function mensajeVacio() {
  if (estado.pestana === "novedades" && estado.datos.primera_semana) {
    return "Esta es la primera actualización del catálogo, así que todavía no hay novedades. A partir de la próxima semana aparecerán aquí los repos nuevos.";
  }
  if (estado.pestana === "skills" && estado.ordenSkills === "subida") {
    return "Aún no hay estrellas de la semana anterior con las que comparar. Esta lista se llenará tras la próxima actualización.";
  }
  return "Ningún repo cumple estos filtros. Quita algún filtro o cambia la búsqueda.";
}

function pintarAviso() {
  const aviso = $("#aviso-vista");
  let texto = "";
  if (estado.pestana === "novedades") {
    texto = "Repos que han aparecido por primera vez en el catálogo durante los últimos 7 días.";
  } else if (estado.pestana === "skills") {
    texto = estado.ordenSkills === "subida"
      ? "Skills que más estrellas de GitHub han ganado desde la actualización anterior."
      : "Skills ordenadas por estrellas de GitHub. No hay datos de instalaciones reales: las estrellas son solo un indicio de uso.";
  }
  aviso.hidden = !texto;
  aviso.textContent = texto;
}

function pintarResumen() {
  const total = estado.resultado.length;
  $("#resumen").textContent = `${numero(total)} ${total === 1 ? "repo" : "repos"}`;
  const activos = contarFiltros();
  $("#num-filtros").textContent = activos || "";
}

function contarFiltros() {
  const { filtros } = estado;
  return filtros.tipo.size + filtros.dominio.size + filtros.semaforo.size + filtros.fuente.size
    + (estado.estrellas ? 1 : 0) + (estado.actividad ? 1 : 0) + (estado.licencia ? 1 : 0);
}

/* ---------- Pintado de la lista ---------- */

function pintarTanda() {
  const desde = estado.mostrados;
  const hasta = Math.min(desde + POR_TANDA, estado.resultado.length);
  const html = [];
  for (let i = desde; i < hasta; i++) html.push(fila(estado.resultado[i], i));
  $("#lista").insertAdjacentHTML("beforeend", html.join(""));
  estado.mostrados = hasta;
}

function fila(r, i) {
  const [propietario, nombre] = r.n.split("/");
  const tipos = r.t.map((t) => `<span class="etiqueta">${TIPOS[t] || t}</span>`).join("");
  const sube = r.sb > 0 ? `<span class="sube">+${numero(r.sb)} esta semana</span>` : "";
  return `<li class="ref" data-sm="${r.sm}" data-i="${i}">
    <button class="ref-resumen" type="button" aria-expanded="false">
      <span class="ref-nombre"><span><span class="propietario">${esc(propietario)}/</span>${esc(nombre)}</span>${r.nv ? '<span class="nuevo">Nuevo</span>' : ""}</span>
      <p class="ref-desc">${esc(r.d) || "<em>Sin descripción</em>"}</p>
      <span class="ref-specs">
        <span class="estrellas">★ ${numero(r.s)}</span>${sube}
        ${tipos}
        <span>${esc(r.l || "sin licencia")}</span>
        <span>Actividad ${hace(r.p)}</span>
      </span>
    </button>
  </li>`;
}

/* Detalles de cada repo: repartidos en docs/detalles/00..ff.json según el SHA-1 del nombre. */
const trozos = new Map();

async function detalle(r) {
  const clave = r.n.toLowerCase();
  const huella = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(clave));
  const trozo = [...new Uint8Array(huella).slice(0, 1)].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (!trozos.has(trozo)) {
    trozos.set(trozo, fetch(`detalles/${trozo}.json`).then((resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.json();
    }).catch((err) => { trozos.delete(trozo); throw err; }));
  }
  return (await trozos.get(trozo))[clave] || {};
}

function ficha(base, extra) {
  const r = { ...base, ...extra };
  const url = `https://github.com/${r.n}`;
  const dominios = r.m.length ? r.m.map((d) => DOMINIOS[d]).join(", ") : "Otros";
  const original = r.o
    ? `<details class="original"><summary>Ver descripción original</summary><p>${esc(r.o)}</p></details>`
    : "";
  const web = r.w ? `<a href="${esc(r.w)}" target="_blank" rel="noopener">Web del proyecto</a>` : "";
  return `<div class="ficha">
    <div class="senal" data-sm="${r.sm}" role="img" aria-label="Semáforo ${SEMAFORO[r.sm]}"><i class="r"></i><i class="a"></i><i class="v"></i></div>
    <div class="ficha-cuerpo">
      <h3>Semáforo ${SEMAFORO[r.sm]}${r.sp != null ? ` (${r.sp} puntos)` : ""}</h3>
      <ul class="motivos">${(r.mo || []).map((m) => `<li>${esc(m)}</li>`).join("") || "<li>Sin puntos a favor</li>"}</ul>
      <p class="orientativo">Valoración orientativa a partir de datos públicos. No es un análisis de seguridad del código.</p>
      ${original}
      <dl class="datos">
        <dt>Tipo</dt><dd>${r.t.map((t) => TIPOS[t] || t).join(", ")}</dd>
        <dt>Dominio</dt><dd>${dominios}</dd>
        <dt>Licencia</dt><dd>${esc(r.l || "Ninguna")} (${LICENCIAS[r.lt]})</dd>
        <dt>Estrellas</dt><dd>${numero(r.s)}${r.sb ? ` (+${numero(r.sb)} esta semana)` : ""}</dd>
        <dt>Forks</dt><dd>${numero(r.f)}</dd>
        <dt>Incidencias</dt><dd>${numero(r.i)} abiertas</dd>
        <dt>Propietario</dt><dd>${r.org ? "Organización" : "Particular"}</dd>
        ${r.lg ? `<dt>Lenguaje</dt><dd>${esc(r.lg)}</dd>` : ""}
        <dt>Creado</dt><dd>${fecha(r.c)}</dd>
        <dt>Último cambio</dt><dd>${fecha(r.p)} (${hace(r.p)})</dd>
        <dt>Fuentes</dt><dd>${r.fu.map((f) => FUENTES[f] || f).join(", ")}</dd>
        ${r.tp ? `<dt>Topics</dt><dd>${r.tp.map(esc).join(", ")}</dd>` : ""}
      </dl>
      <div class="enlaces"><a href="${url}" target="_blank" rel="noopener">Abrir en GitHub</a>${web}</div>
    </div>
  </div>`;
}

/* ---------- Eventos ---------- */

$("#lista").addEventListener("click", async (ev) => {
  const boton = ev.target.closest(".ref-resumen");
  if (!boton) return;
  const li = boton.parentElement;
  const abierta = boton.getAttribute("aria-expanded") === "true";
  boton.setAttribute("aria-expanded", String(!abierta));
  li.querySelector(".ficha")?.remove();
  if (abierta) return;
  const r = estado.resultado[Number(li.dataset.i)];
  let extra = {};
  try {
    extra = await detalle(r);
  } catch {
    extra = { mo: ["No se han podido cargar los motivos. Vuelve a abrir la ficha para reintentarlo."] };
  }
  if (boton.getAttribute("aria-expanded") === "true" && !li.querySelector(".ficha")) {
    li.insertAdjacentHTML("beforeend", ficha(r, extra));
  }
});

new IntersectionObserver((entradas) => {
  if (entradas[0].isIntersecting && estado.mostrados < estado.resultado.length) pintarTanda();
}, { rootMargin: "800px" }).observe($("#centinela"));

let espera;
$("#buscar").addEventListener("input", (ev) => {
  clearTimeout(espera);
  espera = setTimeout(() => { estado.texto = ev.target.value; actualizar(); }, 150);
});

document.querySelectorAll(".pestanas button").forEach((boton) => {
  boton.addEventListener("click", () => {
    estado.pestana = boton.dataset.pestana;
    document.querySelectorAll(".pestanas button").forEach((b) =>
      b.setAttribute("aria-selected", String(b === boton)));
    const skills = estado.pestana === "skills";
    $("#subvista-skills").hidden = !skills;
    $(".orden").hidden = skills;
    actualizar();
  });
});

document.querySelectorAll("[data-orden-skills]").forEach((boton) => {
  boton.addEventListener("click", () => {
    estado.ordenSkills = boton.dataset.ordenSkills;
    document.querySelectorAll("[data-orden-skills]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === boton)));
    actualizar();
  });
});

document.querySelectorAll("[data-filtro]").forEach((grupo) => {
  grupo.addEventListener("change", (ev) => {
    const conjunto = estado.filtros[grupo.dataset.filtro];
    ev.target.checked ? conjunto.add(ev.target.value) : conjunto.delete(ev.target.value);
    actualizar();
  });
});

$("#f-estrellas").addEventListener("change", (ev) => { estado.estrellas = Number(ev.target.value); actualizar(); });
$("#f-actividad").addEventListener("change", (ev) => { estado.actividad = Number(ev.target.value); actualizar(); });
$("#f-licencia").addEventListener("change", (ev) => { estado.licencia = ev.target.value; actualizar(); });
$("#orden").addEventListener("change", (ev) => { estado.orden = ev.target.value; actualizar(); });

$("#limpiar").addEventListener("click", () => {
  Object.values(estado.filtros).forEach((c) => c.clear());
  document.querySelectorAll("#filtros input[type=checkbox]").forEach((c) => { c.checked = false; });
  document.querySelectorAll("#filtros select").forEach((s) => { s.selectedIndex = 0; });
  estado.estrellas = 0;
  estado.actividad = 0;
  estado.licencia = "";
  actualizar();
});

/* Panel de filtros en el móvil */
function abrirFiltros(abrir) {
  $("#filtros").classList.toggle("abierto", abrir);
  $("#fondo-hoja").hidden = !abrir;
  document.body.style.overflow = abrir ? "hidden" : "";
  if (abrir) $("#cerrar-filtros").focus();
}
$("#abrir-filtros").addEventListener("click", () => abrirFiltros(true));
$("#cerrar-filtros").addEventListener("click", () => abrirFiltros(false));
$("#ver-resultados").addEventListener("click", () => abrirFiltros(false));
$("#fondo-hoja").addEventListener("click", () => abrirFiltros(false));
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && $("#filtros").classList.contains("abierto")) abrirFiltros(false);
});

cargar();
