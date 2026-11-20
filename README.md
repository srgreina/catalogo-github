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
python scripts/clasificar.py                       # tipo, dominio, licencia y semáforo
python scripts/traducir.py --max-minutos 30        # descripciones al español
```

## Traducción

Las descripciones se traducen al español con los modelos de
[Argos Translate](https://github.com/argosopentech/argos-translate) (offline, sin
clave), ejecutados directamente con CTranslate2 por lotes. El inglés se traduce
directamente; el chino, el ruso y el japonés pasan antes por el inglés.

- Los modelos (~470 MB) se descargan solos la primera vez en `.argos/`.
- `data/cache_traducciones.json` guarda las traducciones: solo se traduce lo nuevo
  o modificado.
- `--max-minutos` limita el tiempo; lo pendiente se muestra en el idioma original
  y se traduce en la siguiente ejecución.

## Clasificación y semáforo

- **Tipo**: lista awesome, skill, servidor MCP o programa (puede tener varios).
- **Dominio**: construcción/ingeniería/energía, finanzas e inversión, deporte/rutas/
  geodatos, documentos y productividad, u «otros». Se decide por palabras clave en
  nombre, descripción y topics (`DOMINIOS` en `scripts/clasificar.py`).
- **Licencia**: uso libre, otra (revisar) o sin licencia (no reutilizable).
- **Semáforo** 🟢🟡🔴: puntuación **orientativa** según antigüedad, estrellas, forks,
  actividad, si es de una organización, si está en el registro oficial MCP, licencia
  e incidencias abiertas. **No es un análisis de seguridad del código.**

Si existe la variable de entorno `GITHUB_TOKEN`, los scripts la usan (30
búsquedas por minuto y consultas por GraphQL de 50 repos a la vez). Sin ella,
la unión consulta los repos de uno en uno (60 por hora), así que solo sirve
para pruebas. Los resultados intermedios se guardan en `data/raw/` (no se
suben al repo).

## Estructura

- `scripts/` — scripts de recopilación y procesado.
- `data/` — datos generados.
