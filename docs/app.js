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
const FUENTES = {
  github: "búsqueda de GitHub", "registro-mcp": "registro oficial MCP",
  awesome: "listas awesome", "skills-sh": "skills.sh",
};
const POR_TANDA = 50;
const RANGO_SEMAFORO = { v: 3, a: 2, r: 1 };
const CLAVE_FAVORITOS = "catalogo-favoritos";
const CLAVE_FILTROS = "catalogo-filtros";

const $ = (sel) => document.querySelector(sel);
const estado = {
  favoritos: new Set(),
  soloFavoritos: false,
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
  ampliar: true,     // ampliar la búsqueda con equivalentes en inglés
  grupos: [],        // la búsqueda ya interpretada (ver «interpretar»)
};
let glosario = null;   // español → equivalentes en inglés (docs/glosario.json)
let indiceEn = null;   // texto original y topics de cada repo, en el mismo orden que datos.json
const hoy = Date.now();

/* ---------- Utilidades ---------- */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* localStorage puede no estar disponible (modo privado, bloqueado): nunca debe romper la web. */
function leerLocal(clave) {
  try { return localStorage.getItem(clave); } catch { return null; }
}
function guardarLocal(clave, valor) {
  try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento: se ignora */ }
}

const normalizar = (s) => String(s ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/* Texto para buscar: sin tildes, en minúsculas y con espacios en vez de signos (igual que
   `a_busqueda` en generar_web.py). Se evita a propósito la expresión \p{L}\p{N}: es 4 veces
   más lenta y esto se ejecuta sobre 40.000 repos. */
const limpiar = (s) => {
  s = String(s ?? "");
  if (/[^\x00-\x7f]/.test(s)) {
    // Sin tildes (NFD separa la letra de su marca) y sin signos que no sean ASCII:
    // Latin-1 (¿ ¡ « » …), puntuación y símbolos generales, signos chinos/japoneses,
    // formas de ancho completo y emoji (pares sustitutos).
    s = s.normalize("NFD")
      .replace(/[̀-゙゚ͯ]/g, "")
      .replace(/[\u0080-¿ -⯿　-〿＀-／：-＠\ud800-\udfff]+/g, " ");
  }
  // Lo que no sea letra o número ASCII (los demás caracteres se conservan) pasa a espacio.
  return s.toLowerCase().replace(/[^a-z0-9\u0080-￿]+/g, " ").trim();
};

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
    $("#lista").innerHTML = `<li class="vacio">No se ha podido leer <code>datos.json</code> (${esc(err.message)}). Recarga la página; si sigue fallando, la actualización mensual puede estar en curso.</li>`;
    return;
  }
  try { estado.favoritos = new Set(JSON.parse(leerLocal(CLAVE_FAVORITOS) || "[]")); } catch { /* vacío */ }
  pintarNumFavoritos();
  leerFiltros();
  const generado = new Date(estado.datos.generado);
  $("#actualizado").textContent = "Actualizado el " + generado.toLocaleString("es-ES", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const novedades = estado.datos.repos.filter((r) => r.nv).length;
  $("#num-novedades").textContent = novedades ? numero(novedades) : "";
  actualizar();
  // El glosario y el índice en inglés se piden cuando el navegador está libre,
  // para no retrasar la primera pantalla.
  (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(() => {
    cargarGlosario();
    cargarIndiceEn();
    prepararEnSegundoPlano();
  });
}

/* ---------- Búsqueda ampliada: español + equivalentes en inglés ---------- */

/* Cada alternativa del glosario se guarda ya preparada: «patron» es lo que se busca
   en el texto (con espacios para respetar el inicio de palabra) y «texto» lo que se
   enseña al usuario. Si termina en «!», solo vale la palabra exacta. */
function compilar(alternativa) {
  const exacta = alternativa.endsWith("!");
  const texto = limpiar(exacta ? alternativa.slice(0, -1) : alternativa);
  return { patron: exacta ? ` ${texto} ` : ` ${texto}`, texto };
}

/* Texto de búsqueda de cada repo (`_n` nombre, `_q` nombre + descripción), con espacios a
   los lados para poder buscar palabras enteras. Preparar los 40.000 cuesta algo más de medio
   segundo (varios en un móvil lento), así que se hace en segundo plano y por trozos; si
   alguien busca antes de que termine, se completa en ese momento. */
let preparados = 0;
function prepararTextos(hasta = Infinity) {
  const repos = estado.datos.repos;
  const fin = Math.min(repos.length, hasta);
  for (; preparados < fin; preparados++) {
    const r = repos[preparados];
    r._i = preparados;
    r._n = ` ${limpiar(r.n)} `;
    r._q = ` ${limpiar(r.n + " " + r.d)} `;
  }
}

function prepararEnSegundoPlano() {
  if (preparados >= estado.datos.repos.length) return;
  prepararTextos(preparados + 2000);
  setTimeout(prepararEnSegundoPlano, 0);     // deja respirar al navegador entre trozos
}

async function pedirJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function cargarGlosario() {
  try {
    const datos = await pedirJson("glosario.json");
    glosario = new Map(Object.entries(datos).map(([k, v]) => [limpiar(k), v.map(compilar)]));
  } catch { return; }              // sin glosario se busca como siempre
  if (estado.texto.trim()) actualizar();
}

async function cargarIndiceEn() {
  try {
    const datos = await pedirJson("indice_en.json");
    if (datos.length !== estado.datos.repos.length) return;   // no casa con datos.json: se ignora
    indiceEn = datos.map((t) => ` ${t} `);
  } catch { return; }
  if (estado.texto.trim()) actualizar();
}

/* Forma escrita y formas en singular («facturas» → «factura», «ciudades» → «ciudad»). */
function variantes(palabra) {
  const v = [palabra];
  if (palabra.length > 3 && palabra.endsWith("s")) v.push(palabra.slice(0, -1));
  if (palabra.length > 4 && palabra.endsWith("es")) v.push(palabra.slice(0, -2));
  return v;
}

/* Convierte lo escrito en «grupos». Cada grupo es una palabra (o frase del glosario,
   como «hoja de cálculo») con sus alternativas: `es` son las formas en español (se
   buscan como trozo de texto) y `en` los equivalentes del glosario. Un repo cumple la
   búsqueda si cumple todos los grupos, y un grupo se cumple con cualquier alternativa. */
function interpretar(texto, forzar = false) {
  const tokens = limpiar(texto).split(" ").filter(Boolean);
  const usarGlosario = glosario && (estado.ampliar || forzar);
  const grupos = [];
  let i = 0;
  while (i < tokens.length) {
    let encontrado = null;
    if (usarGlosario) {
      // Primero las frases más largas: «hoja de cálculo» antes que «hoja».
      for (let largo = Math.min(4, tokens.length - i); largo >= 1 && !encontrado; largo--) {
        const frase = tokens.slice(i, i + largo);
        for (const v of variantes(frase[frase.length - 1])) {
          const equivalentes = glosario.get([...frase.slice(0, -1), v].join(" "));
          if (equivalentes) { encontrado = { largo, frase, equivalentes }; break; }
        }
      }
    }
    if (encontrado) {
      grupos.push({ es: variantes(encontrado.frase.join(" ")), en: encontrado.equivalentes });
      i += encontrado.largo;
    } else {
      grupos.push({ es: variantes(tokens[i]), en: [] });
      i += 1;
    }
  }
  return grupos;
}

function coincide(r, grupos) {
  if (!grupos.length) return true;
  // _h = texto en español + texto en inglés unidos (se crea la primera vez que hace
  // falta): así cada alternativa se busca una sola vez por repo.
  const h = indiceEn && estado.ampliar ? (r._h ??= r._q + indiceEn[r._i]) : r._q;
  return grupos.every((g) =>
    g.es.some((a) => h.includes(a)) || g.en.some((a) => h.includes(a.patron)));
}

/* Más puntos cuanto más «a la vista» está lo buscado: nombre 4, descripción 3 (lo
   escrito) o 2 (equivalente en inglés), y solo en el texto original o los topics 1. */
function puntuar(r) {
  const ei = indiceEn && estado.ampliar ? indiceEn[r._i] : "";
  let total = 0;
  for (const g of estado.grupos) {
    total += g.es.some((a) => r._n.includes(a)) || g.en.some((a) => r._n.includes(a.patron)) ? 4
      : g.es.some((a) => r._q.includes(a)) ? 3
      : g.en.some((a) => r._q.includes(a.patron)) ? 2
      : ei ? 1 : 0;
  }
  return total;
}

/* Línea bajo el buscador que cuenta qué se ha ampliado, y deja volver a «solo español». */
function pintarAmplia() {
  const el = $("#amplia");
  const reales = estado.ampliar ? estado.grupos : interpretar(estado.texto, true);
  const terminos = [...new Set(reales.flatMap((g) => g.en.map((a) => a.texto)))];
  if (!estado.texto.trim() || !glosario || !terminos.length) { el.hidden = true; return; }
  const lista = terminos.slice(0, 8).join(", ") + (terminos.length > 8 ? "…" : "");
  el.innerHTML = estado.ampliar
    ? `Buscando también en inglés: <strong>${esc(lista)}</strong>${indiceEn ? "" : " (cargando textos en inglés…)"}
       <button type="button" class="enlace" data-amplia="no">Solo español</button>`
    : `Búsqueda solo en español. <button type="button" class="enlace" data-amplia="si">Ampliar a inglés</button>`;
  el.hidden = false;
}

/* ---------- Filtrado y orden ---------- */

function filtrar() {
  const { filtros, estrellas, actividad, licencia, pestana, grupos } = estado;
  if (grupos.length) prepararTextos();       // si se busca, hacen falta todos los textos ya
  return estado.datos.repos.filter((r) => {
    if (pestana === "novedades" && !r.nv) return false;
    if (pestana === "skills" && !r.t.includes("skill")) return false;
    if (pestana === "skills" && estado.ordenSkills === "subida" && !(r.sb > 0)) return false;
    if (estado.soloFavoritos && !estado.favoritos.has(r.n)) return false;
    if (filtros.tipo.size && !r.t.some((t) => filtros.tipo.has(t))) return false;
    if (filtros.dominio.size && !r.m.some((d) => filtros.dominio.has(d))) return false;
    if (filtros.semaforo.size && !filtros.semaforo.has(r.sm)) return false;
    if (filtros.fuente.size && !r.fu.some((f) => filtros.fuente.has(f))) return false;
    if (estrellas && r.s < estrellas) return false;
    if (actividad && dias(r.p) > actividad) return false;
    if (licencia && r.lt !== licencia) return false;
    return coincide(r, grupos);
  });
}

function ordenar(lista) {
  const orden = estado.pestana === "skills" ? estado.ordenSkills : estado.orden;
  const porEstrellas = (a, b) => b.s - a.s;
  if (orden === "relevancia") lista.forEach((r) => { r._rel = puntuar(r); });
  const criterios = {
    estrellas: porEstrellas,
    relevancia: (a, b) => b._rel - a._rel || porEstrellas(a, b),
    subida: (a, b) => (b.sb || 0) - (a.sb || 0) || porEstrellas(a, b),
    semaforo: (a, b) => RANGO_SEMAFORO[b.sm] - RANGO_SEMAFORO[a.sm] || porEstrellas(a, b),
    actividad: (a, b) => (b.p || "").localeCompare(a.p || ""),
    nuevos: (a, b) => (b.c || "").localeCompare(a.c || ""),
    nombre: (a, b) => a.n.localeCompare(b.n, "es", { sensitivity: "base" }),
  };
  return lista.sort(criterios[orden] || porEstrellas);
}

function actualizar() {
  if (!estado.datos) return;
  if (estado.pestana === "ideas") { guardarFiltros(); return; }
  estado.grupos = interpretar(estado.texto);
  estado.resultado = ordenar(filtrar());
  guardarFiltros();
  estado.mostrados = 0;
  $("#lista").innerHTML = "";
  pintarAmplia();
  pintarAviso();
  pintarResumen();
  if (!estado.resultado.length) {
    $("#lista").innerHTML = `<li class="vacio">${mensajeVacio()}</li>`;
    return;
  }
  rellenar();
}

/* Pinta tandas hasta que la lista sobrepase la pantalla (el observador solo
   avisa cuando el centinela entra en pantalla, no si ya estaba dentro). */
function rellenar() {
  const centinela = $("#centinela");
  do {
    pintarTanda();
  } while (estado.mostrados < estado.resultado.length
           && centinela.getBoundingClientRect().top < window.innerHeight + 800);
}

function mensajeVacio() {
  if (estado.pestana === "novedades") {
    return estado.datos.primera_ejecucion
      ? "Esta es la primera actualización del catálogo, así que todavía no hay novedades. A partir de la próxima aparecerán aquí los repos nuevos."
      : "No hay repos nuevos en el último mes que cumplan estos filtros.";
  }
  if (estado.pestana === "skills" && estado.ordenSkills === "subida") {
    return "Aún no hay estrellas del mes anterior con las que comparar. Esta lista se llenará tras la próxima actualización mensual.";
  }
  return "Ningún repo cumple estos filtros. Quita algún filtro o cambia la búsqueda.";
}

function pintarAviso() {
  const aviso = $("#aviso-vista");
  let texto = "";
  if (estado.pestana === "novedades") {
    texto = "Repos que han aparecido por primera vez en el catálogo en el último mes (desde la actualización anterior).";
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
  let texto = `${numero(total)} ${total === 1 ? "repo" : "repos"}`;
  if (total) {
    const de = (t) => estado.resultado.filter((r) => r.t.includes(t)).length;
    const libres = Math.round(100 * estado.resultado.filter((r) => r.lt === "libre").length / total);
    texto += ` · ${numero(de("mcp"))} MCP · ${numero(de("skill"))} skills · ${numero(de("programa"))} programas · ${libres} % de uso libre`;
  }
  $("#resumen").textContent = texto;
  const activos = contarFiltros();
  $("#num-filtros").textContent = activos || "";
}

function contarFiltros() {
  const { filtros } = estado;
  return filtros.tipo.size + filtros.dominio.size + filtros.semaforo.size + filtros.fuente.size
    + (estado.estrellas ? 1 : 0) + (estado.actividad ? 1 : 0) + (estado.licencia ? 1 : 0)
    + (estado.soloFavoritos ? 1 : 0);
}

/* ---------- Filtros en la dirección (#...) y recordados ---------- */

function textoFiltros() {
  const p = new URLSearchParams();
  if (estado.pestana !== "catalogo") p.set("v", estado.pestana);
  if (estado.texto) p.set("q", estado.texto);
  for (const [clave, conjunto] of Object.entries(estado.filtros)) {
    if (conjunto.size) p.set(clave, [...conjunto].join(","));
  }
  if (estado.estrellas) p.set("e", estado.estrellas);
  if (estado.actividad) p.set("a", estado.actividad);
  if (estado.licencia) p.set("l", estado.licencia);
  if (estado.orden !== "estrellas") p.set("o", estado.orden);
  if (estado.ordenSkills !== "estrellas") p.set("os", estado.ordenSkills);
  if (estado.soloFavoritos) p.set("fav", "1");
  if (!estado.ampliar) p.set("ses", "1");       // «solo español»
  return p.toString();
}

function guardarFiltros() {
  const texto = textoFiltros();
  guardarLocal(CLAVE_FILTROS, texto);
  try {
    history.replaceState(null, "", texto ? "#" + texto : location.pathname + location.search);
  } catch { /* la dirección no se puede cambiar: se ignora */ }
}

/* Aplica a la web los filtros de la dirección; si no hay, los de la última visita. */
function leerFiltros() {
  const texto = location.hash.slice(1) || leerLocal(CLAVE_FILTROS) || "";
  const p = new URLSearchParams(texto);
  const opcion = (id, valor, defecto) =>
    [...$(id).options].some((o) => o.value === String(valor)) ? String(valor) : defecto;

  Object.values(estado.filtros).forEach((c) => c.clear());
  for (const clave of Object.keys(estado.filtros)) {
    (p.get(clave) || "").split(",").filter(Boolean).forEach((v) => estado.filtros[clave].add(v));
  }
  estado.texto = p.get("q") || "";
  estado.estrellas = Number(opcion("#f-estrellas", p.get("e") || 0, "0"));
  estado.actividad = Number(opcion("#f-actividad", p.get("a") || 0, "0"));
  estado.licencia = opcion("#f-licencia", p.get("l") || "", "");
  estado.orden = opcion("#orden", p.get("o") || "estrellas", "estrellas");
  estado.ordenSkills = p.get("os") === "subida" ? "subida" : "estrellas";
  estado.soloFavoritos = p.get("fav") === "1";
  estado.ampliar = p.get("ses") !== "1";
  ponerPestana(["novedades", "skills", "ideas"].includes(p.get("v")) ? p.get("v") : "catalogo");

  $("#buscar").value = estado.texto;
  document.querySelectorAll("[data-filtro]").forEach((grupo) => {
    const conjunto = estado.filtros[grupo.dataset.filtro];
    grupo.querySelectorAll("input").forEach((i) => { i.checked = conjunto.has(i.value); });
  });
  $("#f-estrellas").value = String(estado.estrellas);
  $("#f-actividad").value = String(estado.actividad);
  $("#f-licencia").value = estado.licencia;
  $("#orden").value = estado.orden;
  $("#f-favoritos").checked = estado.soloFavoritos;
  document.querySelectorAll("[data-orden-skills]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.ordenSkills === estado.ordenSkills)));
}

function ponerPestana(nombre) {
  estado.pestana = nombre;
  document.querySelectorAll(".pestanas button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.pestana === nombre)));
  $("#subvista-skills").hidden = nombre !== "skills";
  $(".orden").hidden = nombre === "skills";
  // La pestaña Ideas no usa los filtros ni la lista.
  const ideas = nombre === "ideas";
  for (const sel of ["#filtros", ".barra", ".barra-resultados", "#lista", "#centinela"]) {
    $(sel).hidden = ideas;
  }
  $("#vista-ideas").hidden = !ideas;
  document.querySelector(".marco").classList.toggle("sin-filtros", ideas);
  if (ideas) {
    if (!$("#panel").hidden) cerrarPanel();
    $("#aviso-vista").hidden = true;
    $("#amplia").hidden = true;
    abrirFiltros(false);
    cargarIdeas();
  }
}

/* ---------- Favoritos ---------- */

function pintarNumFavoritos() {
  $("#num-favoritos").textContent = estado.favoritos.size ? `(${estado.favoritos.size})` : "";
}

function alternarFavorito(nombre) {
  const quitar = estado.favoritos.has(nombre);
  quitar ? estado.favoritos.delete(nombre) : estado.favoritos.add(nombre);
  guardarLocal(CLAVE_FAVORITOS, JSON.stringify([...estado.favoritos]));
  pintarNumFavoritos();
  return !quitar;
}

/* ---------- Descarga de los resultados en CSV ---------- */

function descargarCSV() {
  // Separador «;» y BOM UTF-8: así Excel en español lo abre bien. Los textos que
  // empiezan por = + - @ se marcan para que Excel no los tome por una fórmula.
  const celda = (v) => {
    let s = String(v ?? "").replace(/\s+/g, " ");
    if (/^[=+\-@]/.test(s)) s = "'" + s;
    return `"${s.replace(/"/g, '""')}"`;
  };
  const filas = [["Repositorio", "Enlace", "Descripción", "Tipo", "Dominio", "Estrellas",
                  "Licencia", "Semáforo", "Creado", "Último cambio"]];
  for (const r of estado.resultado) {
    filas.push([r.n, `https://github.com/${r.n}`, r.d, r.t.map((t) => TIPOS[t] || t).join(", "),
                r.m.map((d) => DOMINIOS[d]).join(", "), r.s, r.l || "sin licencia",
                SEMAFORO[r.sm], r.c || "", r.p || ""]);
  }
  const csv = "﻿" + filas.map((f) => f.map(celda).join(";")).join("\r\n");
  const enlace = document.createElement("a");
  enlace.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  enlace.download = `catalogo-github-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(enlace.href), 5000);
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
  const sube = r.sb > 0 ? `<span class="sube">+${numero(r.sb)} este mes</span>` : "";
  return `<li class="ref" data-sm="${r.sm}" data-i="${i}">
    <button class="ref-resumen" type="button" aria-haspopup="dialog" aria-controls="panel">
      <span class="ref-nombre"><span><span class="propietario">${esc(propietario)}/</span>${esc(nombre)}</span>${r.nv ? '<span class="nuevo">Nuevo</span>' : ""}<span class="fav-marca" title="Favorito" ${estado.favoritos.has(r.n) ? "" : "hidden"}>♥</span></span>
      <span class="ref-desc">${esc(r.d) || "<em>Sin descripción</em>"}</span>
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

/* ---------- Panel lateral con el resumen de cada repo ---------- */

const seccion = (titulo, contenido) => `<section class="bloque"><h3>${titulo}</h3>${contenido}</section>`;
const vinetas = (items) => `<ul class="vinetas">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

function fichaPanel(base, extra) {
  const r = { ...base, ...extra };
  const rs = r.rs || {};                       // resumen automático (ver resumir.py)
  const [propietario, nombre] = r.n.toLowerCase().split("/");
  const url = `https://github.com/${r.n}`;
  const dominios = r.m.length ? r.m.map((d) => DOMINIOS[d]).join(", ") : "Otros";
  // La web del proyecto la escribe cualquiera: solo se enlaza si es http(s).
  const web = r.w && /^https?:\/\//i.test(r.w)
    ? `<a href="${esc(r.w)}" target="_blank" rel="noopener noreferrer">Web del proyecto</a>` : "";
  const favorito = estado.favoritos.has(r.n);

  // Para qué sirve: la descripción de GitHub y, si aporta algo más, el comienzo del README.
  let sirve = `<p>${esc(r.d) || "<em>Sin descripción</em>"}</p>`;
  if (rs.q) sirve += `<p>${esc(rs.q)}</p>`;
  if (r.o) sirve += `<details class="original"><summary>Ver descripción original</summary><p>${esc(r.o)}</p></details>`;
  if (rs.qo) sirve += `<details class="original"><summary>Ver el texto original del README</summary><p>${esc(rs.qo)}</p></details>`;

  // Cómo usarlo: comandos del README y datos del registro oficial MCP. Las direcciones se
  // muestran como texto, sin enlace: son puntos de conexión para el cliente MCP, no páginas.
  const uso = (rs.u || []).map((c) => `<li><code>${esc(c)}</code></li>`);
  if (r.pq) uso.push(`<li>Paquete (registro oficial MCP): ${r.pq.map(esc).join(", ")}</li>`);
  (r.rt || []).forEach((u) => uso.push(`<li>Servidor remoto: <code>${esc(u)}</code></li>`));

  const skills = r.ss ? seccion("Skills incluidas (skills.sh)", `<ul class="chips">${
    r.ss.map((n) => `<li><a href="https://skills.sh/${encodeURIComponent(propietario)}/${encodeURIComponent(nombre)}/${encodeURIComponent(n)}" target="_blank" rel="noopener">${esc(n)}</a></li>`).join("")
  }${r.sn > r.ss.length ? `<li class="mas">y ${numero(r.sn - r.ss.length)} más</li>` : ""}</ul>`) : "";

  const hayResumen = rs.q || rs.c || rs.u || rs.r || rs.k;
  const aviso = hayResumen
    ? (rs.tc
      ? `Resumen automático: se extrae del README con reglas y se traduce con IA (Claude), así que puede tener errores.`
      : `Resumen automático: se extrae del README con reglas (sin IA) y se traduce con traducción automática, así que puede tener errores.`)
    : `Todavía no hay resumen automático de este repo (se hacen para los de 50 estrellas o más).`;

  return `<div class="ficha-panel">
    <p class="rapido"><span class="estrellas">★ ${numero(r.s)}${r.sb ? ` (+${numero(r.sb)} este mes)` : ""}</span>
      ${r.t.map((t) => `<span class="etiqueta">${TIPOS[t] || t}</span>`).join("")}
      <span>${esc(r.l || "sin licencia")}</span> <span>Actividad ${hace(r.p)}</span></p>
    ${seccion("Para qué sirve", sirve)}
    ${rs.k ? seccion("Cuándo usarla (según su SKILL.md)", `<p>${esc(rs.k)}</p>`) : ""}
    ${rs.c ? seccion("Características principales", vinetas(rs.c)) : ""}
    ${uso.length ? seccion("Cómo usarlo", `<ul class="vinetas comandos">${uso.join("")}</ul>`) : ""}
    ${rs.r ? seccion("Rendimiento: lo que afirma el README", `${vinetas(rs.r)}<p class="orientativo">Son cifras del propio proyecto, sin verificar.</p>`) : ""}
    ${skills}
    <p class="aviso-auto">${aviso} <a href="${url}#readme" target="_blank" rel="noopener">Leer el README completo en GitHub</a></p>

    <section class="bloque semaforo-bloque">
      <div class="senal" data-sm="${r.sm}" role="img" aria-label="Semáforo ${SEMAFORO[r.sm]}"><i class="r"></i><i class="a"></i><i class="v"></i></div>
      <div>
        <h3>Semáforo ${SEMAFORO[r.sm]}${r.sp != null ? ` (${r.sp} puntos)` : ""}</h3>
        <ul class="motivos">${(r.mo || []).map((m) => `<li>${esc(m)}</li>`).join("") || "<li>Sin puntos a favor</li>"}</ul>
        <p class="orientativo">Valoración orientativa a partir de datos públicos. No es un análisis de seguridad del código.</p>
      </div>
    </section>

    <dl class="datos">
      <dt>Tipo</dt><dd>${r.t.map((t) => TIPOS[t] || t).join(", ")}</dd>
      <dt>Dominio</dt><dd>${dominios}</dd>
      <dt>Licencia</dt><dd>${esc(r.l || "Ninguna")} (${LICENCIAS[r.lt]})</dd>
      <dt>Forks</dt><dd>${numero(r.f)}</dd>
      <dt>Incidencias</dt><dd>${numero(r.i)} abiertas</dd>
      <dt>Propietario</dt><dd>${r.org ? "Organización" : "Particular"}</dd>
      ${r.lg ? `<dt>Lenguaje</dt><dd>${esc(r.lg)}</dd>` : ""}
      <dt>Creado</dt><dd>${fecha(r.c)}</dd>
      <dt>Último cambio</dt><dd>${fecha(r.p)} (${hace(r.p)})</dd>
      <dt>Fuentes</dt><dd>${r.fu.map((f) => FUENTES[f] || f).join(", ")}</dd>
      ${r.tp ? `<dt>Topics</dt><dd>${r.tp.map(esc).join(", ")}</dd>` : ""}
    </dl>
    <div class="enlaces"><a href="${url}" target="_blank" rel="noopener">Abrir en GitHub</a>${web}
      <button type="button" class="boton-fav" data-fav="${esc(r.n)}" aria-pressed="${favorito}">${favorito ? "♥ En favoritos" : "♡ Guardar en favoritos"}</button></div>
  </div>`;
}

let panelRepo = null;     // repo que se está viendo
let panelFila = null;     // su fila en la lista (si sigue en pantalla)
let panelPeticion = 0;    // para ignorar respuestas de un repo que ya se cerró o cambió

async function abrirPanel(r, fila) {
  panelFila?.classList.remove("activa");
  panelFila = fila || null;
  panelFila?.classList.add("activa");
  panelRepo = r;
  const peticion = ++panelPeticion;
  const cerrado = $("#panel").hidden;
  $("#panel-titulo").textContent = r.n;
  $("#panel-cuerpo").innerHTML = '<p class="vacio-corto">Cargando…</p>';
  $("#panel").hidden = false;
  document.body.classList.add("panel-abierto");
  if (cerrado) $("#cerrar-panel").focus();
  let extra = {};
  try {
    extra = await detalle(r);
  } catch {
    extra = { mo: ["No se ha podido cargar el detalle. Vuelve a abrir el repo para reintentarlo."] };
  }
  if (peticion !== panelPeticion) return;
  $("#panel-cuerpo").innerHTML = fichaPanel(r, extra);
  $("#panel-cuerpo").scrollTop = 0;
}

function cerrarPanel() {
  panelPeticion++;
  $("#panel").hidden = true;
  document.body.classList.remove("panel-abierto");
  panelFila?.classList.remove("activa");
  panelFila?.querySelector(".ref-resumen")?.focus({ preventScroll: true });
  panelFila = panelRepo = null;
}

/* ---------- Eventos ---------- */

$("#lista").addEventListener("click", (ev) => {
  const boton = ev.target.closest(".ref-resumen");
  if (!boton) return;
  const li = boton.parentElement;
  abrirPanel(estado.resultado[Number(li.dataset.i)], li);
});

$("#panel-cuerpo").addEventListener("click", (ev) => {
  const bfav = ev.target.closest(".boton-fav");
  if (!bfav) return;
  const activo = alternarFavorito(bfav.dataset.fav);
  bfav.setAttribute("aria-pressed", String(activo));
  bfav.textContent = activo ? "♥ En favoritos" : "♡ Guardar en favoritos";
  const marca = panelFila && document.contains(panelFila) ? panelFila.querySelector(".fav-marca") : null;
  if (marca) marca.hidden = !activo;
});

$("#cerrar-panel").addEventListener("click", cerrarPanel);

new IntersectionObserver((entradas) => {
  if (entradas[0].isIntersecting && estado.mostrados < estado.resultado.length) rellenar();
}, { rootMargin: "800px" }).observe($("#centinela"));

$("#amplia").addEventListener("click", (ev) => {
  const boton = ev.target.closest("[data-amplia]");
  if (!boton) return;
  estado.ampliar = boton.dataset.amplia === "si";
  actualizar();
});

let espera;
$("#buscar").addEventListener("input", (ev) => {
  clearTimeout(espera);
  espera = setTimeout(() => { estado.texto = ev.target.value; actualizar(); }, 150);
});

document.querySelectorAll(".pestanas button").forEach((boton) => {
  boton.addEventListener("click", () => {
    ponerPestana(boton.dataset.pestana);
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
$("#f-favoritos").addEventListener("change", (ev) => { estado.soloFavoritos = ev.target.checked; actualizar(); });
$("#descargar").addEventListener("click", descargarCSV);

/* Si se cambia la dirección a mano (o se pega otra), se aplican esos filtros. */
window.addEventListener("hashchange", () => {
  if (!estado.datos || location.hash.slice(1) === textoFiltros()) return;
  leerFiltros();
  actualizar();
});

$("#limpiar").addEventListener("click", () => {
  Object.values(estado.filtros).forEach((c) => c.clear());
  document.querySelectorAll("#filtros input[type=checkbox]").forEach((c) => { c.checked = false; });
  document.querySelectorAll("#filtros select").forEach((s) => { s.selectedIndex = 0; });
  estado.estrellas = 0;
  estado.actividad = 0;
  estado.licencia = "";
  estado.soloFavoritos = false;
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
  if (ev.key !== "Escape") return;
  if ($("#filtros").classList.contains("abierto")) abrirFiltros(false);
  else if (!$("#panel").hidden) cerrarPanel();
});

/* ---------- Ideas ---------- */

const ETIQUETA_TIPO = {
  mcp: ["servidor MCP", "servidores MCP"], skill: ["skill", "skills"], programa: ["programa", "programas"],
};
const PETICION_IDEAS = `Con esta información, respóndeme en español sencillo:
1. Qué cubren ya estos programas y en qué se parecen.
2. Qué huecos ves: qué falta o qué nadie hace bien todavía.
3. Cinco ideas concretas de programas que yo podría crear. De cada una dime: para qué sirve, a quién ayuda, de cuál de los anteriores podría partir o con cuáles combinarla, y por dónde empezar.
4. Cuál de las cinco empezarías primero y por qué.`;

const cuenta = (n, tipo) => `${numero(n)} ${ETIQUETA_TIPO[tipo][n === 1 ? 0 : 1]}`;

/* Un hueco: hay mucho de un tipo y, en proporción, poco de otro (calculado en ideas.py). */
function textoHueco(h) {
  const otros = ["mcp", "skill", "programa"].filter((t) => t !== h.falta && h.n[t] > 0);
  const hay = otros.map((t) => cuenta(h.n[t], t)).join(" y ");
  const pocos = h.n[h.falta] === 0 ? `ningún ${ETIQUETA_TIPO[h.falta][0]}` : `solo ${cuenta(h.n[h.falta], h.falta)}`;
  return `${hay}, pero ${pocos}`;
}

function ideaHueco(h) {
  return h.falta === "mcp"
    ? `Idea: crear un servidor MCP de «${h.tema}».`
    : `Idea: crear una skill de «${h.tema}».`;
}

function itemHueco(h) {
  return `<li><span class="tema">${esc(h.tema)}</span>: ${esc(textoHueco(h))}.
    <span class="idea">${esc(ideaHueco(h))}
    <button type="button" class="enlace" data-ver-tema="${esc(h.tema)}">Ver repos</button></span></li>`;
}

function itemRepoIdea(r) {
  const d = (r.d || "").length > 110 ? r.d.slice(0, 107) + "…" : (r.d || "");
  return `<li><a href="https://github.com/${esc(r.n)}" target="_blank" rel="noopener">${esc(r.n)}</a> ★ ${numero(r.s)}${d ? ` — ${esc(d)}` : ""}</li>`;
}

function tarjetaDominio(clave, d) {
  const pct = d.total ? Math.round(100 * d.libres / d.total) : 0;
  const lista = (repos, vacio) => repos.length
    ? `<ol>${repos.map(itemRepoIdea).join("")}</ol>` : `<p class="vacio-corto">${vacio}</p>`;
  return `<article class="idea-dominio">
    <h3>${esc(DOMINIOS[clave])}</h3>
    <p class="cifras">${numero(d.total)} repos: ${cuenta(d.tipos.mcp, "mcp")} · ${cuenta(d.tipos.skill, "skill")} · ${cuenta(d.tipos.programa, "programa")}.
      ${pct} % de uso libre · ${numero(d.verdes)} en verde.</p>
    <h4>Más destacados</h4>${lista(d.mejores, "Ninguno.")}
    <h4>Novedades del mes</h4>${lista(d.nuevos, "Ninguna este mes.")}
    <h4>Huecos</h4>${d.huecos.length ? `<ul class="lista-huecos">${d.huecos.map(itemHueco).join("")}</ul>`
      : '<p class="vacio-corto">No se ha detectado ninguno.</p>'}
    <div class="acciones">
      <button type="button" class="boton" data-ideas-dominio="${clave}">Pedir ideas a Claude sobre este dominio</button>
      <button type="button" class="enlace" data-ver-dominio="${clave}">Ver todos en el catálogo</button>
    </div>
  </article>`;
}

let ideasDatos = null;

async function cargarIdeas() {
  const cont = $("#ideas-contenido");
  if (ideasDatos) return;
  cont.innerHTML = '<p class="vacio-corto">Cargando…</p>';
  try {
    const resp = await fetch("ideas.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    ideasDatos = await resp.json();
  } catch (err) {
    cont.innerHTML = `<p class="vacio">No se ha podido cargar el panorama de ideas (${esc(err.message)}). Vuelve a abrir esta pestaña para reintentarlo.</p>`;
    return;
  }
  const falta = (tipo) => ideasDatos.huecos.filter((h) => h.falta === tipo);
  const cruces = ideasDatos.combinaciones.map((c) =>
    `<li>${c.dominios.map((d) => esc(DOMINIOS[d])).join(" + ")}: <strong>${numero(c.total)}</strong> ${c.total === 1 ? "repo" : "repos"}</li>`).join("");
  cont.innerHTML = `
    <p class="ideas-intro">Panorama para buscar ideas de programas: qué hay en cada dominio y dónde faltan cosas.
      Son <strong>solo cuentas sobre el catálogo</strong> (se recalculan cada mes), no una opinión de ninguna IA.
      Un «hueco» es un tema con mucho de un tipo y poco de otro, y cada uno es una posible idea: crear lo que falta.
      Para ideas más elaboradas, usa «Ideas con Claude» en cualquier búsqueda del catálogo.</p>

    <h2>Qué falta: huecos entre tipos</h2>
    <div class="huecos-grupos">
      <div><p>Hay skills o programas, pero pocos servidores MCP</p>
        <ul class="lista-huecos">${falta("mcp").map(itemHueco).join("")}</ul></div>
      <div><p>Hay servidores MCP o programas, pero pocas skills</p>
        <ul class="lista-huecos">${falta("skill").map(itemHueco).join("")}</ul></div>
    </div>

    <h2>Por dominio</h2>
    <div class="tarjetas-dominio">${Object.entries(ideasDatos.dominios).map(([c, d]) => tarjetaDominio(c, d)).join("")}</div>

    <h2>Cruces entre dominios</h2>
    <p class="ideas-intro">Cuántos repos tocan dos dominios a la vez. Los números más bajos son terreno poco explorado.</p>
    <ul class="cruces">${cruces}</ul>`;
}

/* Del panorama al catálogo: se cambia la dirección y lo demás lo hace «hashchange». */
function irAlCatalogo(parametros) {
  location.hash = new URLSearchParams(parametros).toString();
}

$("#ideas-contenido").addEventListener("click", (ev) => {
  const tema = ev.target.closest("[data-ver-tema]");
  if (tema) return irAlCatalogo({ q: tema.dataset.verTema });
  const dominio = ev.target.closest("[data-ver-dominio]");
  if (dominio) return irAlCatalogo({ dominio: dominio.dataset.verDominio });
  const pedir = ev.target.closest("[data-ideas-dominio]");
  if (pedir) copiarParaClaude(promptDominio(pedir.dataset.ideasDominio));
});

/* ---------- Ideas con Claude: texto para pegar en Claude ---------- */

function lineaRepo(r) {
  const tipos = r.t.map((t) => TIPOS[t] || t).join("/");
  const desc = (r.d || "sin descripción").replace(/\s+/g, " ");
  return `- ${r.n} (★ ${numero(r.s)}, ${tipos}, ${r.l ? "licencia " + r.l : "sin licencia"}, semáforo ${SEMAFORO[r.sm]}): ${desc.length > 160 ? desc.slice(0, 157) + "…" : desc}`;
}

function describirBusqueda() {
  const partes = [];
  if (estado.texto) partes.push(`texto «${estado.texto}»`);
  const f = estado.filtros;
  if (f.tipo.size) partes.push("tipo: " + [...f.tipo].map((t) => TIPOS[t] || t).join(" o "));
  if (f.dominio.size) partes.push("dominio: " + [...f.dominio].map((d) => DOMINIOS[d] || d).join(" o "));
  if (f.semaforo.size) partes.push("semáforo: " + [...f.semaforo].map((v) => SEMAFORO[v]).join(" o "));
  if (estado.licencia) partes.push("licencia: " + LICENCIAS[estado.licencia]);
  if (estado.estrellas) partes.push(`al menos ${numero(estado.estrellas)} estrellas`);
  if (estado.actividad) partes.push(`con actividad en los últimos ${estado.actividad} días`);
  if (estado.pestana === "novedades") partes.push("solo novedades del último mes");
  if (estado.pestana === "skills") partes.push("solo skills");
  if (estado.soloFavoritos) partes.push("solo mis favoritos");
  return partes.join("; ");
}

function promptBusqueda() {
  const lista = estado.resultado.slice(0, 25);
  const de = (t) => estado.resultado.filter((r) => r.t.includes(t)).length;
  const criterio = describirBusqueda();
  return `Estoy buscando ideas para crear programas. He consultado un catálogo de GitHub de servidores MCP, skills de Claude y programas${criterio ? `, con esta búsqueda: ${criterio}` : ""}.

Resultados: ${numero(estado.resultado.length)} repos (${numero(de("mcp"))} servidores MCP, ${numero(de("skill"))} skills, ${numero(de("programa"))} programas). Estos son los ${lista.length} primeros:

${lista.map(lineaRepo).join("\n")}

${PETICION_IDEAS}`;
}

function promptDominio(clave) {
  const d = ideasDatos.dominios[clave];
  const lista = estado.datos.repos.filter((r) => r.m.includes(clave)).sort((a, b) => b.s - a.s).slice(0, 25);
  const huecos = d.huecos.map((h) => `- ${h.tema}: ${textoHueco(h)}.`).join("\n");
  return `Estoy buscando ideas para crear programas en el dominio «${DOMINIOS[clave]}». He consultado un catálogo de GitHub de servidores MCP, skills de Claude y programas.

En este dominio hay ${numero(d.total)} repos (${cuenta(d.tipos.mcp, "mcp")}, ${cuenta(d.tipos.skill, "skill")}, ${cuenta(d.tipos.programa, "programa")}). Estos son los ${lista.length} más populares:

${lista.map(lineaRepo).join("\n")}
${huecos ? `\nHuecos detectados automáticamente (temas con muchos repos de un tipo y pocos de otro):\n${huecos}\n` : ""}
${PETICION_IDEAS}`;
}

async function copiarTexto(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch { /* sin permiso o sin HTTPS: se prueba el método antiguo */ }
  const caja = document.createElement("textarea");
  caja.value = texto;
  caja.style.cssText = "position:fixed;opacity:0;top:0;left:0";
  document.body.appendChild(caja);
  caja.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { /* se ignora */ }
  caja.remove();
  return ok;
}

let temporizadorAviso;
function mostrarAviso(html, ms = 10000) {
  const aviso = $("#toast");
  aviso.innerHTML = html;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, ms);
}

async function copiarParaClaude(texto) {
  if (await copiarTexto(texto)) {
    mostrarAviso('Copiado. Pégalo en Claude para recibir las ideas. <a href="https://claude.ai/new" target="_blank" rel="noopener">Abrir Claude</a>');
  } else {
    window.prompt("No se ha podido copiar solo. Copia este texto (Ctrl+C) y pégalo en Claude:", texto);
  }
}

$("#ideas-claude").addEventListener("click", () => {
  if (!estado.resultado.length) {
    mostrarAviso("No hay resultados: cambia la búsqueda o quita filtros para pedir ideas.", 5000);
    return;
  }
  copiarParaClaude(promptBusqueda());
});

cargar();
