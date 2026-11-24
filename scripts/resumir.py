"""Resúmenes automáticos (sin IA) de los repos más populares, a partir de su README.

Para cada repo con >= 50 estrellas baja su README (y el SKILL.md si es una skill) y
extrae, con reglas sencillas, lo que el panel lateral de la web enseña:

- q: «para qué sirve»: el primer párrafo de texto del README (sin insignias ni enlaces).
- c: características: las viñetas de la sección «Features», «Highlights», «Tools»…
- u: cómo usarlo: los comandos de instalación de la sección «Install» / «Usage».
- r: rendimiento: frases del README que dan cifras («2x faster», «reduces tokens 40 %»).
     Es lo que AFIRMA el README, no algo comprobado; si no hay cifras, no se inventa nada.
- k: skills: el campo «description» del SKILL.md («cuándo usarla»).

Lo que no esté en español (inglés, chino…) se traduce con los mismos modelos de Argos
que las descripciones. El resultado se guarda en data/cache_resumenes.json (un repo por
línea) y generar_web.py lo mete en los ficheros de detalle de la web.

No hay IA ni claves: son reglas, así que a veces el párrafo elegido no es el ideal. Si
no se encuentra nada fiable, el campo se deja vacío en vez de poner algo dudoso.

Cada ejecución procesa primero los repos más populares y se detiene al llegar a
--max-minutos o --max-repos; lo que quede se hace en la siguiente (la primera vez son
unos 11.700 repos, repartidos en 2-3 ejecuciones). Solo se vuelve a bajar el README de
un repo si han pasado 90 días desde la última vez y ha habido cambios en el repo.

Uso:
    python scripts/resumir.py                       # necesita GITHUB_TOKEN
    python scripts/resumir.py --max-repos 20 --sin-traducir
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from comun import RAIZ, _gql, guardar_por_lineas, peticion, preparar_consola, sesion_github, token_github
from traducir import RE_EMOJI, Traductor, detectar_idioma

CATALOGO = RAIZ / "data" / "catalogo.json"
CACHE = RAIZ / "data" / "cache_resumenes.json"
MIN_ESTRELLAS = 50
LOTE = 20                    # repos por consulta GraphQL
DIAS_REVISION = 90           # cada cuánto se vuelve a mirar un README
MAX_INTRO = 320              # caracteres del «para qué sirve»
MIN_INTRO = 90               # se añaden frases hasta llegar a esto
MAX_VINETA = 150
MAX_VINETAS = 5
MAX_FRASE_RENDIMIENTO = 200
MAX_SEGMENTO_TRADUCIR = 400
NOMBRES_README = ("README.md", "readme.md", "README", "README.rst", "Readme.md")

# ---------------------------------------------------------------- limpieza de Markdown

RE_COMENTARIO = re.compile(r"<!--.*?-->", re.S)
RE_IMG_ENLAZADA = re.compile(
    r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|\[!\[[^\]]*\]\[[^\]]*\]\]\([^)]*\)"
    r"|\[!\[[^\]]*\]\([^)]*\)\]\[[^\]]*\]|\[!\[[^\]]*\]\[[^\]]*\]\]\[[^\]]*\]")
RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)|!\[[^\]]*\]\[[^\]]*\]")
RE_HTML = re.compile(r"<[^>\n]{1,300}>")
RE_ENLACE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
RE_ENLACE_REF = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
RE_URL = re.compile(r"https?://\S+")
RE_NEGRITA = re.compile(r"(\*\*|__)(.+?)\1")
RE_CURSIVA = re.compile(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])")
RE_ALERTA = re.compile(r"^\s*>?\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.I)
RE_ENCABEZADO = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
RE_VINETA = re.compile(r"^(\s*)([-*+]|\d{1,2}[.)])\s+(.*)$")
RE_VALLA = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")

RE_TITULO_CARACT = re.compile(
    r"\b(features?|key features|main features|highlights?|capabilit(?:y|ies)|"
    r"what(?:'s| is)? (?:included|inside|it does)|what you get|why\b|"
    r"functionality)\b|主要功能|功能特点|功能|特性|特点|亮点", re.I)
# «Tools» solo vale como título entero (así no entra «Tool limitations»).
RE_TITULO_HERRAMIENTAS = re.compile(r"^(?:available |supported |mcp |list of )?tools(?: list)?$", re.I)
RE_TITULO_USO = re.compile(
    r"\b(install(?:ation)?|getting started|quick ?start|usage|how to use|set ?up)\b|安装|快速开始|使用|用法", re.I)
RE_TITULO_RUIDO = re.compile(
    r"\b(licen[cs]e|contribut\w*|acknowledg\w*|sponsor\w*|star history|table of contents|contents|"
    r"changelog|credits|support|donat\w*|funding|security|roadmap|faq|stars?|badges?|"
    r"requirements|prerequisites|development|testing|contact)\b|目录|许可|贡献|赞助", re.I)
RE_RUIDO_PARRAFO = re.compile(
    r"(?i)^(table of contents|contents|built with|secured by|made with|powered by|"
    r"copyright|licensed under|released under|this project is licensed|"
    r"star us|give (it )?a star|if you (like|find)|please (star|note)|disclaimer|"
    r"warning|note:|important\b|beware|caution|security (notice|advisory)|official sources?|"
    r"\W*click|\W*see (the )?(docs|documentation)|translations?:|"
    r"read this in|\W*english\b.*\|)")
# Palabras que quedan colgando al final cuando se quita un enlace («…el panel en»).
RE_COLA = re.compile(r"[\s,;:(-]+(at|on|in|from|to|via|see|visit|with|and|or|the)?[\s:]*$", re.I)
RE_COMANDO = re.compile(
    r"^(npx|npm|pnpm|yarn|bunx?|pip3?|pipx|uvx?|uv|python3?|docker|git|brew|cargo|go|curl|claude|"
    r"gemini|codex|dotnet|gem|apt|winget|scoop|conda|poetry|deno|irm|iwr)\b")
RE_INSTALA = re.compile(r"\b(install|add|npx|uvx|pipx?|docker (run|pull)|mcp add|clone|brew|cargo|go install)\b", re.I)
LENGUAJES_SHELL = {"", "bash", "sh", "shell", "console", "zsh", "terminal", "text", "powershell", "cmd", "bat"}

RE_CIFRAS = re.compile(
    r"(\b\d+(?:[.,]\d+)?\s?(?:x|×)\s+(?:faster|quicker|smaller|fewer|cheaper|lighter|less|more|speed)\b)"
    r"|(\b(?:up to |over |about |~)?\d{1,3}(?:[.,]\d+)?\s?%\s+(?:faster|less|fewer|lower|smaller|reduction|savings?|cheaper|improvement|token|cost|latency)\b)"
    r"|(\b(?:reduces?|reduced|saves?|saving|cuts?|speeds? up|lowers?|decreases?)\b[^.]{0,70}\d+(?:[.,]\d+)?\s?(?:%|x|×|ms|tokens?|seconds?|minutes?)\b)"
    r"|(\bfaster than\b)|(\b(?:latency|throughput|benchmarks?|tokens?/s|fps)\b[^.]{0,50}\d)"
    r"|([提降减节省缩短减少][^。]{0,15}\d+\s?(?:%|倍|ms|秒))", re.I)


def limpiar_linea(s: str) -> str:
    s = RE_IMG_ENLAZADA.sub("", s)
    s = RE_IMG.sub("", s)
    s = RE_HTML.sub(" ", s)
    s = html.unescape(s)                         # &middot; &amp; &nbsp;…
    s = RE_ENLACE.sub(r"\1", s)
    s = RE_ENLACE_REF.sub(r"\1", s)
    s = RE_URL.sub("", s)
    s = s.replace("`", "")
    s = RE_NEGRITA.sub(r"\2", s)
    s = RE_CURSIVA.sub(r"\1", s)
    s = RE_EMOJI.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" \t>")


def partir_en_secciones(md: str) -> list[dict]:
    """README -> lista de secciones {titulo, parrafos, vinetas, codigos}."""
    md = RE_COMENTARIO.sub("", md[:250_000])
    secciones = [{"titulo": "", "parrafos": [], "vinetas": [], "codigos": []}]
    parrafo: list[str] = []
    codigo: list[str] | None = None
    lenguaje = ""
    ultima_vineta_indent = None

    def cerrar_parrafo() -> None:
        if parrafo:
            secciones[-1]["parrafos"].append(" ".join(parrafo))
            parrafo.clear()

    for linea in md.splitlines():
        valla = RE_VALLA.match(linea)
        if valla:
            if codigo is None:
                cerrar_parrafo()
                codigo, lenguaje = [], valla.group(2).lower()
            else:
                secciones[-1]["codigos"].append((lenguaje, codigo))
                codigo = None
            continue
        if codigo is not None:
            codigo.append(linea)
            continue
        encabezado = RE_ENCABEZADO.match(linea)
        if encabezado:
            cerrar_parrafo()
            secciones.append({"titulo": limpiar_linea(encabezado.group(2)),
                              "parrafos": [], "vinetas": [], "codigos": []})
            ultima_vineta_indent = None
            continue
        if not linea.strip():
            cerrar_parrafo()
            ultima_vineta_indent = None if ultima_vineta_indent is None else ultima_vineta_indent
            continue
        if linea.lstrip().startswith("|") or RE_ALERTA.match(linea):
            cerrar_parrafo()
            continue
        vineta = RE_VINETA.match(linea)
        if vineta:
            cerrar_parrafo()
            texto = limpiar_linea(vineta.group(3))
            secciones[-1]["vinetas"].append(texto)
            ultima_vineta_indent = len(vineta.group(1))
            continue
        # línea sangrada que continúa una viñeta
        if ultima_vineta_indent is not None and linea.startswith(" ") and secciones[-1]["vinetas"]:
            secciones[-1]["vinetas"][-1] = (secciones[-1]["vinetas"][-1] + " " + limpiar_linea(linea)).strip()
            continue
        texto = limpiar_linea(linea)
        if texto:
            parrafo.append(texto)
        else:
            cerrar_parrafo()
    cerrar_parrafo()
    return secciones


def frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", texto) if f.strip()]


def recortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    punto = max(corte.rfind(". "), corte.rfind("。"), corte.rfind("! "), corte.rfind("? "))
    if punto > limite * 0.5:
        return corte[:punto + 1]
    espacio = corte.rfind(" ")
    return (corte[:espacio] if espacio > limite * 0.5 else corte).rstrip(" ,;:-—") + "…"


def es_prosa(p: str) -> bool:
    """¿Es un párrafo de texto de verdad (y no una lista de enlaces, un aviso, un título…)?"""
    if len(p) < 50 or RE_RUIDO_PARRAFO.match(p) or p[0] in "\"“”«‘'":     # sin citas decorativas
        return False
    if p.count("·") >= 2 or p.count("|") >= 2 or p.count(" - ") >= 3:
        return False
    letras = sum(c.isalpha() for c in p)
    if letras < len(p) * 0.6:
        return False
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿가-힯]", p))
    return len(p.split()) >= 8 or cjk >= 20


def extraer_intro(secciones: list[dict]) -> str | None:
    for s in secciones[:5]:
        if s["titulo"] and (RE_TITULO_USO.search(s["titulo"]) or RE_TITULO_CARACT.search(s["titulo"])
                            or RE_TITULO_HERRAMIENTAS.match(s["titulo"].strip())
                            or RE_TITULO_RUIDO.search(s["titulo"])):
            continue
        for p in s["parrafos"]:
            if es_prosa(p):
                elegidas, total = [], 0
                for f in frases(p):
                    if elegidas and total + len(f) > MAX_INTRO:
                        break
                    elegidas.append(f)
                    total += len(f) + 1
                    if total >= MIN_INTRO or len(elegidas) == 3:     # sin frases sueltas de 3 palabras
                        break
                texto = RE_COLA.sub("", recortar(" ".join(elegidas), MAX_INTRO)).strip()
                return texto or None
    return None


def limpiar_vineta(v: str) -> str | None:
    v = re.sub(r"^\W+", "", v)                       # signos y emoji al principio
    v = re.sub(r"^([^:.—-]{2,40})[.:]\s+", r"\1: ", v)  # «Término. Explicación» -> «Término: Explicación»
    if len(v) < 12 or sum(c.isalpha() for c in v) < len(v) * 0.5:
        return None
    return recortar(v, MAX_VINETA)


def extraer_caracteristicas(secciones: list[dict]) -> list[str]:
    for s in secciones:
        es_titulo = s["titulo"] and (RE_TITULO_CARACT.search(s["titulo"])
                                     or RE_TITULO_HERRAMIENTAS.match(s["titulo"].strip()))
        if es_titulo and not RE_TITULO_RUIDO.search(s["titulo"]):
            vinetas = [x for x in (limpiar_vineta(v) for v in s["vinetas"]) if x]
            if len(vinetas) >= 2:
                return vinetas[:MAX_VINETAS]
    return []


def extraer_uso(secciones: list[dict]) -> list[str]:
    comandos: list[str] = []
    for s in secciones:
        if not (s["titulo"] and RE_TITULO_USO.search(s["titulo"])):
            continue
        for lenguaje, lineas in s["codigos"]:
            if lenguaje not in LENGUAJES_SHELL:
                continue
            for linea in lineas:
                c = re.sub(r"^\s*(\$|>|PS>|#!)\s*", "", linea).strip()
                c = re.sub(r"\s+#\s.*$", "", c)         # comentario al final de la línea
                if not c or c.startswith("#") or not RE_COMANDO.match(c) or len(c) > 110:
                    continue
                if RE_INSTALA.search(c) and c not in comandos:
                    comandos.append(c)
                if len(comandos) == 2:
                    return comandos
    return comandos


def extraer_rendimiento(secciones: list[dict]) -> list[str]:
    encontradas: list[str] = []
    for s in secciones:
        if s["titulo"] and RE_TITULO_RUIDO.search(s["titulo"]):
            continue
        for texto in s["parrafos"] + s["vinetas"]:
            for f in frases(texto):
                if 25 <= len(f) <= 400 and RE_CIFRAS.search(f) and f not in encontradas:
                    encontradas.append(recortar(f, MAX_FRASE_RENDIMIENTO))
                    if len(encontradas) == 2:
                        return encontradas
    return encontradas


def descripcion_skill(md: str) -> str | None:
    """Campo «description» del encabezado YAML de un SKILL.md."""
    m = re.match(r"\s*---\s*\n(.*?)\n---", md, re.S)
    if not m:
        return None
    d = re.search(r"(?m)^description:\s*(.*(?:\n[ \t]+.*)*)", m.group(1))
    if not d:
        return None
    texto = re.sub(r"\s+", " ", d.group(1)).strip()
    texto = re.sub(r"^[>|][+-]?\s*", "", texto).strip().strip("'\"")
    texto = limpiar_linea(texto)
    return recortar(texto, MAX_INTRO + 80) if len(texto) >= 20 else None


def parecidos(a: str, b: str) -> bool:
    """¿Dicen casi lo mismo? (para no repetir la descripción de GitHub en el resumen)."""
    a, b = (re.sub(r"[\W_]+", "", x.lower()) for x in (a, b))
    if not a or not b:
        return False
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() > 0.75


def analizar(readme: str | None, skill_md: str | None, descripcion: str | None = None) -> dict:
    """README (+ SKILL.md) -> campos del resumen, todavía en el idioma original."""
    res: dict = {}
    if readme:
        secciones = partir_en_secciones(readme)
        intro = extraer_intro(secciones)
        if intro and descripcion and parecidos(intro, descripcion):
            intro = None                      # ya se enseña la descripción de GitHub
        for clave, valor in (("q", intro), ("c", extraer_caracteristicas(secciones)),
                             ("u", extraer_uso(secciones)), ("r", extraer_rendimiento(secciones))):
            if valor:
                res[clave] = valor
    if skill_md:
        k = descripcion_skill(skill_md)
        if k:
            res["k"] = k
    return res


# ---------------------------------------------------------------- descarga (GraphQL)

FRAGMENTO = "fragment B on Blob { text isTruncated }"


def consulta_readmes(grupo: list[dict]) -> str:
    partes = []
    for i, r in enumerate(grupo):
        owner, nombre = r["nombre"].split("/", 1)
        objetos = " ".join(f'{chr(97 + j)}: object(expression: "HEAD:{n}") {{ ...B }}'
                           for j, n in enumerate(NOMBRES_README))
        if "skill" in r.get("tipos", []):
            objetos += ' s: object(expression: "HEAD:SKILL.md") { ...B }'
        partes.append(f"r{i}: repository(owner: {_gql(owner)}, name: {_gql(nombre)}) {{ {objetos} }}")
    return "query {\n" + "\n".join(partes) + "\n}\n" + FRAGMENTO


def bajar_lote(sesion, grupo: list[dict]) -> dict[str, tuple[str | None, str | None]]:
    """Devuelve {repo en minúsculas: (readme, skill_md)}. Vacío si falla tras reintentos."""
    for intento in range(1, 4):
        try:
            resp = peticion(sesion, "POST", "https://api.github.com/graphql",
                            json={"query": consulta_readmes(grupo)})
        except Exception as err:      # red caída, etc.: se reintenta
            print(f"  [aviso] lote fallido ({type(err).__name__}): reintento {intento}/3", file=sys.stderr)
            time.sleep(15 * intento)
            continue
        cuerpo = resp.json() if resp is not None else {}
        datos = cuerpo.get("data")
        graves = [e for e in cuerpo.get("errors") or []
                  if e.get("type") not in ("NOT_FOUND", "FORBIDDEN")]
        if datos is None or graves:
            print(f"  [aviso] lote sin datos fiables: reintento {intento}/3", file=sys.stderr)
            time.sleep(15 * intento)
            continue
        salida = {}
        for i, r in enumerate(grupo):
            nodo = datos.get(f"r{i}") or {}
            readme = next(((nodo.get(chr(97 + j)) or {}).get("text") for j in range(len(NOMBRES_README))
                           if (nodo.get(chr(97 + j)) or {}).get("text")), None)
            skill = (nodo.get("s") or {}).get("text")
            salida[r["nombre"].lower()] = (readme, skill)
        return salida
    return {}


# ---------------------------------------------------------------- traducción

CAMPOS_TEXTO = ("q", "k")          # texto suelto
CAMPOS_LISTA = ("c", "r")          # listas de frases (u son comandos: no se traducen)


def traducir_resumenes(traductor: Traductor, resumenes: list[dict]) -> None:
    """Traduce al español, en el sitio, los textos de los resúmenes dados."""
    pendientes: dict[str, list[tuple[dict, str, int | None, str]]] = {}
    for res in resumenes:
        segmentos = [(c, None, res[c]) for c in CAMPOS_TEXTO if c in res]
        segmentos += [(c, i, t) for c in CAMPOS_LISTA for i, t in enumerate(res.get(c, []))]
        for campo, indice, texto in segmentos:
            idioma = detectar_idioma(texto)
            if idioma == "en" or idioma in ("zh", "ru", "ja"):
                limpio = re.sub(r"\s+", " ", RE_EMOJI.sub(" ", texto)).strip()[:MAX_SEGMENTO_TRADUCIR]
                pendientes.setdefault(idioma, []).append((res, campo, indice, limpio or texto))
    for idioma, items in pendientes.items():
        traducciones = traductor.traducir([t for *_, t in items], idioma)
        for (res, campo, indice, _), traduccion in zip(items, traducciones):
            if indice is None:
                if campo == "q":
                    res["qo"] = res[campo]       # el original, por si la traducción automática falla
                res[campo] = traduccion
            else:
                res[campo][indice] = traduccion


# ---------------------------------------------------------------- principal

def huella(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]


def fecha_corta(valor: str | None) -> str:
    return (valor or "")[:10]


def necesita_resumen(repo: dict, cache: dict, hoy: date) -> bool:
    entrada = cache.get(repo["nombre"].lower())
    if entrada is None:
        return True
    if fecha_corta(repo.get("ultimo_push")) <= entrada.get("p", ""):
        return False                      # sin cambios desde la última vez
    return (hoy - date.fromisoformat(entrada["f"])).days >= DIAS_REVISION


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-minutos", type=float, default=None)
    parser.add_argument("--max-repos", type=int, default=None)
    parser.add_argument("--min-estrellas", type=int, default=MIN_ESTRELLAS)
    parser.add_argument("--sin-traducir", action="store_true", help="para pruebas rápidas")
    parser.add_argument("--catalogo", type=Path, default=CATALOGO)
    parser.add_argument("--cache", type=Path, default=CACHE)
    args = parser.parse_args()

    token = token_github()
    if not token:
        print("[aviso] Sin GITHUB_TOKEN no se bajan README (GraphQL lo exige). No se hace nada.")
        return
    hoy = datetime.now(timezone.utc).date()
    datos = json.loads(args.catalogo.read_text(encoding="utf-8"))
    cache: dict = (json.loads(args.cache.read_text(encoding="utf-8"))["repos"]
                   if args.cache.exists() else {})
    candidatos = sorted((r for r in datos["repos"]
                         if r["estrellas"] >= args.min_estrellas and "lista" not in r["tipos"]),
                        key=lambda r: -r["estrellas"])
    # El caché solo guarda repos que siguen en el catálogo y cumplen el mínimo.
    vigentes = {r["nombre"].lower() for r in candidatos}
    cache = {k: v for k, v in cache.items() if k in vigentes}
    pendientes = [r for r in candidatos if necesita_resumen(r, cache, hoy)]
    if args.max_repos:
        pendientes = pendientes[:args.max_repos]
    print(f"Candidatos (≥{args.min_estrellas}★): {len(candidatos)} · con resumen: {len(cache)} · "
          f"por hacer en esta ejecución: {len(pendientes)}")

    sesion = sesion_github(token)
    traductor = None if args.sin_traducir else Traductor()
    inicio = time.time()
    hechos = sin_cambios = vacios = 0
    for i in range(0, len(pendientes), LOTE):
        if args.max_minutos and time.time() - inicio > args.max_minutos * 60:
            print(f"[tope de tiempo] quedan {len(pendientes) - i} repos para la próxima ejecución")
            break
        grupo = pendientes[i:i + LOTE]
        bajados = bajar_lote(sesion, grupo)
        nuevos = []
        for r in grupo:
            clave = r["nombre"].lower()
            if clave not in bajados:
                continue                   # el lote falló: se reintentará la próxima vez
            readme, skill = bajados[clave]
            h = huella((readme or "") + "\0" + (skill or ""))
            anterior = cache.get(clave)
            if anterior and anterior.get("h") == h:
                anterior["p"], anterior["f"] = fecha_corta(r.get("ultimo_push")), hoy.isoformat()
                sin_cambios += 1
                continue
            res = analizar(readme, skill, r.get("descripcion"))
            entrada = {"h": h, "p": fecha_corta(r.get("ultimo_push")), "f": hoy.isoformat(), **res}
            if not res:
                vacios += 1
            cache[clave] = entrada
            nuevos.append(entrada)
        if traductor and nuevos:
            traducir_resumenes(traductor, nuevos)
        hechos += len(nuevos)
        if (i // LOTE) % 10 == 9:
            guardar_por_lineas(args.cache, {"generado": hoy.isoformat(), "repos": cache}, "repos")
            print(f"  {i + len(grupo)}/{len(pendientes)} repos · {(time.time() - inicio) / 60:.1f} min")
    guardar_por_lineas(args.cache, {"generado": hoy.isoformat(), "repos": cache}, "repos")
    print(f"\nResúmenes nuevos: {hechos} (sin nada útil: {vacios}) · sin cambios: {sin_cambios} · "
          f"total en caché: {len(cache)} · {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
