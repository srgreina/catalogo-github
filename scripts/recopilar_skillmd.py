"""Busca repos con ficheros SKILL.md (skills de Claude) con la búsqueda de código de GitHub.

La búsqueda de código exige token y permite 10 peticiones/min. Como cada
consulta devuelve como máximo 1.000 resultados, se divide por tamaño de fichero.
Solo se guarda qué repos tienen SKILL.md; sus datos se piden después en unir.py.

Uso:
    GITHUB_TOKEN=... python scripts/recopilar_skillmd.py
    python scripts/recopilar_skillmd.py --limite 100
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from comun import DATOS_RAW, peticion, preparar_consola, sesion_github, token_github

API = "https://api.github.com/search/code"
SALIDA = DATOS_RAW / "skillmd.json"
TOPE = 1000
POR_PAGINA = 100
# Rangos de tamaño (bytes); se subdividen por la mitad si aún superan 1.000 resultados.
RANGOS_INICIALES = [(0, 1000), (1001, 2000), (2001, 3000), (3001, 4000), (4001, 6000),
                    (6001, 8000), (8001, 12000), (12001, 20000), (20001, 400000)]


def buscar(sesion, consulta: str, pagina: int) -> dict:
    resp = peticion(sesion, "GET", API, params={"q": consulta, "per_page": POR_PAGINA,
                                                "page": pagina})
    return resp.json() if resp is not None else {"total_count": 0, "items": []}


def recorrer(sesion, desde: int, hasta: int, repos: dict, limite: int | None) -> None:
    if limite and len(repos) >= limite:
        return
    consulta = f"filename:SKILL.md size:{desde}..{hasta}"
    primera = buscar(sesion, consulta, 1)
    total = primera["total_count"]
    if total > TOPE and hasta - desde > 1:
        medio = (desde + hasta) // 2
        print(f"  {total} en «{consulta}»: subdivido")
        recorrer(sesion, desde, medio, repos, limite)
        recorrer(sesion, medio + 1, hasta, repos, limite)
        return
    print(f"  {total} en «{consulta}»")
    paginas = min((total + POR_PAGINA - 1) // POR_PAGINA, TOPE // POR_PAGINA)
    datos = primera
    for pagina in range(1, paginas + 1):
        if pagina > 1:
            datos = buscar(sesion, consulta, pagina)
        for item in datos["items"]:
            nombre = item["repository"]["full_name"].lower()
            repos[nombre] = repos.get(nombre, 0) + 1   # nº de SKILL.md en el repo
        if limite and len(repos) >= limite:
            return
        if len(datos["items"]) < POR_PAGINA:
            break


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    token = token_github()
    if not token:
        print("La búsqueda de código de GitHub exige token (variable GITHUB_TOKEN).",
              file=sys.stderr)
        sys.exit(1)
    sesion = sesion_github(token)
    prueba = sesion.get(API, params={"q": "filename:SKILL.md", "per_page": 1}, timeout=60)
    if prueba.status_code != 200:
        print(f"La búsqueda de código no acepta este token (HTTP {prueba.status_code}): "
              f"{prueba.text[:300]}", file=sys.stderr)
        print("Solución: crear un token personal y guardarlo como secreto CATALOGO_TOKEN.",
              file=sys.stderr)
        sys.exit(1)

    repos: dict[str, int] = {}
    for desde, hasta in RANGOS_INICIALES:
        recorrer(sesion, desde, hasta, repos, args.limite)

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "skill-md",
        "repos": dict(sorted(repos.items())),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRepos con SKILL.md: {len(repos)}")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
