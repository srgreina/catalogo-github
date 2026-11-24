"""Traduce al español las descripciones del catálogo con los modelos de Argos Translate.

Usa directamente los modelos de Argos (offline, sin clave) con CTranslate2 y
SentencePiece, traduciendo por lotes: es varias veces más rápido que la
librería argostranslate y no necesita instalar PyTorch.

- Lee y actualiza data/catalogo.json, añadiendo a cada repo «descripcion_es» e
  «idioma» (idioma detectado del original).
- Caché en data/cache_traducciones.json: la clave es una huella del texto
  original, así que solo se traduce lo nuevo o modificado. Las entradas que ya
  no se usan se eliminan.
- Idiomas: español → se deja igual; inglés → español; chino, ruso y japonés →
  inglés → español; otros (p. ej. coreano) → se deja el original.
- Tope de tiempo (--max-minutos): lo que no dé tiempo a traducir se muestra en
  el idioma original y se traduce en la siguiente ejecución.
- Modelos: se descargan solos la primera vez en .argos/ (o en ARGOS_DIR).

Uso:
    python scripts/traducir.py
    python scripts/traducir.py --max-minutos 120
    python scripts/traducir.py --limite 50      # prueba: como máximo 50 textos nuevos
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

import requests

from comun import RAIZ, preparar_consola

CATALOGO = RAIZ / "data" / "catalogo.json"
CACHE = RAIZ / "data" / "cache_traducciones.json"
DIR_MODELOS = Path(os.environ.get("ARGOS_DIR", RAIZ / ".argos"))
INDICE_ARGOS = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
A_INGLES = ["zh", "ru", "ja"]          # idiomas que se traducen pasando por el inglés
LOTE = 64                              # textos por lote
MAX_CARACTERES = 600                   # las descripciones más largas se recortan

# Emojis y símbolos que los modelos no conocen (saldrían como «??»).
RE_EMOJI = re.compile("[\U0001F000-\U0001FFFF←-⇿⌀-⏿①-➿"
                      "⬀-⯿️‍]+")
RE_KANA = re.compile(r"[぀-ヿ]")
RE_HAN = re.compile(r"[一-鿿]")
RE_CIRILICO = re.compile(r"[Ѐ-ӿ]")
RE_HANGUL = re.compile(r"[가-힯]")
PALABRAS_ES = {"el", "la", "los", "las", "de", "del", "para", "con", "que", "una", "un",
               "y", "en", "por", "tu", "sus", "como", "desde", "sin"}
PALABRAS_EN = {"the", "and", "for", "with", "to", "of", "your", "an", "a", "in", "on",
               "from", "that", "this", "is", "by", "any", "via", "using"}


def detectar_idioma(texto: str) -> str:
    if RE_KANA.search(texto):
        return "ja"
    if RE_HAN.search(texto):
        return "zh"
    if RE_HANGUL.search(texto):
        return "ko"
    if RE_CIRILICO.search(texto):
        return "ru"
    palabras = re.findall(r"[a-záéíóúñü]+", texto.lower())
    es = sum(p in PALABRAS_ES for p in palabras) + 2 * sum(c in "ñ¿¡" for c in texto)
    en = sum(p in PALABRAS_EN for p in palabras)
    return "es" if es > en else "en"


def huella(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]


def asegurar_modelo(origen: str, destino: str) -> Path:
    """Descarga y descomprime el modelo de Argos si aún no está."""
    carpeta = DIR_MODELOS / f"{origen}_{destino}"
    if (carpeta / "model").exists():
        return carpeta
    indice = requests.get(INDICE_ARGOS, timeout=60).json()
    paquete = next(p for p in indice if p["from_code"] == origen and p["to_code"] == destino)
    print(f"Descargando modelo {origen}→{destino} ({paquete['links'][0]})…")
    resp = requests.get(paquete["links"][0], timeout=600)
    resp.raise_for_status()
    temporal = DIR_MODELOS / f"_{origen}_{destino}"
    shutil.rmtree(temporal, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(temporal)
    raiz_zip = next(temporal.iterdir())          # el zip trae una carpeta raíz
    shutil.rmtree(carpeta, ignore_errors=True)
    raiz_zip.rename(carpeta)
    shutil.rmtree(temporal, ignore_errors=True)
    return carpeta


class Modelo:
    def __init__(self, origen: str, destino: str):
        import ctranslate2
        import sentencepiece

        carpeta = asegurar_modelo(origen, destino)
        self.sp = sentencepiece.SentencePieceProcessor(
            model_file=str(carpeta / "sentencepiece.model"))
        self.traductor = ctranslate2.Translator(
            str(carpeta / "model"), device="cpu", compute_type="int8",
            intra_threads=os.cpu_count() or 4)

    def traducir(self, textos: list[str]) -> list[str]:
        tokens = self.sp.encode(textos, out_type=str)
        resultados = self.traductor.translate_batch(
            tokens, beam_size=2, max_batch_size=LOTE, max_decoding_length=256)
        # El modelo a veces escribe «&amp;» o «&quot;» en vez del carácter: se convierte.
        return [html.unescape(self.sp.decode(r.hypotheses[0])) for r in resultados]


class Traductor:
    def __init__(self):
        self.modelos: dict[str, Modelo] = {}

    def modelo(self, origen: str, destino: str) -> Modelo:
        clave = f"{origen}_{destino}"
        if clave not in self.modelos:
            self.modelos[clave] = Modelo(origen, destino)
        return self.modelos[clave]

    def traducir(self, textos: list[str], idioma: str) -> list[str]:
        if idioma in A_INGLES:
            textos = self.modelo(idioma, "en").traducir(textos)
        return self.modelo("en", "es").traducir(textos)


def guardar_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=0),
                     encoding="utf-8")


def main() -> None:
    preparar_consola()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-minutos", type=float, default=None,
                        help="tiempo máximo traduciendo; el resto queda para la próxima vez")
    parser.add_argument("--limite", type=int, default=None,
                        help="máximo de textos nuevos a traducir (para pruebas)")
    args = parser.parse_args()

    datos = json.loads(CATALOGO.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    usados: dict[str, str] = {}
    pendientes: dict[str, dict[str, str]] = {}   # idioma → {clave: texto}

    for repo in datos["repos"]:
        original = (repo.get("descripcion") or "").strip()
        repo["idioma"] = detectar_idioma(original) if original else None
        repo["descripcion_es"] = original     # provisional: original hasta tener traducción
        if not original or repo["idioma"] == "es":
            continue
        clave = huella(original)
        if clave in cache:
            usados[clave] = cache[clave]
        elif repo["idioma"] == "en" or repo["idioma"] in A_INGLES:
            limpio = re.sub(r"\s+", " ", RE_EMOJI.sub(" ", original)).strip()
            pendientes.setdefault(repo["idioma"], {})[clave] = limpio[:MAX_CARACTERES] or original

    total_pendientes = sum(len(p) for p in pendientes.values())
    print(f"Descripciones: de caché {len(usados)} · nuevas por traducir {total_pendientes}")

    traductor = Traductor()
    inicio = time.time()
    nuevos = 0
    parado = None
    for idioma, textos in pendientes.items():
        items = list(textos.items())
        for i in range(0, len(items), LOTE):
            if args.limite is not None and nuevos >= args.limite:
                parado = "límite de prueba"
                break
            if args.max_minutos is not None and time.time() - inicio > args.max_minutos * 60:
                parado = "tope de tiempo"
                break
            lote = items[i:i + LOTE]
            if args.limite is not None:
                lote = lote[:args.limite - nuevos]
            traducciones = traductor.traducir([t for _, t in lote], idioma)
            for (clave, _), traduccion in zip(lote, traducciones):
                usados[clave] = traduccion
            nuevos += len(lote)
            if nuevos % (LOTE * 10) < LOTE:
                velocidad = nuevos / (time.time() - inicio)
                print(f"  {nuevos}/{total_pendientes} traducidas ({velocidad:.1f}/s)")
                guardar_cache(usados)          # por si se interrumpe
        if parado:
            break

    for repo in datos["repos"]:
        original = repo["descripcion_es"]
        if original and repo["idioma"] != "es":
            repo["descripcion_es"] = usados.get(huella(original), original)

    eliminadas = len(set(cache) - set(usados))
    guardar_cache(usados)
    CATALOGO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    segundos = time.time() - inicio
    print(f"\nTraducciones nuevas: {nuevos} · total en caché: {len(usados)} · "
          f"eliminadas de la caché: {eliminadas} · {segundos:.0f} s")
    if parado:
        print(f"[{parado}] quedan {total_pendientes - nuevos} por traducir en la próxima ejecución")


if __name__ == "__main__":
    main()
