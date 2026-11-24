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
| [skills.sh](https://skills.sh) (mapas del sitio) | Repos con skills publicadas en ese directorio (solo nombres de repos, no su contenido) | ≥ 5 |

En todas las fuentes se descartan:

- los repos archivados;
- los inactivos (sin push en 6 meses) que además tienen menos de 20 estrellas.

Para que cada ejecución tarde menos:

- **Búsqueda incremental**: `data/estado_github.json` guarda los repos de la
  ejecución anterior. Solo se buscan los que han tenido actividad desde entonces;
  el resto conserva sus datos. Cada ~3 meses (o lanzando el workflow con la
  casilla «Búsqueda completa») se busca todo de nuevo y se actualizan las
  estrellas de los inactivos.
  Además, las skills con ≥ 50 estrellas se refrescan cada vez por GraphQL (unos
  5 min), porque pueden ganar estrellas sin que nadie haga cambios.
- **Descartes recordados**: `data/descartes.json` guarda los repos del registro y
  de las listas que se descartaron (pocas estrellas, archivados, inexistentes) y
  no se vuelven a consultar durante 90 días.
- **Modelos de traducción en una Release**: la caché de Actions caduca a los 7 días
  sin usarse, así que con ejecución mensual siempre habría que bajarlos de
  argos-net.com (~45 min). Se guardan en la Release `modelos-argos` y el workflow
  los baja de ahí en segundos si no hay caché.

Seguridad de la ejecución:

- Si el catálogo baja más de un 15 % respecto al mes anterior, `generar_web.py`
  falla y no se guarda ni se publica nada (`--forzar` lo salta a mano).
- Al terminar, el workflow crea un Issue que menciona al propietario («Catálogo
  actualizado» o «FALLÓ…»), lo que llega como notificación por correo y por la app
  móvil de GitHub.

No se usan:

- **API de skills.sh**: exige un token OIDC de Vercel (sí se usan sus mapas del sitio, que son públicos).
- **Búsqueda de código de `SKILL.md`**: hay ~7,7 millones de ficheros y la API
  solo permite 10 consultas/min con 1.000 resultados cada una (más de 13 h por
  ejecución), y el token automático de Actions apenas tiene cupo para ella. El
  script se probó y se borró; sigue en el historial de git (commit `d87175a` y
  anteriores) por si se quisiera retomar.

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

**Buscador en español e inglés**: lo que escribes en español se amplía con equivalentes en
inglés (`docs/glosario.json`, ~380 términos revisados a mano: «finanzas» → finance, financial,
fintech) y se busca también en los topics y en la descripción original (`docs/indice_en.json`,
que la web carga en segundo plano). Bajo el cuadro se ve qué se ha ampliado y un botón
«Solo español». El orden «Más relevantes» puntúa más el nombre que la descripción y los topics.
Para añadir términos basta con editar el glosario.

Funciones de la web: buscador y filtros (que se guardan en la dirección `#…` para
compartirlos y se recuerdan en el navegador), orden por estrellas, semáforo,
actividad, estrellas del mes, nombre; **descarga de los resultados en CSV**
(separador `;`, se abre bien con Excel); **favoritos** guardados en el navegador;
y, en los servidores del registro oficial MCP, el bloque «Cómo usarlo» con su
paquete (npm, pypi…) y su servidor remoto.

**Panel lateral con el resumen de cada repo**: al pulsar un repo se abre un panel a la derecha
(hoja a pantalla completa en el móvil) con **para qué sirve**, **características**, **cómo usarlo**
(comandos de instalación), **rendimiento** (solo las cifras que afirma el propio README, marcadas
como no verificadas), **cuándo usar** una skill (campo `description` de su `SKILL.md`), las
**skills que tiene en skills.sh** (con enlace a cada una), el semáforo y los datos. Lo genera
`scripts/resumir.py` **sin IA**, con reglas sobre el README, para los repos con ≥ 50 estrellas
(~11.700), y lo traduce con Argos; por eso puede tener errores y el panel lo avisa. Se guarda en
`data/cache_resumenes.json` y solo se vuelve a bajar el README de un repo cada 90 días si ha
habido cambios.

**Pestaña «Ideas»**: panorama para buscar ideas de programas. No usa IA, son solo
cuentas que calcula `scripts/ideas.py` cada mes (`docs/ideas.json`): por dominio, cuántos
repos hay de cada tipo, los más destacados, las novedades y los **huecos** (temas con
muchos repos de un tipo y, en proporción, pocos de otro, p. ej. muchas skills de un tema
y casi ningún servidor MCP), más los cruces entre dominios. Además, el botón **«Ideas con
Claude»** (en la barra de resultados de cualquier búsqueda, y por dominio en la pestaña
Ideas) copia al portapapeles un texto con los 25 mejores resultados y una petición de
ideas, para pegarlo en Claude.

Para verla en local: `python -m http.server -d docs` y abrir http://localhost:8000.
Necesita `docs/datos.json` y `docs/detalles/` (`python scripts/generar_web.py`; ojo:
escribe también `data/historico.json`, que no hay que subir).

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
