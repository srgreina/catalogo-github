"""Recopila los servidores del registro oficial de MCP.

API: https://registry.modelcontextprotocol.io/v0/servers
Pagina por cursor (metadata.nextCursor), 100 servidores por página, y se pide
solo la última versión de cada servidor (version=latest).

Uso:
    python scripts/recopilar_registro_mcp.py
    python scripts/recopilar_registro_mcp.py --limite 200
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from comun import DATOS_RAW, arreglar_texto, peticion, preparar_consola, repos_en_texto

API = "https://registry.modelcontextprotocol.io/v0/servers"
SALIDA = DATOS_RAW / "registro_mcp.json"
CLAVE_META = "io.modelcontextprotocol.registry/official"


def convertir(entrada: dict) -> dict:
    servidor = entrada["server"]
    meta = entrada.get("_meta", {}).get(CLAVE_META, {})
    repositorio = servidor.get("repository") or {}
    url_repo = repositorio.get("url") or ""
    repos = repos_en_texto(url_repo) if repositorio.get("source", "github") == "github" else set()
    return {
        "id": servidor["name"],
        "titulo": servidor.get("title") or None,
        "descripcion": arreglar_texto(servidor.get("description")),
        "version": servidor.get("version"),
        "web": servidor.get("websiteUrl") or None,
        "url_repo": url_repo or None,
        "repo": next(iter(repos), None),  # «owner/repo» en minúsculas si está en GitHub
        "remotos": [r.get("url") for r in servidor.get("remotes", []) if r.get("url")],
        "paquetes": sorted({p.get("registryType") for p in servidor.get("packages", [])
                            if p.get("registryType")}),
        "estado": meta.get("status"),
        "publicado": meta.get("publishedAt"),
        "actualizado": meta.get("updatedAt"),
    }


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    sesion = requests.Session()
    sesion.headers["User-Agent"] = "catalogo-github-script"
    servidores: dict[str, dict] = {}
    cursor = None
    paginas = 0
    while True:
        params = {"limit": 100, "version": "latest"}
        if cursor:
            params["cursor"] = cursor
        resp = peticion(sesion, "GET", API, params=params)
        if resp is None:
            break
        datos = resp.json()
        paginas += 1
        for entrada in datos.get("servers", []):
            s = convertir(entrada)
            servidores[s["id"]] = s
        cursor = (datos.get("metadata") or {}).get("nextCursor")
        if paginas % 10 == 0:
            print(f"  {paginas} páginas, {len(servidores)} servidores")
        if not cursor or (args.limite and len(servidores) >= args.limite):
            break

    lista = [s for s in servidores.values() if s["estado"] in (None, "active")]
    con_repo = sum(1 for s in lista if s["repo"])
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "registro-mcp",
        "servidores": lista,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nServidores activos: {len(lista)} (con repo en GitHub: {con_repo}) · "
          f"páginas: {paginas}")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
