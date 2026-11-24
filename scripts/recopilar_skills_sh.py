"""Recopila los repos de GitHub que aparecen en skills.sh, a partir de sus mapas del sitio.

La API de skills.sh exige un token de Vercel (no sirve desde Actions) y su robots.txt
prohíbe /api/ y /search. Pero publica sus mapas del sitio (sitemap.xml), pensados para
buscadores y permitidos por robots.txt: listan unas 20.000 skills con direcciones del
tipo https://www.skills.sh/propietario/repo/skill. De ahí se saca el repo de GitHub.

Son 3 peticiones al mes (el índice y dos mapas), muy por debajo de lo que sus términos
de uso consideran uso razonable. Solo se guardan nombres de repos: no se copia el
contenido de ninguna skill.

Si algo falla o la estructura cambia (menos de 500 repos, un mapa que no baja), el
script avisa, NO escribe nada y termina con error; el workflow lo ejecuta con
continue-on-error, así que esa ejecución sigue sin esta fuente.

Uso:
    python scripts/recopilar_skills_sh.py
    python scripts/recopilar_skills_sh.py --max-mapas 1     # prueba rápida
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

from comun import DATOS_RAW, peticion, preparar_consola

INDICE = "https://www.skills.sh/sitemap.xml"
SALIDA = DATOS_RAW / "skills_sh.json"
MIN_REPOS = 500        # por debajo de esto, se da por roto el formato y no se guarda nada
MAX_NOMBRES = 100      # nombres de skills que se guardan por repo

RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
RE_MAPA_SKILLS = re.compile(r"/sitemap-skills-[\w-]*\.xml$")
RE_SKILL = re.compile(
    r"^https://(?:www\.)?skills\.sh/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/([^/?#\s]+)$")


def mapas_de_skills(indice_xml: str) -> list[str]:
    """Direcciones de los mapas de skills que lista el índice."""
    return [u for u in RE_LOC.findall(indice_xml) if RE_MAPA_SKILLS.search(u)]


def repos_de_mapa(xml: str) -> dict[str, list[str]]:
    """Nombres de las skills de cada repo («propietario/repo» en minúsculas) de un mapa."""
    repos: dict[str, list[str]] = {}
    for url in RE_LOC.findall(xml):
        m = RE_SKILL.match(url)
        if m:
            repos.setdefault(f"{m.group(1)}/{m.group(2)}".lower(), []).append(unquote(m.group(3)))
    return repos


def bajar(sesion: requests.Session, url: str) -> str | None:
    try:
        resp = peticion(sesion, "GET", url)
    except (RuntimeError, requests.RequestException) as err:
        print(f"  [aviso] no se pudo bajar {url}: {err}", file=sys.stderr)
        return None
    if resp is None:
        print(f"  [aviso] {url} no existe o no es accesible", file=sys.stderr)
        return None
    return resp.text


def main() -> int:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-mapas", type=int, default=None,
                        help="bajar solo los N primeros mapas (para pruebas)")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    sesion = requests.Session()
    sesion.headers["User-Agent"] = "catalogo-github-script"

    indice = bajar(sesion, INDICE)
    mapas = mapas_de_skills(indice) if indice else []
    if not mapas:
        print("[ERROR] No se encontró ningún mapa de skills en el índice de skills.sh: "
              "¿ha cambiado su estructura? No se guarda nada.", file=sys.stderr)
        return 1
    if args.max_mapas:
        mapas = mapas[:args.max_mapas]

    repos: dict[str, list[str]] = {}
    skills = 0
    for url in mapas:
        xml = bajar(sesion, url)
        if xml is None:
            print("[ERROR] Falta un mapa: los datos saldrían incompletos. No se guarda nada.",
                  file=sys.stderr)
            return 1
        parcial = repos_de_mapa(xml)
        total_mapa = sum(len(v) for v in parcial.values())
        skills += total_mapa
        for repo, nombres in parcial.items():
            repos.setdefault(repo, []).extend(nombres)
        print(f"  {url.rsplit('/', 1)[-1]}: {total_mapa} skills")

    if len(repos) < MIN_REPOS and not args.max_mapas:
        print(f"[ERROR] Solo {len(repos)} repos (se esperaban más de {MIN_REPOS}): "
              f"el formato de skills.sh habrá cambiado. No se guarda nada.", file=sys.stderr)
        return 1

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "skills-sh",
        "skills": skills,
        # Repo -> nombres de sus skills (sin repetir, como máximo MAX_NOMBRES).
        "repos": {r: sorted(set(n))[:MAX_NOMBRES] for r, n in sorted(repos.items())},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSkills: {skills} · repos distintos: {len(repos)} · mapas: {len(mapas)}")
    print(f"Guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
