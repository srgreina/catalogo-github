# catalogo-github
Catálogo semanal de MCP, skills y programas públicos de GitHub

> Proyecto en construcción (fase 1: recopilación desde GitHub).

## Qué recoge

Repositorios públicos de GitHub con topics relacionados con servidores MCP,
skills de Claude y Claude Code, con al menos 5 estrellas. Se descartan:

- los repos archivados;
- los inactivos (sin push en 6 meses) que además tienen menos de 20 estrellas.

## Uso en local

```bash
pip install -r requirements.txt
python scripts/recopilar_github.py --limite 50     # prueba rápida
python scripts/recopilar_github.py                 # recopilación completa
```

Si existe la variable de entorno `GITHUB_TOKEN`, el script la usa (30 búsquedas
por minuto); sin ella va a 10 por minuto. El resultado se guarda en
`data/raw/github.json`.

## Estructura

- `scripts/` — scripts de recopilación y procesado.
- `data/` — datos generados.
