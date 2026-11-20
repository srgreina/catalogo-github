"""Recopila repositorios públicos de GitHub por topics (MCP, skills de Claude, etc.).

Usa la API REST de búsqueda de repositorios. Para sortear el tope de 1.000
resultados por búsqueda, divide cada consulta por año de creación, después por
rangos de estrellas y, si aún hace falta, por meses.

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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from comun import (DATOS_RAW, descartar, peticion, preparar_consola, repo_desde_rest,
                   sesion_github, token_github)

API = "https://api.github.com/search/repositories"
SALIDA = DATOS_RAW / "github.json"

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


class ClienteBusqueda:
    def __init__(self, token: str | None):
        self.sesion = sesion_github(token)
        self.peticiones = 0

    def buscar(self, consulta: str, pagina: int) -> dict:
        params = {"q": consulta, "per_page": POR_PAGINA, "page": pagina,
                  "sort": "stars", "order": "desc"}
        self.peticiones += 1
        resp = peticion(self.sesion, "GET", API, params=params)
        if resp is None:
            print(f"  [aviso] consulta no válida o fuera de rango: «{consulta}» pág. {pagina}",
                  file=sys.stderr)
            return {"total_count": 0, "incomplete_results": False, "items": []}
        return resp.json()


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


def recopilar_consulta(cliente: ClienteBusqueda, base: str, filtros: dict, nivel: int,
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
    repos[clave] = {**repo_desde_rest(item), "consultas": [topic]}


def main() -> None:
    preparar_consola()
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

    token = token_github()
    print(f"Token: {'sí' if token else 'no (10 búsquedas/min)'}")
    cliente = ClienteBusqueda(token)
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
