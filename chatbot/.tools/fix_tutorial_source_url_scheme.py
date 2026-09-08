"""
Script de una sola ejecucion (one-time data fix) para chatbot/data/vector_docstore.json.

Contexto (ver investigacion de citas muertas en RagSourcesDrawer):
  - 101 de 256 paginas de Tutorial tienen `metadata.source_url` guardado con
    esquema `http://` en vez de `https://` para el dominio
    controlsanitario.gob.ec. Ese dominio no responde en el puerto 80
    (ConnectTimeout confirmado), asi que esas 101 citas quedan como enlaces
    muertos en la UI (RagSourcesDrawer.jsx -> officialUrl).
  - 4 de esas paginas ademas tienen una entrada DUPLICADA en el docstore:
    una con esquema http y otra con https para la MISMA pagina real (mismo
    contenido `text`, solo cambia el id porque tutorial_ingestion.py no
    normalizaba el esquema antes de generar el hash del id via
    scrape_servicios.stable_id()).

Este script corrige el dato ya horneado en vector_docstore.json (no
requiere re-scrapear ni re-ingestar, que es costoso). Es el equivalente
para Tutorial del fix que se aplico directamente a los datos de Normativa
para las 145 URLs de esa migracion anterior: se parchea el JSON in-place.

Que hace, en orden:
  1. Carga chatbot/data/vector_docstore.json.
  2. Detecta grupos de entradas "tutorial:*" que comparten la misma URL
     canonica (sin esquema, sin barra final). Para cada grupo con mas de
     una entrada:
       - Si el texto (`text`) es IDENTICO entre todas las entradas del
         grupo (verificado, no asumido), se conserva la entrada con
         `captured_at` mas antiguo (mismo criterio que ya usa el scraper:
         "la PRIMERA vez que se descubre una URL fija su version
         definitiva", ver scrape_servicios.py) y se eliminan las demas.
       - Si el texto DIFIERE, no se borra nada: se imprime una advertencia
         para revision manual (evita perder contenido real).
  3. Para toda entrada "tutorial:*" que sobreviva el paso 2, si su
     `metadata.source_url` apunta a controlsanitario.gob.ec (con o sin
     "www.") con esquema `http://`, se reescribe a `https://`.
  4. Escribe el resultado de vuelta en el mismo archivo (mismo formato de
     serializacion que usa chatbot/vector_ingest.py:
     json.dump(doc, f, ensure_ascii=False), sin indentacion, para no
     inflar el diff con cambios de formato irrelevantes).
  5. Antes de sobreescribir, guarda un backup
     "vector_docstore.json.bak-pre-scheme-fix" (el archivo no esta bajo
     control de version, asi que este es el unico respaldo disponible).

Uso:
    python chatbot/.tools/fix_tutorial_source_url_scheme.py [--dry-run]

--dry-run imprime que haria sin escribir nada a disco.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

CHATBOT_DIR = Path(__file__).resolve().parent.parent
DOCSTORE_PATH = CHATBOT_DIR / "data" / "vector_docstore.json"
BACKUP_PATH = CHATBOT_DIR / "data" / "vector_docstore.json.bak-pre-scheme-fix"

_TARGET_HOSTS = {"controlsanitario.gob.ec", "www.controlsanitario.gob.ec"}


def _canonical_for_dedup(url: str) -> str:
    """URL canonica solo para detectar duplicados por esquema (no muta datos):
    quita esquema y barra final, pero CONSERVA el query string (dos paginas
    con distinto '?p=...' son paginas distintas, no un duplicado de
    esquema; verificado contra un falso positivo real en la data:
    'https://www.controlsanitario.gob.ec' (home) vs
    'https://www.controlsanitario.gob.ec/?p=28121&preview=true', que sin
    el query string colapsan al mismo canonico pero son paginas con texto
    totalmente distinto). No es la misma funcion que
    scrape_servicios.canonical_url() (esa se usa en el scraper, esta es
    local a este script de reparacion de datos)."""
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.netloc.lower()}{path}{query}"


def _needs_scheme_fix(url: str) -> bool:
    if not url or not url.startswith("http://"):
        return False
    parsed = urlparse(url)
    return parsed.netloc.lower() in _TARGET_HOSTS


def _fix_scheme(url: str) -> str:
    return "https://" + url[len("http://"):]


def find_duplicate_groups(docstore: dict) -> dict[str, list[str]]:
    """Agrupa claves 'tutorial:*' por URL canonica (sin esquema). Devuelve
    solo los grupos con mas de una entrada."""
    groups: dict[str, list[str]] = {}
    for key, entry in docstore.items():
        if not key.startswith("tutorial:"):
            continue
        source_url = (entry.get("metadata") or {}).get("source_url") or ""
        canon = _canonical_for_dedup(source_url)
        if not canon:
            continue
        groups.setdefault(canon, []).append(key)
    return {canon: keys for canon, keys in groups.items() if len(keys) > 1}


def resolve_duplicates(docstore: dict, groups: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Decide que claves eliminar por cada grupo duplicado.

    Returns:
        (keys_to_delete, warnings): keys_to_delete es la lista de claves a
        borrar del docstore; warnings son grupos que NO se tocaron porque
        su texto difiere entre entradas (requieren revision manual).
    """
    keys_to_delete: list[str] = []
    warnings: list[str] = []

    for canon, keys in groups.items():
        texts = {docstore[k].get("text") for k in keys}
        if len(texts) > 1:
            warnings.append(
                f"[ADVERTENCIA] Grupo '{canon}' tiene {len(keys)} entradas con "
                f"TEXTO DISTINTO ({keys}); no se fusiona automaticamente."
            )
            continue

        # Texto identico: conservar la entrada con captured_at mas antiguo
        # (mismo criterio de "primera aparicion gana" que ya usa el
        # scraper), eliminar el resto.
        def _captured_at(key: str) -> str:
            return (docstore[key].get("metadata") or {}).get("captured_at") or ""

        keys_sorted = sorted(keys, key=_captured_at)
        keep_key = keys_sorted[0]
        drop_keys = keys_sorted[1:]
        keys_to_delete.extend(drop_keys)

    return keys_to_delete, warnings


