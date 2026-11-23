# CLAUDE.md — catalogo-github

Catálogo semanal de servidores MCP, skills de Claude y programas públicos de GitHub.
Web: https://srgreina.github.io/catalogo-github/ (repo público `srgreina/catalogo-github`).

## Cómo trabajar con el usuario

- Todo en español: código (identificadores, comentarios), commits y mensajes.
- Antes de crear o modificar archivos: resumen de lo que se va a hacer y esperar confirmación,
  salvo que el usuario ya haya dado permiso para esa tarea.
- Preguntas de una en una, siempre con una opción recomendada.

## Flujo de datos

El workflow `.github/workflows/semanal.yml` (lunes 03:37 UTC y lanzable a mano) ejecuta en orden:

| Script | Lee | Escribe |
|---|---|---|
| `recopilar_github.py` | API de búsqueda (topics MCP/skills/Claude, ≥5★) | `data/raw/github.json` |
| `recopilar_registro_mcp.py` | registry.modelcontextprotocol.io (cursor, `version=latest`) | `data/raw/registro_mcp.json` |
| `recopilar_awesome.py` | README de 7 listas awesome | `data/raw/awesome.json` |
| `unir.py` | los tres anteriores + GraphQL para repos nuevos | `data/raw/unido.json` |
| `clasificar.py` | `unido.json` | `data/catalogo.json` (tipo, dominio, licencia, semáforo) |
| `traducir.py` | `catalogo.json` + `data/cache_traducciones.json` | los mismos |
| `generar_web.py` | `catalogo.json` + `data/historico.json` | `docs/datos.json`, `docs/detalles/*.json`, `data/novedades.json`, histórico |

`comun.py` reúne peticiones con reintentos, GraphQL por lotes, filtros de descarte y utilidades.

## Reglas del catálogo (decididas por el usuario)

- Mínimo 5★ para búsqueda y registro MCP; sin mínimo para listas awesome.
- Siempre fuera los archivados; los inactivos (6 meses sin push) solo si tienen <20★.
- Servidores del registro sin repo en GitHub: excluidos.
- Licencia: «libre» / «otra» / «sin licencia (no reutilizable)».
- Dominios por palabras clave (`DOMINIOS` en `clasificar.py`), evitando términos ambiguos
  («architecture», «training», «maps», «stock»…).
- Semáforo por puntos, siempre presentado como **orientativo, no análisis de seguridad**.
- «Skills en subida» usa estrellas de GitHub ganadas en la semana (no hay datos de instalaciones).

## Qué se guarda en git y qué no

- En el repo: código, `docs/` (web), `data/historico.json`, `data/novedades.json`,
  `data/cache_traducciones.json` (los tres los actualiza el workflow con un commit).
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
- Probar sin token: `recopilar_github.py --limite 50`, `unir.py --max-consultas 20`,
  `traducir.py --limite 50`. Ver la web: `python -m http.server -d docs`.
