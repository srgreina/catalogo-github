"""Une las fuentes (búsqueda de GitHub, registro MCP, listas awesome) sin duplicados.

La clave es «owner/repo» en minúsculas. Los repos que llegan del registro MCP o
de las listas awesome y no estaban en la búsqueda se completan con la API de
GitHub, y a todos se les descartan los archivados y los inactivos con pocas
estrellas. Además:

- Repos que solo vienen del registro MCP: mínimo de 5 estrellas, igual que la
  búsqueda (en el registro publica cualquiera).
- Repos de listas awesome: sin mínimo de estrellas (listas revisadas a mano).
- Servidores del registro sin repo en GitHub: se excluyen (no hay datos para
  filtrarlos ni para el semáforo).

Uso:
    python scripts/unir.py
    python scripts/unir.py --max-consultas 20     # prueba sin token
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from comun import DATOS_RAW, descartar, obtener_repos, preparar_consola, token_github

SALIDA = DATOS_RAW / "unido.json"
MIN_ESTRELLAS_REGISTRO = 5


def leer(nombre: str) -> dict:
    ruta = DATOS_RAW / nombre
    if not ruta.exists():
        print(f"  [aviso] falta {ruta.name}; se omite esa fuente")
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def anadir_fuente(repo: dict, fuente: str) -> None:
    fuentes = repo.setdefault("fuentes", [])
    if fuente not in fuentes:
        fuentes.append(fuente)


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-consultas", type=int, default=None,
                        help="máximo de repos nuevos a consultar en GitHub (para pruebas)")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    catalogo: dict[str, dict] = {}
    for repo in leer("github.json").get("repos", []):
        catalogo[repo["nombre"].lower()] = {**repo, "fuentes": ["github"]}
    print(f"Búsqueda de GitHub: {len(catalogo)} repos")

    # Información extra de repos que aún no tienen datos de GitHub.
    pendientes: dict[str, dict] = {}

    def extra(clave: str) -> dict:
        return catalogo[clave] if clave in catalogo else pendientes.setdefault(clave, {})

    servidores = leer("registro_mcp.json").get("servidores", [])
    sin_repo = 0
    for s in servidores:
        if not s["repo"]:
            sin_repo += 1
            continue
        destino = extra(s["repo"])
        anadir_fuente(destino, "registro-mcp")
        destino.setdefault("registro_mcp", []).append({
            "id": s["id"], "titulo": s["titulo"], "version": s["version"],
            "remotos": s["remotos"], "paquetes": s["paquetes"]})
    print(f"Registro MCP: {len(servidores)} servidores ({sin_repo} sin repo en GitHub, excluidos)")

    awesome = leer("awesome.json").get("repos", {})
    for clave, listas in awesome.items():
        destino = extra(clave)
        anadir_fuente(destino, "awesome")
        destino["listas_awesome"] = listas
    print(f"Listas awesome: {len(awesome)} repos")

    # Completar con la API de GitHub los repos que no salieron en la búsqueda.
    nombres = sorted(pendientes)
    if args.max_consultas is not None:
        nombres = nombres[:args.max_consultas]
    print(f"Repos nuevos a consultar en GitHub: {len(nombres)} de {len(pendientes)}")
    datos = obtener_repos(nombres, token_github())

    ahora = datetime.now(timezone.utc)
    descartes: dict[str, int] = {}

    def contar(motivo: str) -> None:
        descartes[motivo] = descartes.get(motivo, 0) + 1

    for clave in nombres:
        repo = datos.get(clave)
        info = pendientes[clave]
        if repo is None:
            contar("no_existe")
            continue
        motivo = descartar(repo, ahora)
        if motivo:
            contar(motivo)
            continue
        if "awesome" not in info["fuentes"] and repo["estrellas"] < MIN_ESTRELLAS_REGISTRO:
            contar("registro_pocas_estrellas")
            continue
        nueva = repo["nombre"].lower()  # puede diferir si el repo se renombró
        if nueva in catalogo:
            existente = catalogo[nueva]
            for fuente in info["fuentes"]:
                anadir_fuente(existente, fuente)
            existente.setdefault("registro_mcp", []).extend(info.get("registro_mcp", []))
            if "listas_awesome" in info:
                existente["listas_awesome"] = sorted(
                    set(existente.get("listas_awesome", [])) | set(info["listas_awesome"]))
        else:
            catalogo[nueva] = {**repo, **info}

    lista = sorted(catalogo.values(), key=lambda r: r["estrellas"], reverse=True)
    por_fuente: dict[str, int] = {}
    for r in lista:
        for f in r["fuentes"]:
            por_fuente[f] = por_fuente.get(f, 0) + 1

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": ahora.isoformat(timespec="seconds"),
        "total": len(lista),
        "por_fuente": por_fuente,
        "descartados": descartes,
        "sin_consultar": len(pendientes) - len(nombres),
        "repos": lista,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal unido: {len(lista)} · por fuente: {por_fuente} · descartados: {descartes}")
    if len(pendientes) > len(nombres):
        print(f"[prueba] {len(pendientes) - len(nombres)} repos nuevos sin consultar")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
