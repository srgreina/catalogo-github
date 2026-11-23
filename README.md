# catalogo-github
Catálogo mensual de MCP, skills y programas públicos de GitHub

**Web: https://srgreina.github.io/catalogo-github/** — se actualiza sola el día 1
de cada mes (workflow «Catálogo mensual», también lanzable a mano desde Actions).

## Qué recoge

| Fuente | Qué aporta | Filtro de estrellas |
|---|---|---|
| Búsqueda de GitHub por topics (MCP, skills, Claude Code) | El grueso del catálogo | ≥ 5 |
| [Registro oficial de MCP](https://registry.modelcontextprotocol.io) | Servidores publicados oficialmente (solo los que tienen repo en GitHub) | ≥ 5 |
| Listas awesome de MCP y skills | Repos seleccionados a mano | ninguno |

En todas las fuentes se descartan:

- los repos archivados;
- los inactivos (sin push en 6 meses) que además tienen menos de 20 estrellas.

Para que cada ejecución tarde menos:

- **Búsqueda incremental**: `data/estado_github.json` guarda los repos de la
  ejecución anterior. Solo se buscan los que han tenido actividad desde entonces;
  el resto conserva sus datos. Cada ~3 meses (o lanzando el workflow con la
  casilla «Búsqueda completa») se busca todo de nuevo y se actualizan las
  estrellas de los inactivos.
- **Descartes recordados**: `data/descartes.json` guarda los repos del registro y
  de las listas que se descartaron (pocas estrellas, archivados, inexistentes) y
  no se vuelven a consultar durante 90 días.

No se usan:

- **skills.sh**: su API exige un token OIDC de Vercel.
- **Búsqueda de código de `SKILL.md`**: hay ~7,7 millones de ficheros y la API
  solo permite 10 consultas/min con 1.000 resultados cada una (más de 13 h por
  ejecución), y el token automático de Actions apenas tiene cupo para ella. El
  script `scripts/recopilar_skillmd.py` se conserva, pero no está en el workflow.

## Uso en local

```bash
pip install -r requirements.txt
python scripts/recopilar_github.py --limite 50     # búsqueda (prueba rápida, no toca el estado)
python scripts/recopilar_registro_mcp.py           # registro MCP
python scripts/recopilar_awesome.py                # listas awesome
python scripts/unir.py --max-consultas 20          # unión (prueba sin token)
python scripts/clasificar.py                       # tipo, dominio, licencia y semáforo
python scripts/traducir.py --max-minutos 30        # descripciones al español
python scripts/generar_web.py                      # datos de la web y novedades
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

## Web

La web estática está en `docs/` (HTML, CSS y JS sin framework) y se publica con
GitHub Pages. `python scripts/generar_web.py` prepara sus datos:

- `docs/datos.json`: lo necesario para la lista, el buscador y los filtros.
- `docs/detalles/00..ff.json`: el resto de cada ficha, repartido en 256 ficheros
  que la web descarga solo al abrir un repo.
- `data/historico.json`: primera aparición de cada repo y sus estrellas de las
  últimas ejecuciones. De ahí salen las **novedades del mes**
  (`data/novedades.json`) y las **skills en subida** (estrellas ganadas en el mes).

Para verla en local: `python -m http.server -d docs` y abrir http://localhost:8000.

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
