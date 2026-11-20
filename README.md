# catalogo-github
Catálogo semanal de MCP, skills y programas públicos de GitHub

> Proyecto en construcción (fase 2: varias fuentes y deduplicado).

## Qué recoge

| Fuente | Qué aporta | Filtro de estrellas |
|---|---|---|
| Búsqueda de GitHub por topics (MCP, skills, Claude Code) | El grueso del catálogo | ≥ 5 |
| [Registro oficial de MCP](https://registry.modelcontextprotocol.io) | Servidores publicados oficialmente (solo los que tienen repo en GitHub) | ≥ 5 |
| Listas awesome de MCP y skills | Repos seleccionados a mano | ninguno |

En todas las fuentes se descartan:

- los repos archivados;
- los inactivos (sin push en 6 meses) que además tienen menos de 20 estrellas.

Pendiente: skills.sh (su API exige un token OIDC de Vercel) y la búsqueda de
código de `SKILL.md`.

## Uso en local

```bash
pip install -r requirements.txt
python scripts/recopilar_github.py --limite 50     # búsqueda (prueba rápida)
python scripts/recopilar_registro_mcp.py           # registro MCP
python scripts/recopilar_awesome.py                # listas awesome
python scripts/unir.py --max-consultas 20          # unión (prueba sin token)
```

Si existe la variable de entorno `GITHUB_TOKEN`, los scripts la usan (30
búsquedas por minuto y consultas por GraphQL de 50 repos a la vez). Sin ella,
la unión consulta los repos de uno en uno (60 por hora), así que solo sirve
para pruebas. Los resultados intermedios se guardan en `data/raw/` (no se
suben al repo).

## Estructura

- `scripts/` — scripts de recopilación y procesado.
- `data/` — datos generados.
