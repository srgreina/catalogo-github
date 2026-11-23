"""Recopila repositorios públicos de GitHub por topics (MCP, skills de Claude, etc.).

Usa la API REST de búsqueda de repositorios. Para sortear el tope de 1.000
resultados por búsqueda, divide cada consulta por año de creación, después por
rangos de estrellas y, si aún hace falta, por meses.

Búsqueda incremental: data/estado_github.json guarda los repos de la ejecución
anterior. Si existe y la última búsqueda completa tiene menos de 85 días, solo se
buscan los repos con actividad (push) desde la ejecución anterior; el resto se
conserva con los datos que ya tenía (sus estrellas no se actualizan hasta la
siguiente búsqueda completa, que se hace cada ~3 meses o con --completa). Solo las
skills con ≥50 estrellas se refrescan cada vez por GraphQL (necesita token).

Token: si existe la variable de entorno GITHUB_TOKEN se usa (30 búsquedas/min);
si no, va sin token (10 búsquedas/min).

Uso:
    python scripts/recopilar_github.py                 # incremental o completa, según el estado
    python scripts/recopilar_github.py --completa      # fuerza la búsqueda completa
    python scripts/recopilar_github.py --limite 50     # prueba rápida (no toca el estado)
    python scripts/recopilar_github.py --topics mcp-server --limite 20
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from comun import (DATOS_RAW, RAIZ, descartar, guardar_por_lineas, obtener_repos,
                   parece_skill, peticion, preparar_consola, repo_desde_rest, sesion_github,
                   token_github)

API = "https://api.github.com/search/repositories"
SALIDA = DATOS_RAW / "github.json"
ESTADO = RAIZ / "data" / "estado_github.json"
DIAS_COMPLETA = 85      # cada cuánto se repite la búsqueda completa
DIAS_MARGEN = 3         # se busca algo antes de la ejecución anterior, por si acaso
MIN_ESTRELLAS_REFRESCO = 50   # skills conservadas que se refrescan por GraphQL

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
                       repos: dict, limite: int | None) -> None:
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
            recopilar_consulta(cliente, base, sub, nivel + 1, repos, limite)
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
            anadir(repos, item)
            if limite and len(repos) >= limite:
                return
        if len(datos["items"]) < POR_PAGINA:
            break


def anadir(repos: dict, item: dict) -> None:
    repos.setdefault(item["full_name"].lower(), repo_desde_rest(item))


def refrescar_skills(repos: dict, conservados: list[dict], token: str) -> None:
    """Actualiza estrellas, archivado, etc. de las skills conservadas con ≥50 estrellas.

    Los repos que ya no existen (NOT_FOUND) se quitan; los que fallan por un error
    de GitHub se dejan como estaban.
    """
    nombres = sorted(r["nombre"] for r in conservados
                     if r["estrellas"] >= MIN_ESTRELLAS_REFRESCO and parece_skill(r))
    print(f"Refrescando {len(nombres)} skills con ≥{MIN_ESTRELLAS_REFRESCO} estrellas")
    fallidos: set[str] = set()
    nuevos = obtener_repos(nombres, token, fallidos=fallidos)
    for nombre in nombres:
        clave = nombre.lower()
        if clave in nuevos:
            repos.pop(clave, None)
            repos[nuevos[clave]["nombre"].lower()] = nuevos[clave]   # por si se renombró
        elif clave not in fallidos:
            del repos[clave]
    borrados = sum(1 for n in nombres if n.lower() not in nuevos and n.lower() not in fallidos)
    print(f"  refrescadas: {len(nuevos)} · desaparecidas: {borrados} · con error: {len(fallidos)}")


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
    parser.add_argument("--completa", action="store_true",
                        help="buscar todo aunque haya estado de la ejecución anterior")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    ahora = datetime.now(timezone.utc)
    hoy = ahora.date()
    # Las pruebas (límite o topics a mano) ni usan ni modifican el estado.
    prueba = bool(args.limite) or args.topics != TOPICS or args.min_estrellas != MIN_ESTRELLAS
    estado = None
    if not prueba and not args.completa and ESTADO.exists():
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
        if (hoy - date.fromisoformat(estado["ultima_completa"])).days >= DIAS_COMPLETA:
            estado = None
    desde = (date.fromisoformat(estado["ultima"]) - timedelta(days=DIAS_MARGEN)
             if estado else None)
    print(f"Búsqueda {'incremental (push desde ' + desde.isoformat() + ')' if desde else 'completa'}")

    token = token_github()
    print(f"Token: {'sí' if token else 'no (10 búsquedas/min)'}")
    cliente = ClienteBusqueda(token)
    repos: dict[str, dict] = {}
    filtro_push = f" pushed:>={desde.isoformat()}" if desde else ""

    for topic in args.topics:
        print(f"Topic: {topic}")
        recopilar_consulta(cliente, f"topic:{topic} archived:false{filtro_push}",
                           {"stars": f">={args.min_estrellas}"}, 0,
                           repos, args.limite)
        if args.limite and len(repos) >= args.limite:
            break

    # Incremental: los repos sin actividad conservan los datos de la vez anterior...
    actualizados = len(repos)
    if estado:
        conservados_antes = []
        for repo in estado["repos"]:
            repo.pop("consultas", None)       # campo antiguo, ya no se usa
            if repo["nombre"].lower() not in repos:
                repos[repo["nombre"].lower()] = repo
                conservados_antes.append(repo)
        print(f"Actualizados: {actualizados} · conservados de la ejecución anterior: "
              f"{len(conservados_antes)}")
        # ...salvo las skills con muchas estrellas: se refrescan por GraphQL, porque
        # pueden ganar estrellas (o archivarse) sin que nadie haga push.
        if token:
            refrescar_skills(repos, conservados_antes, token)

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

    if not prueba:
        guardar_por_lineas(ESTADO, {
            "ultima": hoy.isoformat(),
            "ultima_completa": estado["ultima_completa"] if estado else hoy.isoformat(),
            "repos": conservados,
        }, "repos")
        print(f"Estado guardado en {ESTADO}")


if __name__ == "__main__":
    main()
