"""Extrae los repos de GitHub enlazados en listas awesome de MCP y skills.

Lee el README de cada lista con la API de GitHub y guarda, para cada repo
encontrado, en qué listas aparece. Los datos del repo (estrellas, licencia...)
se piden después, en unir.py.

Uso:
    python scripts/recopilar_awesome.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from comun import (DATOS_RAW, peticion, preparar_consola, repos_en_texto, sesion_github,
                   token_github)

SALIDA = DATOS_RAW / "awesome.json"

LISTAS = [
    "punkpeye/awesome-mcp-servers",
    "wong2/awesome-mcp-servers",
    "travisvn/awesome-claude-skills",
    "ComposioHQ/awesome-claude-skills",
    "VoltAgent/awesome-agent-skills",
    "BehiSecc/awesome-claude-skills",
    "hesreallyhim/awesome-claude-code",
]


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listas", nargs="+", default=LISTAS)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    sesion = sesion_github(token_github())
    repos: dict[str, list[str]] = {}
    resumen = {}
    for lista in args.listas:
        resp = peticion(sesion, "GET", f"https://api.github.com/repos/{lista}/readme",
                        headers={"Accept": "application/vnd.github.raw"})
        if resp is None:
            print(f"  [aviso] no se pudo leer {lista}")
            resumen[lista] = None
            continue
        encontrados = repos_en_texto(resp.text) - {lista.lower()}
        resumen[lista] = len(encontrados)
        print(f"  {lista}: {len(encontrados)} repos")
        for repo in encontrados:
            repos.setdefault(repo, []).append(lista)

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "awesome",
        "listas": resumen,
        "repos": dict(sorted(repos.items())),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRepos únicos: {len(repos)}")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
