"""Clasifica cada repo por tipo y dominio, valora su licencia y calcula el semáforo.

Lee data/raw/unido.json y escribe data/catalogo.json.

- Tipo (puede haber varios): lista awesome, skill, servidor MCP o programa.
- Dominio (puede haber varios): por palabras clave en nombre, descripción y topics.
- Licencia: uso libre / otra (revisar) / sin licencia (no reutilizable).
- Semáforo: puntuación ORIENTATIVA de confianza (no es un análisis de seguridad
  del código), con los motivos de cada punto.

Uso:
    python scripts/clasificar.py
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from comun import DATOS_RAW, RAIZ, parece_skill, preparar_consola

ENTRADA = DATOS_RAW / "unido.json"
SALIDA = RAIZ / "data" / "catalogo.json"

LISTAS_SKILLS = {
    "travisvn/awesome-claude-skills", "ComposioHQ/awesome-claude-skills",
    "VoltAgent/awesome-agent-skills", "BehiSecc/awesome-claude-skills",
}
LISTAS_MCP = {"punkpeye/awesome-mcp-servers", "wong2/awesome-mcp-servers"}

# Palabras clave por dominio (se buscan como palabras completas, sin distinguir
# mayúsculas). Se evitan términos ambiguos en software («architecture», «training»…).
DOMINIOS = {
    "construccion_energia": [
        "bim", "ifc", "revit", "autocad", "cad", "dwg", "civil engineering",
        "structural engineering", "structural analysis", "construction", "hvac",
        "energy", "solar", "photovoltaic", "wind turbine", "wind power", "battery",
        "power grid", "smart grid", "electricity", "ev charging",
        "construcción", "construccion", "ingeniería", "ingenieria", "energía", "energia",
    ],
    "finanzas_inversion": [
        "finance", "financial", "fintech", "stocks", "stock market", "stock price", "trading",
        "trader", "investment", "investing", "portfolio management", "portfolio tracker",
        "etf", "forex", "crypto", "cryptocurrency", "bitcoin", "ethereum", "defi",
        "accounting", "bookkeeping", "banking", "sec filings", "edgar", "yahoo finance",
        "brokerage", "finanzas", "bolsa", "inversión", "inversion", "contabilidad",
    ],
    "deporte_geodatos": [
        "strava", "garmin", "fitness", "workout", "cycling", "hiking", "marathon",
        "triathlon", "sport", "sports", "gpx", "gis", "geospatial", "geojson",
        "openstreetmap", "osm", "gps", "google maps", "mapbox", "geocoding",
        "elevation", "deporte", "rutas", "senderismo", "ciclismo", "geodatos",
    ],
    "documentos_productividad": [
        "pdf", "docx", "xlsx", "excel", "pptx", "powerpoint", "spreadsheet", "ocr",
        "notion", "obsidian", "calendar", "email", "gmail", "outlook", "note taking",
        "notes app", "todo", "todoist", "productivity", "google docs", "google drive",
        "google sheets", "office", "documentos", "productividad",
    ],
}
PATRONES_DOMINIO = {
    dominio: re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(palabras, key=len,
                                                                       reverse=True)) + r")\b")
    for dominio, palabras in DOMINIOS.items()
}

LICENCIAS_LIBRES = {
    "MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC",
    "MPL-2.0", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0", "AGPL-3.0", "Unlicense",
    "CC0-1.0", "CC-BY-4.0", "EPL-2.0", "Zlib", "BSL-1.0", "WTFPL", "EUPL-1.2",
}


def texto_busqueda(repo: dict) -> str:
    partes = [repo["nombre"].split("/", 1)[-1], repo.get("descripcion") or ""]
    partes += repo.get("topics", [])
    return re.sub(r"[-_/]", " ", " ".join(partes)).lower()


def tipos(repo: dict) -> list[str]:
    nombre = repo["nombre"].split("/", 1)[-1].lower()
    topics = {t.lower() for t in repo.get("topics", [])}
    listas = set(repo.get("listas_awesome", []))
    if nombre.startswith("awesome") or topics & {"awesome", "awesome-list"}:
        return ["lista"]
    resultado = []
    if parece_skill(repo) or listas & LISTAS_SKILLS or "skills-sh" in repo.get("fuentes", []):
        resultado.append("skill")
    if ("mcp" in nombre or any("mcp" in t or t == "model-context-protocol" for t in topics)
            or "registro-mcp" in repo.get("fuentes", []) or listas & LISTAS_MCP):
        resultado.append("mcp")
    return resultado or ["programa"]


def dominios(repo: dict) -> tuple[list[str], dict[str, list[str]]]:
    texto = texto_busqueda(repo)
    encontrados = {}
    for dominio, patron in PATRONES_DOMINIO.items():
        coincidencias = sorted(set(patron.findall(texto)))
        if coincidencias:
            encontrados[dominio] = coincidencias
    return (list(encontrados) or ["otros"]), encontrados


def licencia(spdx: str | None) -> str:
    if not spdx:
        return "sin_licencia"
    return "libre" if spdx in LICENCIAS_LIBRES else "otra"


def semaforo(repo: dict, tipo_licencia: str, ahora: datetime) -> dict:
    puntos, motivos = 0, []

    def sumar(valor: int, motivo: str) -> None:
        nonlocal puntos
        puntos += valor
        motivos.append(f"{'+' if valor > 0 else ''}{valor} {motivo}")

    def dias(fecha: str | None) -> int | None:
        if not fecha:
            return None
        return (ahora - datetime.fromisoformat(fecha.replace("Z", "+00:00"))).days

    edad = dias(repo.get("creado"))
    if edad is not None and edad >= 365:
        sumar(2, "más de 1 año")
    elif edad is not None and edad >= 90:
        sumar(1, "más de 3 meses")

    estrellas = repo.get("estrellas", 0)
    if estrellas >= 1000:
        sumar(3, "≥1.000 estrellas")
    elif estrellas >= 100:
        sumar(2, "≥100 estrellas")
    elif estrellas >= 20:
        sumar(1, "≥20 estrellas")

    if repo.get("forks", 0) >= 10:
        sumar(1, "≥10 forks")
    push = dias(repo.get("ultimo_push"))
    if push is not None and push <= 90:
        sumar(1, "actividad en los últimos 3 meses")
    if repo.get("tipo_propietario") == "Organization":
        sumar(1, "de una organización")
    if "registro-mcp" in repo.get("fuentes", []):
        sumar(1, "en el registro oficial MCP")
    if tipo_licencia == "libre":
        sumar(1, "licencia libre")
    elif tipo_licencia == "sin_licencia":
        sumar(-1, "sin licencia")
    if repo.get("incidencias_abiertas", 0) > max(estrellas, 1):
        sumar(-1, "más incidencias abiertas que estrellas")

    color = "verde" if puntos >= 6 else "ambar" if puntos >= 3 else "rojo"
    return {"color": color, "puntos": puntos, "motivos": motivos}


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entrada", type=Path, default=ENTRADA)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()

    datos = json.loads(args.entrada.read_text(encoding="utf-8"))
    ahora = datetime.now(timezone.utc)
    resumen = {"tipo": {}, "dominio": {}, "licencia": {}, "semaforo": {}}

    def contar(grupo: str, valor: str) -> None:
        resumen[grupo][valor] = resumen[grupo].get(valor, 0) + 1

    for repo in datos["repos"]:
        repo["tipos"] = tipos(repo)
        repo["dominios"], repo["dominios_palabras"] = dominios(repo)
        repo["tipo_licencia"] = licencia(repo.get("licencia"))
        repo["semaforo"] = semaforo(repo, repo["tipo_licencia"], ahora)
        for t in repo["tipos"]:
            contar("tipo", t)
        for d in repo["dominios"]:
            contar("dominio", d)
        contar("licencia", repo["tipo_licencia"])
        contar("semaforo", repo["semaforo"]["color"])

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "generado": ahora.isoformat(timespec="seconds"),
        "total": len(datos["repos"]),
        "resumen": resumen,
        "repos": datos["repos"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Repos: {len(datos['repos'])}")
    for grupo, valores in resumen.items():
        print(f"  {grupo}: {dict(sorted(valores.items(), key=lambda kv: -kv[1]))}")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
