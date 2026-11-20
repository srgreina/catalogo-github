"""Recopila repositorios públicos de GitHub por topics (MCP, skills de Claude, etc.).

Usa la API REST de búsqueda de repositorios. Para sortear el tope de 1.000
resultados por búsqueda, divide cada consulta por año de creación y, si aún
hace falta, por rangos de estrellas.

Token: si existe la variable de entorno GITHUB_TOKEN se usa (30 búsquedas/min);
si no, va sin token (10 búsquedas/min).

Uso:
    python scripts/recopilar_github.py                 # todo
    python scripts/recopilar_github.py --limite 50     # prueba rápida
    python scripts/recopilar_github.py --topics mcp-server --limite 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://api.github.com/search/repositories"
RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "data" / "raw" / "github.json"

TOPICS = [
    "mcp-server",
    "mcp",
    "model-context-protocol",
    "mcp-servers",
    "claude-skills",
    "claudeskills",
    "agent-skills",
    "claude-code",
    "claude",
    "anthropic-claude",
]

TOPE_BUSQUEDA = 1000          # GitHub no devuelve más de 1.000 resultados por consulta
POR_PAGINA = 100
PRIMER_ANIO = 2008
MIN_ESTRELLAS = 5             # mínimo para entrar en el catálogo
RANGOS_ESTRELLAS = ["5..9", "10..19", "20..49", "50..199", "200..999", "1000..*"]
DIAS_INACTIVO = 182
MIN_ESTRELLAS_INACTIVO = 20
MAX_REINTENTOS = 5


class ClienteGitHub:
    """Hace búsquedas respetando el límite de peticiones y reintentando ante 403/429."""

    def __init__(self, token: str | None):
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "catalogo-github-script",
        })
        if token:
            self.sesion.headers["Authorization"] = f"Bearer {token}"
        self.peticiones = 0

    def buscar(self, consulta: str, pagina: int) -> dict:
        params = {"q": consulta, "per_page": POR_PAGINA, "page": pagina,
                  "sort": "stars", "order": "desc"}
        for intento in range(1, MAX_REINTENTOS + 1):
            resp = self.sesion.get(API, params=params, timeout=30)
            self.peticiones += 1
            if resp.status_code == 200:
                self._pausa_si_agotado(resp)
                return resp.json()
            if resp.status_code in (403, 429):
                espera = self._segundos_espera(resp, intento)
                print(f"  [límite] {resp.status_code}: espero {espera} s "
                      f"(intento {intento}/{MAX_REINTENTOS})", file=sys.stderr)
                time.sleep(espera)
                continue
            if resp.status_code == 422:
                # Consulta no válida o página fuera de rango: se trata como vacía.
                print(f"  [aviso] 422 en «{consulta}» pág. {pagina}: {resp.text[:200]}",
                      file=sys.stderr)
                return {"total_count": 0, "incomplete_results": False, "items": []}
            if resp.status_code >= 500:
                time.sleep(5 * intento)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Sin respuesta válida tras {MAX_REINTENTOS} intentos: {consulta}")

    @staticmethod
    def _segundos_espera(resp: requests.Response, intento: int) -> int:
        if "Retry-After" in resp.headers:
            return int(resp.headers["Retry-After"]) + 1
        if resp.headers.get("X-RateLimit-Remaining") == "0" and "X-RateLimit-Reset" in resp.headers:
            return max(int(resp.headers["X-RateLimit-Reset"]) - int(time.time()), 0) + 2
        return 30 * intento

    @staticmethod
    def _pausa_si_agotado(resp: requests.Response) -> None:
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            espera = max(reset - int(time.time()), 0) + 2
            print(f"  [límite] cupo agotado: espero {espera} s", file=sys.stderr)
            time.sleep(espera)


def montar(base: str, filtros: dict) -> str:
    return " ".join([base] + [f"{k}:{v}" for k, v in filtros.items()])


def subdividir(filtros: dict, nivel: int) -> list[dict]:
    """Niveles de división: 0 → años; 1 → rangos de estrellas; 2 → meses del año."""
    if nivel == 0:
        anio_actual = datetime.now(timezone.utc).year
        return [{**filtros, "created": f"{a}-01-01..{a}-12-31"}
                for a in range(anio_actual, PRIMER_ANIO - 1, -1)]
    if nivel == 1:
        minimo = int(filtros["stars"].lstrip(">="))
        rangos = [r for r in RANGOS_ESTRELLAS if int(r.split("..")[0]) >= minimo]
        return [{**filtros, "stars": r} for r in rangos]
    anio = int(filtros["created"][:4])
    meses = []
    for m in range(12, 0, -1):
        fin = (datetime(anio + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
        meses.append({**filtros, "created": f"{anio}-{m:02d}-01..{anio}-{m:02d}-{fin:02d}"})
    return meses


def recopilar_consulta(cliente: ClienteGitHub, base: str, filtros: dict, nivel: int,
                       repos: dict, topic: str, limite: int | None) -> None:
    """Recorre una consulta; si supera el tope de 1.000, la subdivide."""
    if limite and len(repos) >= limite:
        return
    consulta = montar(base, filtros)
    primera = cliente.buscar(consulta, 1)
    total = primera["total_count"]
    if total == 0:
        return
    if total > TOPE_BUSQUEDA and nivel < 3:
        print(f"  {total} resultados en «{consulta}»: subdivido")
        for sub in subdividir(filtros, nivel):
            recopilar_consulta(cliente, base, sub, nivel + 1, repos, topic, limite)
        return
    if total > TOPE_BUSQUEDA:
        print(f"  [aviso] «{consulta}» sigue con {total} resultados; solo se leerán 1.000",
              file=sys.stderr)
    print(f"  {total} resultados en «{consulta}»")
    paginas = min((total + POR_PAGINA - 1) // POR_PAGINA, TOPE_BUSQUEDA // POR_PAGINA)
    datos = primera
    for pagina in range(1, paginas + 1):
        if pagina > 1:
            datos = cliente.buscar(consulta, pagina)
        for item in datos["items"]:
            anadir(repos, item, topic)
            if limite and len(repos) >= limite:
                return
        if len(datos["items"]) < POR_PAGINA:
            break


def anadir(repos: dict, item: dict, topic: str) -> None:
    clave = item["full_name"].lower()
    if clave in repos:
        if topic not in repos[clave]["consultas"]:
            repos[clave]["consultas"].append(topic)
        return
    licencia = item.get("license") or {}
    repos[clave] = {
        "nombre": item["full_name"],
        "url": item["html_url"],
        "descripcion": item.get("description") or "",
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
        "fuentes": ["github"],
        "consultas": [topic],
    }


def descartar(repo: dict, ahora: datetime) -> str | None:
    """Devuelve el motivo de descarte, o None si se conserva."""
    if repo["archivado"]:
        return "archivado"
    if repo["ultimo_push"]:
        push = datetime.fromisoformat(repo["ultimo_push"].replace("Z", "+00:00"))
        if ahora - push > timedelta(days=DIAS_INACTIVO) and repo["estrellas"] < MIN_ESTRELLAS_INACTIVO:
            return "inactivo_pocas_estrellas"
    return None


def main() -> None:
    # La consola de Windows no usa UTF-8 por defecto: evita tildes rotas.
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=None,
                        help="máximo de repos a recopilar (para pruebas)")
    parser.add_argument("--topics", nargs="+", default=TOPICS,
                        help="topics a consultar (por defecto, la lista completa)")
    parser.add_argument("--min-estrellas", type=int, default=MIN_ESTRELLAS,
                        help=f"estrellas mínimas (por defecto {MIN_ESTRELLAS})")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    print(f"Token: {'sí' if token else 'no (10 búsquedas/min)'}")
    cliente = ClienteGitHub(token)
    repos: dict[str, dict] = {}

    for topic in args.topics:
        print(f"Topic: {topic}")
        recopilar_consulta(cliente, f"topic:{topic} archived:false",
                           {"stars": f">={args.min_estrellas}"}, 0,
                           repos, topic, args.limite)
        if args.limite and len(repos) >= args.limite:
            break

    ahora = datetime.now(timezone.utc)
    conservados, descartes = [], {}
    for repo in repos.values():
        motivo = descartar(repo, ahora)
        if motivo:
            descartes[motivo] = descartes.get(motivo, 0) + 1
        else:
            conservados.append(repo)
    conservados.sort(key=lambda r: r["estrellas"], reverse=True)

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    resultado = {
        "generado": ahora.isoformat(timespec="seconds"),
        "fuente": "github-search",
        "peticiones": cliente.peticiones,
        "total_encontrados": len(repos),
        "descartados": descartes,
        "repos": conservados,
    }
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEncontrados: {len(repos)} · conservados: {len(conservados)} · "
          f"descartados: {descartes or 0} · peticiones: {cliente.peticiones}")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
