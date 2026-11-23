"""Calcula el panorama de ideas del catálogo (docs/ideas.json).

No usa IA: son solo cuentas sobre el catálogo ya clasificado. Sirve para ver de un
vistazo qué hay en cada dominio y dónde hay huecos:

- Por dominio: cuántos repos hay de cada tipo, qué parte tiene licencia libre y
  semáforo verde, los más destacados y las novedades.
- Huecos por tema (topic de GitHub): temas en los que hay muchas skills o programas
  pero pocos servidores MCP, o al revés. Cada hueco es una idea: «crea el que falta».
- Combinaciones de dominios: cuántos repos tocan dos dominios a la vez.

Lo llama generar_web.py; también se puede probar suelto con un catálogo:
    python scripts/ideas.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import combinations

TIPOS = ("mcp", "skill", "programa")
DOMINIOS = ("construccion_energia", "finanzas_inversion", "deporte_geodatos",
            "documentos_productividad")

MIN_REPOS_TEMA = 12        # un tema necesita al menos esto para contar como hueco
MIN_REPOS_TEMA_DOMINIO = 6 # dentro de un dominio (hay menos repos)
UMBRAL_HUECO = 0.25        # «pocos»: la proporción del tipo escaso es ≤ 25 % de la del abundante
MAX_HUECOS = 7             # por cada tipo que falta
MAX_HUECOS_DOMINIO = 5
PARES = (("skill", "mcp"), ("programa", "mcp"), ("mcp", "skill"), ("programa", "skill"))
TOP = 5

# Topics que no dicen de qué trata un repo (herramienta, lenguaje, marca, formato…).
TEMAS_GENERICOS = {
    "ai", "api", "automation", "bot", "chatbot", "cli", "cloud", "code", "coding",
    "csharp", "dashboard", "database", "desktop-app", "developer-tools", "devops",
    "devtools", "docker", "dotnet", "electron", "framework", "frontend", "backend",
    "fullstack", "git", "github", "go", "golang", "html", "java", "javascript", "json",
    "kotlin", "library", "linux", "local-first", "macos", "markdown", "memory", "mobile",
    "monorepo", "nextjs", "nodejs", "node", "npm", "open-source", "opensource", "php",
    "plugin", "plugins", "python", "react", "ruby", "rust", "sdk", "security", "self-hosted",
    "server", "sqlite", "swift", "terminal", "tool", "tools", "typescript", "ui", "vscode",
    "web", "windows", "workflow", "yaml", "productivity", "testing", "template",
    "knowledge-graph", "knowledge-base", "code-review", "debugging", "docs",
    "fastapi", "tauri", "tui", "langchain", "langgraph", "llamaindex", "postgresql",
    "postgres", "mysql", "redis", "mongodb", "cloudflare", "cloudflare-workers", "aws",
    "azure", "gcp", "vercel", "supabase", "observability", "a2a", "modelcontextprotocol",
    "privacy", "embeddings", "vector-search", "semantic-search", "vector-database",
    "openapi", "graphql", "grpc", "websocket", "oauth", "stdio", "sse", "http", "rest",
    "rest-api", "sandbox", "wasm", "webassembly", "android", "ios", "flutter", "kubernetes",
    "k8s", "terraform", "ansible", "nginx", "jupyter", "pandas", "numpy", "pytorch",
    "tensorflow", "machine-learning", "deep-learning", "nlp", "data-science", "devcontainer",
    "ci-cd", "cicd", "github-actions", "mcp-gateway", "gateway", "proxy", "router",
    "monitoring", "logging", "performance", "context", "context-engineering", "multimodal",
    "chat", "tts", "stt", "chinese", "english", "japanese", "korean", "token-usage", "i18n", "llms", "rag-pipeline", "retrieval", "search", "scraping",
}
RE_GENERICO = re.compile(
    r"mcp|skill|claude|agent|anthropic|llm|gpt|openai|copilot|cursor|codex|gemini|vibe|"
    r"prompt|awesome|assistant|opencode|openclaw|antigravity|ollama|deepseek|qwen|kimi|"
    r"context-protocol|^ai-|-ai$|^rag$|orchestrat|harness|hooks?$|slash-command|"
    r"^model-|-model$|^tool-?(use|calling)|^claw|^hermes|^zed|^windsurf|^cline|^roo|"
    r"^kilo|^aider|^goose|^trae|^iflow|^qoder|^amp$|^droid|^factory|^crush|^pi-|-cli$|-sdk$")

ETIQUETA_TIPO = {"mcp": "servidores MCP", "skill": "skills", "programa": "programas"}


def es_tema(topic: str) -> bool:
    return topic not in TEMAS_GENERICOS and not RE_GENERICO.search(topic) and len(topic) > 2


def totales_por_tipo(repos: list[dict]) -> dict[str, int]:
    return {t: max(sum(1 for r in repos if t in r["tipos"]), 1) for t in TIPOS}


def huecos(repos: list[dict], totales: dict[str, int], minimo: int) -> list[dict]:
    """Temas con muchos repos de un tipo y, en proporción, pocos de otro.

    Se compara la proporción de cada tipo (repos del tema / repos de ese tipo en todo
    el catálogo), no las cifras: hay el doble de servidores MCP que de skills, y
    comparando cifras todos los huecos saldrían en el mismo sentido.
    Cada hueco dice qué tipo abunda («sobra») y cuál falta («falta»): la idea es
    crear lo que falta a partir de lo que ya existe en el otro formato.
    """
    por_tema: dict[str, Counter] = {}
    for r in repos:
        tipos = [t for t in r["tipos"] if t in TIPOS]
        for tema in {t.lower() for t in r.get("topics", []) if es_tema(t.lower())}:
            c = por_tema.setdefault(tema, Counter())
            for t in tipos:
                c[t] += 1
    mejores: dict[str, dict] = {}
    for tema, c in por_tema.items():
        for sobra, falta in PARES:
            if c[sobra] < minimo:
                continue
            proporcion = (c[falta] / totales[falta]) / (c[sobra] / totales[sobra])
            if proporcion <= UMBRAL_HUECO and (tema not in mejores
                                               or c[sobra] > mejores[tema]["n"][mejores[tema]["sobra"]]):
                mejores[tema] = {"tema": tema, "sobra": sobra, "falta": falta,
                                 "n": {t: c[t] for t in TIPOS}}
    return sorted(mejores.values(), key=lambda h: -h["n"][h["sobra"]])


def huecos_globales(repos: list[dict], totales: dict[str, int]) -> list[dict]:
    """Los mayores huecos por cada tipo que falta (servidores MCP / skills)."""
    todos = huecos(repos, totales, MIN_REPOS_TEMA)
    return [h for falta in ("mcp", "skill")
            for h in [x for x in todos if x["falta"] == falta][:MAX_HUECOS]]


def resumen_repo(r: dict, sb: dict[str, int]) -> dict:
    return {"n": r["nombre"], "d": r.get("descripcion_es") or r.get("descripcion") or "",
            "s": r["estrellas"], "t": r["tipos"], "sm": r["semaforo"]["color"][0],
            "sb": sb.get(r["nombre"].lower(), 0)}


def calcular(repos: list[dict], sb: dict[str, int], nuevos: set[str]) -> dict:
    """Panorama del catálogo.

    repos: catálogo clasificado; sb: estrellas ganadas por repo (clave en minúsculas);
    nuevos: claves en minúsculas de los repos nuevos del mes.
    """
    totales = totales_por_tipo(repos)
    por_dominio = {}
    for dom in DOMINIOS:
        de_dominio = [r for r in repos if dom in r["dominios"]]
        por_estrellas = sorted(de_dominio, key=lambda r: -r["estrellas"])
        recientes = [r for r in por_estrellas if r["nombre"].lower() in nuevos]
        h = huecos(de_dominio, totales, MIN_REPOS_TEMA_DOMINIO)[:MAX_HUECOS_DOMINIO]
        por_dominio[dom] = {
            "total": len(de_dominio),
            "tipos": {t: sum(1 for r in de_dominio if t in r["tipos"]) for t in TIPOS},
            "libres": sum(1 for r in de_dominio if r["tipo_licencia"] == "libre"),
            "verdes": sum(1 for r in de_dominio if r["semaforo"]["color"] == "verde"),
            "mejores": [resumen_repo(r, sb) for r in por_estrellas[:TOP]],
            "nuevos": [resumen_repo(r, sb) for r in recientes[:TOP]],
            "huecos": h,
        }
    combinaciones = []
    for a, b in combinations(DOMINIOS, 2):
        n = sum(1 for r in repos if a in r["dominios"] and b in r["dominios"])
        combinaciones.append({"dominios": [a, b], "total": n})
    return {
        "total": len(repos),
        "dominios": por_dominio,
        "huecos": huecos_globales(repos, totales),
        "combinaciones": sorted(combinaciones, key=lambda c: c["total"]),
    }


if __name__ == "__main__":
    from comun import RAIZ, preparar_consola

    preparar_consola()
    datos = json.loads((RAIZ / "data" / "catalogo.json").read_text(encoding="utf-8"))
    panorama = calcular(datos["repos"], {}, set())
    print(json.dumps(panorama, ensure_ascii=False, indent=2)[:3000])
