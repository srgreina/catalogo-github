# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Catálogo mensual de servidores MCP, skills de Claude y programas públicos de GitHub.
Web: https://srgreina.github.io/catalogo-github/ (repo público `srgreina/catalogo-github`).

## Cómo trabajar con el usuario

- Todo en español: código (identificadores, comentarios), commits y mensajes.
- Antes de crear o modificar archivos: resumen de lo que se va a hacer y esperar confirmación,
  salvo que el usuario ya haya dado permiso para esa tarea.
- Preguntas de una en una, siempre con una opción recomendada.

## Flujo de datos

El workflow `.github/workflows/mensual.yml` (día 1 de cada mes a las 03:37 UTC, y lanzable
a mano con la casilla «completa») ejecuta en orden:

| Script | Lee | Escribe |
|---|---|---|
| `recopilar_github.py` | API de búsqueda (topics MCP/skills/Claude, ≥5★) + `data/estado_github.json` | `data/raw/github.json`, estado |
| `recopilar_registro_mcp.py` | registry.modelcontextprotocol.io (cursor, `version=latest`) | `data/raw/registro_mcp.json` |
| `recopilar_awesome.py` | README de 7 listas awesome | `data/raw/awesome.json` |
| `unir.py` | los tres anteriores + GraphQL para repos nuevos + `data/descartes.json` | `data/raw/unido.json`, descartes |
| `clasificar.py` | `unido.json` | `data/catalogo.json` (tipo, dominio, licencia, semáforo) |
| `traducir.py` | `catalogo.json` + `data/cache_traducciones.json` | los mismos |
| `generar_web.py` | `catalogo.json` + `data/historico.json` | `docs/datos.json`, `docs/detalles/*.json`, `data/novedades.json`, histórico |

`comun.py` reúne peticiones con reintentos, GraphQL por lotes, filtros de descarte y utilidades.

## Comandos y verificación

No hay tests ni linter. Se verifica así:

```bash
python -m py_compile scripts/*.py                    # sintaxis
python scripts/recopilar_github.py --limite 50       # un script, sin token y con límite (no toca el estado)
python scripts/unir.py --max-consultas 20            # sin token: REST de uno en uno (60/h)
python scripts/traducir.py --limite 50               # requiere ctranslate2 + sentencepiece
python -m http.server -d docs                        # ver la web en http://localhost:8000
```

Los scripts se ejecutan desde la raíz o desde `scripts/` (importan `comun` por ruta
relativa al propio script). `GITHUB_TOKEN` en el entorno activa GraphQL y 30 búsquedas/min.

Workflow y resultados en GitHub:

```bash
gh workflow run mensual.yml -R srgreina/catalogo-github              # -f completa=true: búsqueda completa
gh run list -R srgreina/catalogo-github -L 3
gh run view <id> -R srgreina/catalogo-github --log | grep -E "Búsqueda (incr|compl)|Encontrados:|Total unido|Traducciones nuevas|Repos en la web|Errores de GraphQL"
```

Esas líneas de resumen las imprime cada script al terminar; son la forma de comprobar
una ejecución real.

## Contratos entre ficheros

**Campos de `docs/datos.json`** (los escribe `generar_web.py`, los lee `docs/app.js`; cambiar
un nombre exige cambiarlo en los dos):

| Lista (`datos.json`) | | Ficha (`detalles/xx.json`) | |
|---|---|---|---|
| `n` nombre `owner/repo` | `l` licencia SPDX | `f` forks | `o` descripción original |
| `d` descripción (es) | `lt` libre/otra/sin_licencia | `i` incidencias | `tp` topics |
| `t` tipos | `c` creado (AAAA-MM-DD) | `sp` puntos | `lg` lenguaje |
| `m` dominios (sin «otros») | `p` último push | `mo` motivos | `w` web |
| `s` estrellas | `sm` semáforo v/a/r | | |
| `fu` fuentes | `org`, `nv`, `sb` opcionales | | |

**Novedades y subidas** (`generar_web.py` + `app.js`): `historico.json` guarda `base` (fecha
de la primera ejecución) y, por repo, `primera` aparición y las últimas 8 instantáneas de
estrellas. Un repo es nuevo (`nv`) si `primera > base` y tiene menos de 25 días; `sb` son
las estrellas ganadas desde la instantánea de hace ≥25 días (solo si es positiva). 25 días
y no 30: el mes más corto tiene 28, y así una ejecución manual a mitad de mes no vacía
las novedades. Mientras `primera_ejecucion` sea verdadero, la web explica que aún no hay
novedades.

