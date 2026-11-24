"""Traducciones de calidad (hechas por Claude Code con la skill baoyu-translate) de los
resúmenes de los repos más populares.

Argos traduce mal a veces («Oscuro/Light tema de la lucha»). Para los repos más vistos se
sustituye su traducción por una hecha en una sesión de Claude Code. Es manual: no corre en
el workflow. El flujo es:

1. preparar: baja los README de los N repos más populares, extrae los textos SIN traducir
   (con las mismas reglas que resumir.py) y los guarda en un fichero de trabajo.
2. (Claude Code traduce ese fichero a español y escribe otro con las traducciones.)
   Un campo se puede poner a null para DESCARTARLO (texto basura que la extracción cogió
   por error: un aviso, una lista de idiomas, HTML cortado); desaparece también el de Argos.
   En una lista, un null descarta solo esa frase.
3. aplicar: comprueba las traducciones (misma estructura que los originales) y las añade a
   data/traducciones_claude.json, que generar_web.py prefiere a las de Argos.

Cada entrada guarda «h», la huella del README del que salió; si el README cambia mucho
después y resumir.py rehace el resumen (otra huella), la traducción manual ya no se usa.

Uso:
    python scripts/traduccion_manual.py preparar --top 300 --salida trabajo.json
    python scripts/traduccion_manual.py aplicar --originales trabajo.json --traducciones es.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from clasificar import tipos as tipos_de
from comun import RAIZ, guardar_por_lineas, preparar_consola, sesion_github, token_github
from resumir import LOTE, analizar, bajar_lote, huella
from traducir import detectar_idioma

CATALOGO = RAIZ / "data" / "estado_github.json"      # repos de la búsqueda, con la descripción original
SALIDA = RAIZ / "data" / "traducciones_claude.json"
CAMPOS_TEXTO = ("q", "k")
CAMPOS_LISTA = ("c", "r")


def cargar_hechas(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))["repos"] if ruta.exists() else {}


def preparar(args: argparse.Namespace) -> None:
    token = token_github()
    if not token:
        sys.exit("Hace falta GITHUB_TOKEN para bajar los README.")
    repos = json.loads(args.catalogo.read_text(encoding="utf-8"))["repos"]
    for r in repos:
        r["tipos"] = tipos_de(r)
    hechas = cargar_hechas(args.hechas)
    candidatos = sorted((r for r in repos if "lista" not in r["tipos"]), key=lambda r: -r["estrellas"])
    if not args.rehacer:
        candidatos = [r for r in candidatos if r["nombre"].lower() not in hechas]
    candidatos = candidatos[:args.top]
    print(f"Repos por preparar: {len(candidatos)}")

    sesion = sesion_github(token)
    trabajo = []
    for i in range(0, len(candidatos), LOTE):
        grupo = candidatos[i:i + LOTE]
        bajados = bajar_lote(sesion, grupo)
        for r in grupo:
            clave = r["nombre"].lower()
            if clave not in bajados:
                continue
            readme, skill = bajados[clave]
            res = analizar(readme, skill, r.get("descripcion"))
            item: dict = {"n": r["nombre"], "s": r["estrellas"], "h": huella((readme or "") + "\0" + (skill or ""))}
            for c in CAMPOS_TEXTO:
                if c in res and detectar_idioma(res[c]) != "es":
                    item[c] = res[c]
            for c in CAMPOS_LISTA:
                if c in res and any(detectar_idioma(t) != "es" for t in res[c]):
                    item[c] = res[c]
            if len(item) > 3:                       # hay algo que traducir
                trabajo.append(item)
        print(f"  {min(i + LOTE, len(candidatos))}/{len(candidatos)}")
    args.salida.write_text(json.dumps(trabajo, ensure_ascii=False, indent=1), encoding="utf-8")
    segmentos = sum(len(t.get("c", [])) + len(t.get("r", [])) + sum(c in t for c in CAMPOS_TEXTO) for t in trabajo)
    print(f"{len(trabajo)} repos con textos que traducir · {segmentos} frases · guardado en {args.salida}")


def comprobar(item: dict, trad: dict) -> list[str]:
    """Problemas de una traducción respecto a su original (lista vacía = correcta)."""
    fallos = []
    for c in CAMPOS_TEXTO:
        if c in item and trad.get(c) is not None and not (isinstance(trad.get(c), str) and trad[c].strip()):
            fallos.append(f"falta {c}")
        if c in item and c not in trad:
            fallos.append(f"falta {c} (usa null para descartarlo)")
    for c in CAMPOS_LISTA:
        if c in item:
            t = trad.get(c)
            if c not in trad:
                fallos.append(f"falta {c} (usa null para descartarlo)")
            elif t is not None and not (isinstance(t, list) and len(t) == len(item[c])
                                        and all(x is None or (isinstance(x, str) and x.strip()) for x in t)):
                fallos.append(f"{c}: debe ser una lista de {len(item[c])} textos (null para descartar uno)")
    return fallos


def aplicar(args: argparse.Namespace) -> None:
    originales = {o["n"].lower(): o for o in json.loads(args.originales.read_text(encoding="utf-8"))}
    traducciones = json.loads(args.traducciones.read_text(encoding="utf-8"))
    hechas = cargar_hechas(args.hechas)
    nuevas = rechazadas = 0
    for nombre, trad in traducciones.items():
        clave = nombre.lower()
        item = originales.get(clave)
        if item is None:
            print(f"  [rechazada] {nombre}: no está en el fichero de originales")
            rechazadas += 1
            continue
        fallos = comprobar(item, trad)
        if fallos:
            print(f"  [rechazada] {nombre}: {'; '.join(fallos)}")
            rechazadas += 1
            continue
        entrada = {"h": item["h"]}
        if "q" in item:
            entrada["qo"] = item["q"]                  # el original, para «Ver el texto original»
        for c in (*CAMPOS_TEXTO, *CAMPOS_LISTA):
            if c in item:
                valor = trad[c]                       # null = descartar ese campo (texto basura)
                if isinstance(valor, list):           # y null dentro de una lista = descartar esa frase
                    valor = [x for x in valor if x is not None] or None
                entrada[c] = valor
        if "q" in entrada and entrada["q"] is None:
            entrada.pop("qo", None)
        hechas[clave] = entrada
        nuevas += 1
    guardar_por_lineas(args.hechas, {"generado": datetime.now(timezone.utc).date().isoformat(),
                                     "repos": hechas}, "repos")
    print(f"Añadidas: {nuevas} · rechazadas: {rechazadas} · total: {len(hechas)} en {args.hechas}")


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--top", type=int, default=300)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--catalogo", type=Path, default=CATALOGO)
    p.add_argument("--hechas", type=Path, default=SALIDA)
    p.add_argument("--rehacer", action="store_true", help="incluir también los ya traducidos")
    a = sub.add_parser("aplicar")
    a.add_argument("--originales", type=Path, required=True)
    a.add_argument("--traducciones", type=Path, required=True)
    a.add_argument("--hechas", type=Path, default=SALIDA)
    args = parser.parse_args()
    (preparar if args.orden == "preparar" else aplicar)(args)


if __name__ == "__main__":
    main()
