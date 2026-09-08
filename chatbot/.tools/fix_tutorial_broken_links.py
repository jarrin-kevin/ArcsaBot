"""
Script de una sola ejecucion (one-time data fix) para chatbot/data/vector_docstore.json.

Contexto (ver investigacion de links rotos reproducidos por el chatbot):
  - chatbot/main.py::_build_grounded_prompt mete chunk["text"] tal cual en el
    prompt que recibe el LLM, sin limpiar. 234 de los 252 chunks
    "tutorial:*" tienen URLs embebidas en su texto (la mayoria en formato
    Markdown "[texto del link](url)").
  - chatbot/scraping/link_validation_report.json (generado por
    `python -m chatbot.link_validation`) ya audito esas URLs contra el sitio
    real: marca cada una como "valid"/"redirect"/"broken"/"timeout".
  - El LLM reproduce ese texto tal cual, incluidos los enlaces rotos: un
    usuario puede terminar con un link muerto en la respuesta.

Este script aplica sobre el docstore YA GENERADO (sin re-embeber ni volver a
subir nada a Pinecone: el indice solo guarda id+embedding+metadata,
nunca el texto, ver decision de diseno 3 en chatbot/vector_ingest.py)
la misma limpieza que chatbot/vector_ingest.py ya aplica automaticamente en
cada corrida completa via chatbot.link_validation.strip_broken_links_from_text().

Que hace, en orden:
  1. Carga chatbot/data/vector_docstore.json.
  2. Carga las URLs "broken"/"timeout" del reporte de link_validation.py mas
     reciente en disco (chatbot.link_validation.load_broken_urls()).
  3. Para cada entrada "tutorial:*", limpia su campo "text" con
     chatbot.link_validation.strip_broken_links_from_text(): un enlace
     Markdown roto "[texto](url-rota)" queda como solo "texto"; una URL
     suelta rota se elimina conservando el resto de la frase.
  4. Escribe el resultado de vuelta en el mismo archivo (mismo formato de
     serializacion que usa chatbot/vector_ingest.py:
     json.dump(doc, f, ensure_ascii=False), sin indentacion).
  5. Antes de sobreescribir, guarda un backup
     "vector_docstore.json.bak-pre-broken-links-fix" (el archivo no esta
     bajo control de version, asi que este es el unico respaldo disponible).
  6. Verifica que ninguna de las URLs "broken"/"timeout" siga presente en el
     texto de alguna entrada "tutorial:*" tras la limpieza, e imprime
     cualquier caso residual para revision manual.

Uso:
    python chatbot/.tools/fix_tutorial_broken_links.py [--dry-run]

--dry-run imprime que haria sin escribir nada a disco.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

CHATBOT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CHATBOT_DIR.parent
DOCSTORE_PATH = CHATBOT_DIR / "data" / "vector_docstore.json"
BACKUP_PATH = CHATBOT_DIR / "data" / "vector_docstore.json.bak-pre-broken-links-fix"

sys.path.insert(0, str(REPO_ROOT))

from chatbot.link_validation import (  # noqa: E402
    REPORT_PATH,
    load_broken_urls,
    normalize_url_for_comparison,
    strip_broken_links_from_text,
)


def clean_docstore(docstore: dict, broken_urls: set[str]) -> tuple[int, int, list[str]]:
    """
    Limpia in-place el campo "text" de toda entrada "tutorial:*" del
    docstore. Devuelve (chunks_modificados, links_eliminados, ejemplos)
    donde `ejemplos` son hasta 3 strings "antes -> despues" de chunks
    realmente modificados, para reportar.
    """
    cleaned_chunks = 0
    cleaned_links = 0
    examples: list[str] = []

    for key, entry in docstore.items():
        if not key.startswith("tutorial:"):
            continue
        original_text = entry.get("text") or ""
        new_text, removed = strip_broken_links_from_text(original_text, broken_urls)
        if not removed:
            continue

        cleaned_chunks += 1
        cleaned_links += removed
        entry["text"] = new_text

        if len(examples) < 3:
            examples.append(
                f"[{key}] {removed} enlace(s) eliminado(s):\n"
                f"  ANTES : {original_text[:400]!r}\n"
                f"  DESPUES: {new_text[:400]!r}"
            )

    return cleaned_chunks, cleaned_links, examples


def verify_no_broken_urls_remain(docstore: dict, broken_urls: set[str]) -> list[str]:
    """
    Vuelve a escanear todas las entradas "tutorial:*" ya limpiadas en busca
    de cualquier URL rota que haya sobrevivido (comparacion normalizada,
    igual que la limpieza). Devuelve la lista de hallazgos residuales
    (deberia dar vacia).
    """
    from chatbot.link_validation import extract_links_from_text

    normalized_broken = {normalize_url_for_comparison(u) for u in broken_urls}
    residual: list[str] = []
    for key, entry in docstore.items():
        if not key.startswith("tutorial:"):
            continue
        text = entry.get("text") or ""
        for link in extract_links_from_text(text):
            if normalize_url_for_comparison(link["url"]) in normalized_broken:
                residual.append(f"[{key}] URL rota residual: {link['url']!r}")
    return residual


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
    tutorial_keys = [k for k in docstore if k.startswith("tutorial:")]
    print(f"[INFO] {len(docstore)} entradas totales, {len(tutorial_keys)} 'tutorial:*'.")

    print(f"[INFO] Cargando URLs broken/timeout desde '{REPORT_PATH}'...")
    broken_urls = load_broken_urls(REPORT_PATH)
    if not broken_urls:
        print("[ADVERTENCIA] No hay URLs broken/timeout para limpiar (reporte vacio o ausente). Nada que hacer.")
        return 0

    cleaned_chunks, cleaned_links, examples = clean_docstore(docstore, broken_urls)

    print(f"[INFO] Chunks 'tutorial:*' modificados: {cleaned_chunks}/{len(tutorial_keys)}")
    print(f"[INFO] Enlaces rotos eliminados en total: {cleaned_links}")

    if examples:
        print("\n[INFO] Ejemplos de chunks modificados (antes/despues):\n")
        for example in examples:
            print(example)
            print()

    residual = verify_no_broken_urls_remain(docstore, broken_urls)
    if residual:
        print(f"\n[ADVERTENCIA] {len(residual)} URL(s) rota(s) siguen presentes tras la limpieza (revisar manualmente):")
        for r in residual:
            print(f"  - {r}")
    else:
        print("\n[INFO] Verificacion: 0 URLs broken/timeout residuales en el corpus 'tutorial:*' tras la limpieza.")

    if args.dry_run:
        print("[INFO] --dry-run activo: no se escribio nada a disco.")
        return 0

    if cleaned_chunks == 0:
        print("[INFO] Ningun chunk requirio cambios; no se toca el archivo en disco.")
        return 0

    print(f"[INFO] Escribiendo backup en '{BACKUP_PATH}'...")
    shutil.copy2(DOCSTORE_PATH, BACKUP_PATH)

    print(f"[INFO] Escribiendo '{DOCSTORE_PATH}'...")
    with DOCSTORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(docstore, f, ensure_ascii=False)

    print("[INFO] Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
