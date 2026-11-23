"""Genera los datos de la web, el histórico y las novedades del mes.

- Lee data/catalogo.json (ya clasificado y traducido).
- Actualiza data/historico.json: fecha en que se vio cada repo por primera vez y
  sus estrellas en las últimas ejecuciones (una al mes).
- Escribe data/novedades.json: repos que aparecen por primera vez en el último mes.
- Escribe docs/datos.json: versión reducida (campos cortos) que carga la web, y
  docs/detalles/00..ff.json: el resto de cada ficha, repartido por el SHA-1 del
  nombre (la web descarga solo el fichero del repo que se abre).

La primera ejecución solo crea la base del histórico: no marca novedades, porque
todo sería «nuevo».

Uso:
    python scripts/generar_web.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone

from comun import RAIZ, guardar_por_lineas, preparar_consola

CATALOGO = RAIZ / "data" / "catalogo.json"
HISTORICO = RAIZ / "data" / "historico.json"
NOVEDADES = RAIZ / "data" / "novedades.json"
WEB = RAIZ / "docs" / "datos.json"
DETALLES = RAIZ / "docs" / "detalles"
INSTANTANEAS_GUARDADAS = 8
# La ejecución es mensual (el mes más corto: 28 días). Con 25 días, lo visto en la
# ejecución anterior ya no cuenta como novedad, y una ejecución manual a mitad de
# mes no borra las novedades ni las subidas.
DIAS_NOVEDAD = 25
DIAS_SUBIDA = 25
DIAS_OLVIDO = 240     # repos que ya no están: se borran del histórico tras ~8 meses
MAX_TOPICS = 8
MAX_CAIDA = 0.15      # si el catálogo baja más de un 15 % respecto al anterior, no se publica
COLOR = {"verde": "v", "ambar": "a", "rojo": "r"}


def trozo(clave: str) -> str:
    """Fichero de detalles (00..ff) en el que va un repo. La web usa la misma regla."""
    return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:2]


def solo_fecha(valor: str | None) -> str | None:
    return valor[:10] if valor else None


def estrellas_hace(historial: dict[str, int], hoy: date, dias: int) -> int | None:
    """Estrellas en la instantánea más reciente con al menos «dias» de antigüedad."""
    limite = (hoy - timedelta(days=dias)).isoformat()
    anteriores = [f for f in historial if f <= limite]
    return historial[max(anteriores)] if anteriores else None


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fecha", default=None,
                        help="fecha de la ejecución (AAAA-MM-DD); por defecto, hoy")
    parser.add_argument("--forzar", action="store_true",
                        help="publicar aunque el catálogo haya bajado más de un 15 %%")
    args = parser.parse_args()

    ahora = datetime.now(timezone.utc)
    hoy = date.fromisoformat(args.fecha) if args.fecha else ahora.date()
    hoy_txt = hoy.isoformat()

    datos = json.loads(CATALOGO.read_text(encoding="utf-8"))
    historico = (json.loads(HISTORICO.read_text(encoding="utf-8")) if HISTORICO.exists()
                 else {"base": hoy_txt, "repos": {}})
    base = historico["base"]
    hist_repos: dict = historico["repos"]

    # Seguridad: si una búsqueda falló a medias, el catálogo saldría con huecos.
    # Se aborta antes de escribir nada (el workflow no publica ni guarda).
    previo = historico.get("total")
    if previo and len(datos["repos"]) < previo * (1 - MAX_CAIDA) and not args.forzar:
        print(f"[ERROR] El catálogo ha bajado de {previo} a {len(datos['repos'])} repos "
              f"(más de un {MAX_CAIDA:.0%}). Parece que alguna fuente ha fallado: no se publica. "
              f"Revisa la ejecución o usa --forzar.", file=sys.stderr)
        sys.exit(1)
    historico["total"] = len(datos["repos"])

    repos_web, novedades = [], []
    detalles: dict[str, dict] = {}
    for repo in datos["repos"]:
        clave = repo["nombre"].lower()
        h = hist_repos.setdefault(clave, {"primera": hoy_txt, "estrellas": {}})
        h["estrellas"][hoy_txt] = repo["estrellas"]
        # Conservar solo las últimas instantáneas.
        for fecha in sorted(h["estrellas"])[:-INSTANTANEAS_GUARDADAS]:
            del h["estrellas"][fecha]

        nuevo = h["primera"] > base and (hoy - date.fromisoformat(h["primera"])).days < DIAS_NOVEDAD
        previas = estrellas_hace(h["estrellas"], hoy, DIAS_SUBIDA)
        subida = repo["estrellas"] - previas if previas is not None else None

        original = repo.get("descripcion") or ""
        traducida = repo.get("descripcion_es") or original
        sem = repo["semaforo"]
        # Lista: lo necesario para mostrar, buscar y filtrar (campos cortos).
        entrada = {
            "n": repo["nombre"],
            "d": traducida,
            "t": repo["tipos"],
            "m": [d for d in repo["dominios"] if d != "otros"],
            "s": repo["estrellas"],
            "l": repo.get("licencia"),
            "lt": repo["tipo_licencia"],
            "c": solo_fecha(repo.get("creado")),
            "p": solo_fecha(repo.get("ultimo_push")),
            "sm": COLOR[sem["color"]],
            "fu": repo["fuentes"],
        }
        if repo.get("tipo_propietario") == "Organization":
            entrada["org"] = 1
        # Ficha: se descarga solo al abrir el repo.
        detalle = {
            "f": repo.get("forks", 0),
            "i": repo.get("incidencias_abiertas", 0),
            "sp": sem["puntos"],
            "mo": sem["motivos"],
        }
        if traducida != original:
            detalle["o"] = original
        if repo.get("topics"):
            detalle["tp"] = repo["topics"][:MAX_TOPICS]
        if repo.get("lenguaje"):
            detalle["lg"] = repo["lenguaje"]
        if repo.get("web"):
            detalle["w"] = repo["web"]
        # Cómo usarlo, si está en el registro oficial MCP.
        registro = repo.get("registro_mcp") or []
        paquetes = sorted({p for r in registro for p in r.get("paquetes", [])})
        remotos = list(dict.fromkeys(u for r in registro for u in r.get("remotos", [])))
        if paquetes:
            detalle["pq"] = paquetes
        if remotos:
            detalle["rt"] = remotos[:2]
        detalles.setdefault(trozo(clave), {})[clave] = detalle
        if nuevo:
            entrada["nv"] = 1
            novedades.append({"nombre": repo["nombre"], "url": repo["url"],
                              "descripcion": traducida, "tipos": repo["tipos"],
                              "estrellas": repo["estrellas"]})
        if subida and subida > 0:
            entrada["sb"] = subida
        repos_web.append(entrada)

    # Los repos que ya no están en el catálogo se borran del histórico pasado un
    # tiempo (si vuelven antes, no cuentan como novedad).
    limite = (hoy - timedelta(days=DIAS_OLVIDO)).isoformat()
    for clave in [c for c, h in hist_repos.items() if max(h["estrellas"], default="") < limite]:
        del hist_repos[clave]

    guardar_por_lineas(HISTORICO, historico, "repos")
    NOVEDADES.write_text(json.dumps({"fecha": hoy_txt, "total": len(novedades),
                                     "repos": novedades}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    WEB.parent.mkdir(parents=True, exist_ok=True)
    WEB.write_text(json.dumps({
        "generado": ahora.isoformat(timespec="minutes"),
        "primera_ejecucion": base == hoy_txt,
        "repos": repos_web,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    shutil.rmtree(DETALLES, ignore_errors=True)
    DETALLES.mkdir(parents=True)
    for nombre, contenido in detalles.items():
        (DETALLES / f"{nombre}.json").write_text(
            json.dumps(contenido, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tam = WEB.stat().st_size / 1024 / 1024
    tam_det = sum(f.stat().st_size for f in DETALLES.iterdir()) / 1024 / 1024
    print(f"Repos en la web: {len(repos_web)} · novedades: {len(novedades)} · "
          f"con subida de estrellas: {sum(1 for r in repos_web if r.get('sb'))} · "
          f"datos.json: {tam:.2f} MB · detalles: {tam_det:.2f} MB en {len(detalles)} ficheros")


if __name__ == "__main__":
    main()
