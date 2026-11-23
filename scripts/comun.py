"""Utilidades compartidas por los scripts de recopilación."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
DATOS_RAW = RAIZ / "data" / "raw"

DIAS_INACTIVO = 182
MIN_ESTRELLAS_INACTIVO = 20
MAX_REINTENTOS = 5

# Enlaces de github.com que no son repositorios.
NO_SON_REPOS = {
    "about", "account", "apps", "assets", "codespaces", "collections", "contact",
    "customer-stories", "dashboard", "enterprise", "explore", "features", "join",
    "login", "marketplace", "new", "notifications", "orgs", "pricing", "readme",
    "search", "security", "settings", "signup", "site", "sponsors", "topics",
    "trending", "user-attachments", "users",
}
RE_REPO_GITHUB = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/([A-Za-z0-9._-]+)"
)


def preparar_consola() -> None:
    """La consola de Windows no usa UTF-8 por defecto: evita tildes rotas."""
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", line_buffering=True)


def token_github() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or None


def sesion_github(token: str | None) -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "catalogo-github-script",
    })
    if token:
        sesion.headers["Authorization"] = f"Bearer {token}"
    return sesion


def segundos_espera(resp: requests.Response, intento: int) -> int:
    if "Retry-After" in resp.headers:
        return int(resp.headers["Retry-After"]) + 1
    if resp.headers.get("X-RateLimit-Remaining") == "0" and "X-RateLimit-Reset" in resp.headers:
        return max(int(resp.headers["X-RateLimit-Reset"]) - int(time.time()), 0) + 2
    return 30 * intento


def pausa_si_agotado(resp: requests.Response) -> None:
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
        espera = max(reset - int(time.time()), 0) + 2
        print(f"  [límite] cupo agotado: espero {espera} s", file=sys.stderr)
        time.sleep(espera)


def es_limite(resp: requests.Response) -> bool:
    """¿Es un rechazo por límite de velocidad (y no por falta de permisos)?"""
    if resp.status_code == 429:
        return True
    return resp.status_code == 403 and (
        resp.headers.get("X-RateLimit-Remaining") == "0"
        or "Retry-After" in resp.headers
        or "rate limit" in resp.text.lower())


def peticion(sesion: requests.Session, metodo: str, url: str, **kwargs) -> requests.Response | None:
    """GET/POST con reintentos ante límites de velocidad y errores 5xx.

    Devuelve None si el recurso no existe o no es accesible (404, 410, 422, 451 o
    403 que no sea por límite de velocidad, p. ej. un repo bloqueado).
    """
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = sesion.request(metodo, url, timeout=60, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as err:
            print(f"  [red] {type(err).__name__}: reintento {intento}/{MAX_REINTENTOS}",
                  file=sys.stderr)
            time.sleep(10 * intento)
            continue
        if resp.status_code == 200:
            pausa_si_agotado(resp)
            return resp
        if resp.status_code in (404, 410, 422, 451):
            return None
        if es_limite(resp):
            espera = segundos_espera(resp, intento)
            print(f"  [límite] {resp.status_code}: espero {espera} s "
                  f"(intento {intento}/{MAX_REINTENTOS})", file=sys.stderr)
            time.sleep(espera)
            continue
        if resp.status_code == 403:
            return None
        if resp.status_code >= 500:
            time.sleep(5 * intento)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Sin respuesta válida tras {MAX_REINTENTOS} intentos: {url}")


RE_SKILL_NOMBRE = re.compile(r"(^|[-_.])skills?([-_.]|$)")
RE_SKILL_TOPIC = re.compile(r"(^|-)skills?(-|$)")


def parece_skill(repo: dict) -> bool:
    """¿El nombre o los topics del repo indican que es una skill?"""
    nombre = repo["nombre"].split("/", 1)[-1].lower()
    return bool(RE_SKILL_NOMBRE.search(nombre)
                or any(RE_SKILL_TOPIC.search(t.lower()) for t in repo.get("topics", [])))


def guardar_por_lineas(ruta: Path, datos: dict, campo: str) -> None:
    """Guarda un JSON con un elemento de «campo» por línea.

    Para ficheros que se suben a git cada mes: así git solo guarda las líneas que
    cambian y no el fichero entero.
    """
    elementos = datos[campo]
    if isinstance(elementos, dict):
        lineas = [f"{json.dumps(k, ensure_ascii=False)}:"
                  f"{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                  for k, v in sorted(elementos.items())]
        abre, cierra = "{", "}"
    else:
        lineas = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in elementos]
        abre, cierra = "[", "]"
    cabecera = {k: v for k, v in datos.items() if k != campo}
    texto = json.dumps(cabecera, ensure_ascii=False)[:-1]
    texto += (", " if cabecera else "") + f'"{campo}": {abre}\n' + ",\n".join(lineas) + f"\n{cierra}}}\n"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def arreglar_texto(texto: str | None) -> str:
    """Repara textos con codificación doble (p. ej. «â€”» en lugar de «—») y
    entidades HTML sin convertir (p. ej. «&quot;» en lugar de «"»)."""
    if not texto:
        return ""
    if "&" in texto:
        texto = html.unescape(texto)
    if any(marca in texto for marca in ("Ã", "â€", "Â")):
        try:
            return texto.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return texto


def repos_en_texto(texto: str) -> set[str]:
    """Extrae «owner/repo» (en minúsculas) de los enlaces a GitHub de un texto."""
    encontrados = set()
    for owner, nombre in RE_REPO_GITHUB.findall(texto):
        nombre = nombre.removesuffix(".git").rstrip(".")
        if owner.lower() in NO_SON_REPOS or not nombre or nombre.startswith("."):
            continue
        encontrados.add(f"{owner}/{nombre}".lower())
    return encontrados


def repo_desde_rest(item: dict) -> dict:
    licencia = item.get("license") or {}
    return {
        "nombre": item["full_name"],
        "url": item["html_url"],
        "descripcion": arreglar_texto(item.get("description")),
        "topics": item.get("topics", []),
        "estrellas": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "incidencias_abiertas": item.get("open_issues_count", 0),
        "licencia": licencia.get("spdx_id") if licencia else None,
        "propietario": item["owner"]["login"],
        "tipo_propietario": item["owner"]["type"],  # Organization / User
        "lenguaje": item.get("language"),
        "web": item.get("homepage") or None,
        "archivado": item.get("archived", False),
        "creado": item.get("created_at"),
        "ultimo_push": item.get("pushed_at"),
        "actualizado": item.get("updated_at"),
    }


def repo_desde_graphql(nodo: dict) -> dict:
    licencia = nodo.get("licenseInfo") or {}
    lenguaje = nodo.get("primaryLanguage") or {}
    return {
        "nombre": nodo["nameWithOwner"],
        "url": nodo["url"],
        "descripcion": arreglar_texto(nodo.get("description")),
        "topics": [t["topic"]["name"] for t in nodo["repositoryTopics"]["nodes"]],
        "estrellas": nodo["stargazerCount"],
        "forks": nodo["forkCount"],
        "incidencias_abiertas": nodo["issues"]["totalCount"],
        "licencia": licencia.get("spdxId"),
        "propietario": nodo["owner"]["login"],
        "tipo_propietario": nodo["owner"]["__typename"],
        "lenguaje": lenguaje.get("name"),
        "web": nodo.get("homepageUrl") or None,
        "archivado": nodo["isArchived"],
        "creado": nodo["createdAt"],
        "ultimo_push": nodo["pushedAt"],
        "actualizado": nodo["updatedAt"],
    }


CAMPOS_GRAPHQL = """
  nameWithOwner url description stargazerCount forkCount isArchived
  createdAt pushedAt updatedAt homepageUrl
  licenseInfo { spdxId }
  owner { login __typename }
  primaryLanguage { name }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  issues(states: OPEN) { totalCount }
"""


def obtener_repos(nombres: list[str], token: str | None, lote: int = 50,
                  fallidos: set[str] | None = None) -> dict[str, dict]:
    """Datos de una lista de «owner/repo». Clave: el nombre pedido, en minúsculas.

    Con token usa GraphQL (50 repos por petición); sin token, REST de uno en uno
    (solo apto para pruebas: GitHub permite 60 peticiones/hora sin token).
    Si se pasa «fallidos», se añaden los repos que faltan por un error de GitHub
    (no porque no existan), para no darlos por inexistentes.
    """
    sesion = sesion_github(token)
    resultado: dict[str, dict] = {}
    if not token:
        for i, nombre in enumerate(nombres, 1):
            resp = peticion(sesion, "GET", f"https://api.github.com/repos/{nombre}")
            if resp is not None:
                resultado[nombre.lower()] = repo_desde_rest(resp.json())
            if i % 25 == 0:
                print(f"  {i}/{len(nombres)} repos consultados")
        return resultado

    errores: dict[str, int] = {}
    for inicio in range(0, len(nombres), lote):
        grupo = nombres[inicio:inicio + lote]
        datos, completo = _consulta_graphql(sesion, grupo, errores)
        for i, nombre in enumerate(grupo):
            nodo = datos.get(f"r{i}")
            if nodo:
                resultado[nombre.lower()] = repo_desde_graphql(nodo)
            elif not completo and fallidos is not None:
                fallidos.add(nombre.lower())
        hechos = min(inicio + lote, len(nombres))
        if hechos % 1000 < lote or hechos == len(nombres):
            print(f"  {hechos}/{len(nombres)} repos consultados")
    if errores:
        print(f"  Errores de GraphQL por tipo: {errores}")
    return resultado


# Errores de GraphQL que afectan a un repo concreto y no se arreglan reintentando.
ERRORES_PERMANENTES = {"NOT_FOUND", "FORBIDDEN"}


def _consulta_graphql(sesion: requests.Session, grupo: list[str],
                      errores: dict) -> tuple[dict, bool]:
    """Pide un lote de repos por GraphQL. Reintenta si falla algo que no sea «no existe».

    Devuelve los datos y si la respuesta es fiable (False: agotó los reintentos).
    """
    partes = []
    for i, nombre in enumerate(grupo):
        owner, repo = nombre.split("/", 1)
        partes.append(f'r{i}: repository(owner: {_gql(owner)}, name: {_gql(repo)}) {{{CAMPOS_GRAPHQL}}}')
    consulta = "query {\n" + "\n".join(partes) + "\n}"
    for intento in range(1, 4):
        resp = peticion(sesion, "POST", "https://api.github.com/graphql", json={"query": consulta})
        cuerpo = resp.json() if resp is not None else {}
        tipos = [e.get("type", "DESCONOCIDO") for e in cuerpo.get("errors") or []]
        graves = [t for t in tipos if t not in ERRORES_PERMANENTES]
        if cuerpo.get("data") is not None and not graves:
            for t in tipos:
                errores[t] = errores.get(t, 0) + 1
            return cuerpo["data"], True
        print(f"  [GraphQL] lote fallido ({', '.join(sorted(set(graves))) or 'sin datos'}): "
              f"reintento {intento}/3", file=sys.stderr)
        time.sleep(20 * intento)
    for t in graves or ["SIN_DATOS"]:
        errores[t] = errores.get(t, 0) + 1
    return ((cuerpo.get("data") or {}) if cuerpo else {}), False


def _gql(texto: str) -> str:
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def descartar(repo: dict, ahora: datetime | None = None) -> str | None:
    """Motivo de descarte (archivado / inactivo con pocas estrellas) o None."""
    ahora = ahora or datetime.now(timezone.utc)
    if repo.get("archivado"):
        return "archivado"
    if repo.get("ultimo_push"):
        push = datetime.fromisoformat(repo["ultimo_push"].replace("Z", "+00:00"))
        if ahora - push > timedelta(days=DIAS_INACTIVO) and repo["estrellas"] < MIN_ESTRELLAS_INACTIVO:
            return "inactivo_pocas_estrellas"
    return None