**Ahorro de tiempo** (antes: búsqueda 50 min + unir 41 min):
- `recopilar_github.py` es incremental: con `data/estado_github.json` y una búsqueda
  completa de hace <85 días, solo busca `pushed:>=` (ejecución anterior − 3 días) y
  conserva el resto del estado, con sus estrellas sin actualizar. Sin estado, con
  `--completa` o pasados 85 días, busca todo. `--limite`/`--topics` no tocan el estado.
- `unir.py` no vuelve a consultar durante 90 días los repos de `data/descartes.json`
  (salvo «pocas estrellas» si ahora están en una lista awesome). Los repos que faltan
  por un error de GraphQL (`fallidos` de `obtener_repos`) no se recuerdan como
  inexistentes.
- Ambos ficheros se escriben con `guardar_por_lineas` (un repo por línea) para que
  git solo guarde lo que cambia.

## Reglas del catálogo (decididas por el usuario)

- Mínimo 5★ para búsqueda y registro MCP; sin mínimo para listas awesome.
- Siempre fuera los archivados; los inactivos (6 meses sin push) solo si tienen <20★.
- Servidores del registro sin repo en GitHub: excluidos.
- Licencia: «libre» / «otra» / «sin licencia (no reutilizable)».
- Dominios por palabras clave (`DOMINIOS` en `clasificar.py`), evitando términos ambiguos
  («architecture», «training», «maps», «stock»…).
- Semáforo por puntos, siempre presentado como **orientativo, no análisis de seguridad**.
- «Skills en subida» usa estrellas de GitHub ganadas en el mes (no hay datos de instalaciones).
- Ejecución mensual (decidido el 2026-11-23 para reducir tiempo de Actions).

## Qué se guarda en git y qué no

- En el repo: código, `docs/` (web), `data/historico.json`, `data/novedades.json`,
  `data/cache_traducciones.json`, `data/estado_github.json`, `data/descartes.json`
  (los actualiza el workflow con un commit).
- Fuera del repo (`.gitignore`): `data/raw/`, `data/catalogo.json`, `docs/datos.json`,
  `docs/detalles/`, `.venv/`, `.argos/`. La web se publica con `upload-pages-artifact` +
  `deploy-pages` (Pages en modo «GitHub Actions»), no desde la rama.
- No subir datos de pruebas locales: sobrescribirían el histórico real.

## Decisiones técnicas y trampas conocidas

- **Traducción**: modelos de Argos usados directamente con CTranslate2 + SentencePiece
  (`int8`, `beam_size=2`, lotes de 64). No usar la librería `argostranslate`: arrastra
  PyTorch (~1 GB) y es ~3 veces más lenta. Modelos en `.argos/` (caché de Actions,
  clave `argos-modelos-v1`); el servidor argos-net.com es muy lento descargando.
  En Actions traduce ~15 textos/s; `--max-minutos` evita pasar del límite de 6 h.
- **Tamaño de la web**: `datos.json` solo lleva lo necesario para lista/búsqueda/filtros
  (~330 B por repo, ~4 MB comprimido con ~42.000 repos); el resto va en 256 ficheros
  `docs/detalles/xx.json` elegidos por SHA-1 del nombre en minúsculas. La regla está
  duplicada en `generar_web.py` (`trozo`) y `docs/app.js` (`detalle`): cambiar ambas.
- **Fuentes descartadas**: skills.sh exige token OIDC de Vercel. La búsqueda de código
  de `SKILL.md` (`recopilar_skillmd.py`) no está en el workflow: ~7,7 M de ficheros y el
  token automático de Actions apenas tiene cupo para la búsqueda de código.
- **Ejecución programada**: no usar el minuto 0 en el cron (GitHub retrasa o descarta).

## Entorno local (Windows 11)

- El PC tiene poca RAM libre: no hacer la traducción completa en local.
- `gh` está en `C:\Program Files\GitHub CLI\gh.exe` con sesión iniciada.
- La sesión puede activar `.venv` (solo `requests`, `ctranslate2`, `sentencepiece`).
  Playwright (para capturas de la web con Edge, `channel="msedge"`) está en el Python
  general: `C:\Users\srgre\AppData\Local\Programs\Python\Python312\python.exe`.