def fix_schemes(docstore: dict) -> list[str]:
    """Normaliza a https:// el metadata.source_url de toda entrada
    'tutorial:*' que apunte a controlsanitario.gob.ec por http://. Devuelve
    la lista de claves modificadas."""
    fixed_keys: list[str] = []
    for key, entry in docstore.items():
        if not key.startswith("tutorial:"):
            continue
        metadata = entry.get("metadata") or {}
        source_url = metadata.get("source_url") or ""
        if _needs_scheme_fix(source_url):
            metadata["source_url"] = _fix_scheme(source_url)
            fixed_keys.append(key)
    return fixed_keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="No escribe cambios a disco; solo imprime el diagnostico.",
    )
    args = parser.parse_args()

    print(f"[INFO] Cargando '{DOCSTORE_PATH}'...")
    with DOCSTORE_PATH.open(encoding="utf-8") as f:
        docstore = json.load(f)
    print(f"[INFO] {len(docstore)} entradas cargadas.")

    tutorial_keys = [k for k in docstore if k.startswith("tutorial:")]
    before_bad = sum(
        1 for k in tutorial_keys
        if _needs_scheme_fix((docstore[k].get("metadata") or {}).get("source_url") or "")
    )
    print(f"[INFO] Entradas Tutorial: {len(tutorial_keys)}")
    print(f"[INFO] Entradas con source_url http:// (controlsanitario.gob.ec) ANTES: {before_bad}")

    groups = find_duplicate_groups(docstore)
    print(f"[INFO] Grupos de URL canonica duplicada detectados: {len(groups)}")

    keys_to_delete, warnings = resolve_duplicates(docstore, groups)
    for w in warnings:
        print(w)
    print(f"[INFO] Entradas duplicadas a eliminar (texto identico verificado): {len(keys_to_delete)}")
    for k in keys_to_delete:
        print(f"       - eliminando '{k}'")

    fixed_keys = fix_schemes(docstore)
    print(f"[INFO] Entradas con source_url reescrito a https://: {len(fixed_keys)}")

    for k in keys_to_delete:
        del docstore[k]

    tutorial_keys_after = [k for k in docstore if k.startswith("tutorial:")]
    after_bad = sum(
        1 for k in tutorial_keys_after
        if _needs_scheme_fix((docstore[k].get("metadata") or {}).get("source_url") or "")
    )
    print(f"[INFO] Entradas Tutorial DESPUES: {len(tutorial_keys_after)}")
    print(f"[INFO] Entradas con source_url http:// (controlsanitario.gob.ec) DESPUES: {after_bad}")

    if args.dry_run:
        print("[INFO] --dry-run activo: no se escribio nada a disco.")
        return 0

    print(f"[INFO] Escribiendo backup en '{BACKUP_PATH}'...")
    import shutil
    shutil.copy2(DOCSTORE_PATH, BACKUP_PATH)

    print(f"[INFO] Escribiendo '{DOCSTORE_PATH}'...")
    with DOCSTORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(docstore, f, ensure_ascii=False)

    print("[INFO] Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
