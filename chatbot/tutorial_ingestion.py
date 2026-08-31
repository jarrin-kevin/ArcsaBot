"""
Módulo de limpieza y parsing del corpus de Tutorial (páginas scrapeadas de
https://www.controlsanitario.gob.ec/servicios/).

Este módulo es DISTINTO de chatbot/ingestion.py: parse_normativa() en ese
otro módulo está pensado para Normativa Vigente con estructura legal
Artículo/Numeral/Literal. El contenido de Tutorial no tiene esa estructura
(son guías en lenguaje natural sobre cómo completar un Trámite, ver
CONTEXT.md), así que aquí se define un pipeline de limpieza/parsing propio,
sin tocar ni reutilizar parse_normativa().

Etapas de este módulo:
  1. filter_pages(): decide qué páginas del scrape NO entran al corpus
     ingestionable, y por qué (ver ADR 0004: "flag, don't drop" — en vez de
     saltarlas en silencio, se escribe un reporte explícito de exclusión).
  2. parse_tutorial(): convierte una página sobreviviente en un chunk listo
     para RAG, extrayendo además menciones a Normativa ARCSA (Resoluciones,
     Acuerdos Ministeriales, Decisiones de la CAN) vía regex, para que en un
     trabajo futuro se puedan cruzar contra el Corpus Documental y detectar
     Cita Desactualizada (ese cruce NO se implementa en este módulo).
  3. to_documents(): adaptador delgado hacia llama_index.core.Document,
     igual que el de chatbot/ingestion.py.
  4. run_pipeline(): orquesta las tres etapas anteriores sobre el corpus
     real en disco y reporta conteos.

Este módulo NO hace embeddings ni llamadas a un vector store, y NO modifica
el scraper (chatbot/scraping/scrape_servicios.py) ni chatbot/ingestion.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Rutas por defecto (relativas a la ubicación de este archivo, para que el
# módulo funcione sin importar desde qué directorio se invoque).
# --------------------------------------------------------------------------

SCRAPING_DIR = Path(__file__).resolve().parent / "scraping"
CAPTURE_SUMMARY_PATH = SCRAPING_DIR / "capture_summary.json"
PAGES_DIR = SCRAPING_DIR / "pages"
EXCLUDED_PAGES_REPORT_PATH = SCRAPING_DIR / "excluded_pages.json"


# --------------------------------------------------------------------------
# Etapa 1: filtrado del corpus crudo
# --------------------------------------------------------------------------

# Valores de capture_status que indican que la página NO tiene contenido
# aprovechable (verificado contra capture_summary.json real: 41 páginas
# "broken" —típicamente HTTP 404 o un enlace que dispara una descarga de
# Nextcloud en vez de navegar— y 4 "empty_content" —el contenedor principal
# quedó vacío tras la limpieza del DOM, un defecto del sitio—).
_UNUSABLE_CAPTURE_STATUSES = {"broken", "empty_content"}

# Rama de section_path que es una trampa de rastreo genuina: carpetas
# "Coordinación Zonal N / Files" con enlaces a descargas de Nextcloud
# (nube.controlsanitario.gob.ec/.../download?...). No es contenido de
# Trámite/Tutorial, son anexos de rendición de cuentas financiera.
_RENDICION_CUENTAS_SECTION = "RENDICIÓN DE CUENTAS ARCSA"

# Nodo del árbol de secciones que agrupa las biografías individuales del
# comité de expertos externos (personil directory, no un Trámite).
_COMITE_EXPERTOS_SECTION = "COMITÉ DE EXPERTOS ARCSA"

# Encabezados/prefijos honoríficos usados en los títulos de las biografías
# individuales encontradas en la data real (Dr., Dra., Mgs., etc.). Se usa
# como segunda señal (además de la posición en section_path) para no
# excluir por error una página índice legítima que no sea una biografía.
_PERSON_TITLE_PATTERN = re.compile(
    r"^(Dr|Dra|Mgs|Msc|MSc|Lcdo|Lcda|Ing|Sr|Sra|Ab|Abg|Econ|PhD)\.?\s+\S",
)


def _is_rendicion_cuentas_branch(section_path: list[str]) -> bool:
    """True si section_path cae dentro de la rama RENDICIÓN DE CUENTAS ARCSA."""
    return any(part == _RENDICION_CUENTAS_SECTION for part in section_path)


def _is_comite_expertos_bio_leaf(section_path: list[str], title: str) -> bool:
    """
    True si la página es una biografía individual dentro del Comité de
    Expertos Externos (hoja del árbol), y no la página índice/landing del
    comité o de "Expertos Externos" en general.

    En la data real:
      - La página landing "Expertos Externos" tiene section_path de solo
        2 niveles (["Servicios", "Otros servicios"]) y título propio
        "Expertos Externos": NO cae aquí (no tiene contenido de biografía).
      - La página índice "COMITÉ DE EXPERTOS ARCSA" tiene section_path de
        3 niveles terminando en "Expertos Externos": tampoco cae aquí,
        se conserva aunque su contenido resulte casi vacío en el scrape.
      - Las 8 biografías individuales ("Dr. Fray Martínez Reyes", etc.)
        tienen section_path de 4 niveles terminando en
        "COMITÉ DE EXPERTOS ARCSA": SÍ caen aquí.
    """
    if not section_path or section_path[-1] != _COMITE_EXPERTOS_SECTION:
        return False
    return bool(_PERSON_TITLE_PATTERN.match(title.strip()))


def filter_pages(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Divide los registros de capture_summary.json en (kept, excluded).

    Cada registro excluido conserva su reason (string) además de sus datos
    originales, para poder escribir un reporte explícito de exclusión en
    vez de descartar la página en silencio (ver ADR 0004: "flag, don't
    drop" aplicado aquí a nivel de corpus, no solo de citas).

    La precedencia de reglas es: (a) capture_status inutilizable, luego
    (b) trampa de rastreo de Rendición de Cuentas, luego (c) biografía de
    experto. Cada página excluida cae bajo UNA sola razón (la primera que
    aplique), para que los conteos por razón no se solapen.

    Args:
        records: lista de diccionarios tal como vienen de capture_summary.json.

    Returns:
        (kept, excluded): kept es la lista de registros que sí entran al
        corpus ingestionable; excluded es la lista de registros descartados,
        cada uno con una clave adicional "exclusion_reason".
    """
    kept: list[dict] = []
    excluded: list[dict] = []

    for record in records:
        capture_status = record.get("capture_status")
        section_path = record.get("section_path") or []
        title = record.get("title") or ""

        reason = None

        # (a) Estado de captura inutilizable.
        if capture_status in _UNUSABLE_CAPTURE_STATUSES:
            reason = f"capture_status:{capture_status}"

        # (b) Trampa de rastreo: anexos financieros de Rendición de Cuentas.
        elif _is_rendicion_cuentas_branch(section_path):
            reason = "crawl_trap_rendicion_cuentas"

        # (c) Biografía individual del Comité de Expertos Externos.
        elif _is_comite_expertos_bio_leaf(section_path, title):
            reason = "personnel_directory_bio"

        if reason is not None:
            excluded.append({**record, "exclusion_reason": reason})
        else:
            kept.append(record)

    return kept, excluded


def write_exclusion_report(excluded: list[dict], output_path: Path = EXCLUDED_PAGES_REPORT_PATH) -> None:
    """
    Escribe el reporte explícito de páginas excluidas del corpus.

    Cada entrada conserva source_url, title, section_path, capture_status
    y exclusion_reason, para que el reporte sea auditable sin tener que
    volver a cruzar contra capture_summary.json.
    """
    report = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "source_url": item.get("source_url"),
            "section_path": item.get("section_path"),
            "capture_status": item.get("capture_status"),
            "exclusion_reason": item.get("exclusion_reason"),
        }
        for item in excluded
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Reporte de exclusión escrito en '{output_path}' ({len(report)} páginas).")


# --------------------------------------------------------------------------
# Etapa 2: parsing de una página sobreviviente
# --------------------------------------------------------------------------

# El front matter YAML lo escribe scrape_servicios.py como
# "---\n{yaml}---\n" al inicio del archivo. Este patrón captura solo el
# PRIMER bloque delimitado por "---" al inicio del texto (no confundirlo
# con líneas "---" que puedan aparecer como separador horizontal más abajo
# en el cuerpo Markdown, porque el match no es codicioso y se detiene en el
# primer cierre).
_FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Patrones de citas a Normativa ARCSA/relacionada, calibrados contra
# ejemplos reales encontrados en el corpus (ver justificación en el
# reporte de este trabajo, no solo en la especificación original):
#
#   - Resolución ARCSA-DE-...: el código real varía en el orden de sus
#     partes numéricas (a veces "AÑO-NÚMERO", a veces "NÚMERO-AÑO", p.ej.
#     "ARCSA-DE-2021-016-AKRG" y "ARCSA-DE-008-2018-JCGO" both existen), y
#     ocasionalmente el scrape introduce un espacio extra alrededor de un
#     guion por un salto de línea del sitio original (p.ej.
#     "ARCSA-DE-2021- 008-AKRG"). El patrón tolera ambos.
#   - Acuerdo Ministerial: aparece como "Nº 705", "No. 763", "012-2019"
#     (número-año) o "00069-2024", sin un orden fijo de N°/No./nada.
#   - Decisión (de la Comunidad Andina, CAN): aparece como "Decisión 833"
#     o "DECISIÓN 833", siempre número simple sin sufijo de año.
_RESOLUCION_ARCSA_PATTERN = re.compile(r"ARCSA-DE-\d{2,4}-\s?\d{2,4}-\s?[A-Z]{2,6}")
_ACUERDO_MINISTERIAL_PATTERN = re.compile(
    r"Acuerdo\s+Ministerial\s+(?:N[°ºo]\.?\s*)?\d{1,6}(?:-\d{4})?",
    re.IGNORECASE,
)
_DECISION_CAN_PATTERN = re.compile(r"Decisi[oó]n\s+\d+", re.IGNORECASE)

_NORMATIVA_CITATION_PATTERNS = (
    _RESOLUCION_ARCSA_PATTERN,
    _ACUERDO_MINISTERIAL_PATTERN,
    _DECISION_CAN_PATTERN,
)


def _strip_front_matter(markdown_text: str) -> str:
    """Quita el bloque de front matter YAML inicial y deja solo el cuerpo."""
    match = _FRONT_MATTER_PATTERN.match(markdown_text)
    if not match:
        return markdown_text.strip()
    return markdown_text[match.end():].strip()


def _extract_normativa_citations(body: str) -> list[str]:
    """
    Extrae menciones a Normativa ARCSA/relacionada del cuerpo de texto,
    deduplicadas y en orden de primera aparición.

    No se resuelve aquí si la cita está Vigente o Derogada (Cita
    Desactualizada, ver CONTEXT.md/ADR 0004): eso requiere cruzar contra el
    Corpus Documental, que es trabajo de otro workstream. Esta función solo
    extrae el string de la cita tal como aparece en el Tutorial.
    """
    seen: dict[str, None] = {}
    for pattern in _NORMATIVA_CITATION_PATTERNS:
        for match in pattern.finditer(body):
            # Normaliza espacios internos accidentales (p. ej. el guion con
            # espacio visto en "ARCSA-DE-2021- 008-AKRG").
            citation = re.sub(r"\s+", " ", match.group(0)).strip()
            seen.setdefault(citation, None)
    return list(seen.keys())


def parse_tutorial(markdown_text: str, front_matter: dict) -> dict:
    """
    Convierte el contenido crudo de una página de Tutorial en un chunk
    listo para RAG.

    Args:
        markdown_text: contenido crudo del archivo .md tal como se leyó de
            disco (incluye el bloque de front matter YAML al inicio).
        front_matter: metadata ya conocida de la página (típicamente el
            registro correspondiente de capture_summary.json, que trae
            id/title/source_url/section_path/captured_at/etc.).

    Returns:
        Diccionario con las claves:
            - "id": identificador de la página.
            - "title": título de la página.
            - "text": cuerpo limpio, sin el front matter YAML.
            - "source_url": URL original de la página.
            - "section_path": lista de secciones (breadcrumb) de la página.
            - "captured_at": timestamp de captura del scraper.
            - "normativa_citations": lista de menciones a Normativa ARCSA
              (Resoluciones, Acuerdos Ministeriales, Decisiones CAN)
              encontradas en el cuerpo, para cruce futuro contra el Corpus
              Documental (detección de Cita Desactualizada).
    """
    body = _strip_front_matter(markdown_text)
    citations = _extract_normativa_citations(body)

    return {
        "id": front_matter.get("id"),
        "title": front_matter.get("title"),
        "text": body,
        "source_url": front_matter.get("source_url"),
        "section_path": front_matter.get("section_path"),
        "captured_at": front_matter.get("captured_at"),
        "normativa_citations": citations,
    }


# --------------------------------------------------------------------------
# Etapa 3: adaptador hacia llama_index.core.Document
# --------------------------------------------------------------------------

def to_documents(chunks: list[dict]):
    """
    Envuelve cada chunk de parse_tutorial() en un llama_index.core.Document,
    dejando el resto de campos como metadata. Espeja el patrón de
    to_documents() en chatbot/ingestion.py para mantener consistencia entre
    ambos pipelines de ingesta.

    Args:
        chunks: lista de diccionarios producidos por parse_tutorial().

    Returns:
        Lista de instancias de llama_index.core.Document.
    """
    from llama_index.core import Document

    documents = []
    for chunk in chunks:
        documents.append(
            Document(
                text=chunk["text"],
                metadata={
                    "id": chunk.get("id"),
                    "title": chunk.get("title"),
                    "source_url": chunk.get("source_url"),
                    "section_path": chunk.get("section_path"),
                    "captured_at": chunk.get("captured_at"),
                    "normativa_citations": chunk.get("normativa_citations"),
                },
            )
        )
    return documents


# --------------------------------------------------------------------------
# Etapa 4: orquestación sobre el corpus real
# --------------------------------------------------------------------------

_FILE_HASH_SUFFIX_PATTERN = re.compile(r"-([0-9a-f]{8})(?:\.md)?$")


def _build_file_index(pages_dir: Path) -> dict[str, Path]:
    """
    Construye un índice hash -> ruta de archivo a partir de los .md en
    disco.

    No se puede reconstruir la ruta de un archivo a partir de
    section_path/title porque el slug del nombre de archivo en disco puede
    estar truncado distinto al "id" corto que trae capture_summary.json
    (verificado: mismo hash de 8 hex al final, pero longitudes de slug
    distintas). El hash de 8 caracteres al final del nombre de archivo (y
    del campo "id") es la clave de unión confiable entre ambos.
    """
    index: dict[str, Path] = {}
    for path in pages_dir.rglob("*.md"):
        match = _FILE_HASH_SUFFIX_PATTERN.search(path.name)
        if match:
            index[match.group(1)] = path
    return index


def _locate_page_file(record: dict, file_index: dict[str, Path]) -> Path | None:
    """Encuentra el archivo .md correspondiente a un registro, vía su hash."""
    record_id = record.get("id") or ""
    match = _FILE_HASH_SUFFIX_PATTERN.search(record_id)
    if not match:
        return None
    return file_index.get(match.group(1))


def run_pipeline(
    capture_summary_path: Path = CAPTURE_SUMMARY_PATH,
    pages_dir: Path = PAGES_DIR,
    excluded_report_path: Path = EXCLUDED_PAGES_REPORT_PATH,
) -> list[dict]:
    """
    Ejecuta el pipeline completo de limpieza/parsing sobre el corpus real:
    carga capture_summary.json, filtra, escribe el reporte de exclusión,
    parsea cada página sobreviviente y reporta conteos finales.

    Returns:
        Lista de chunks (diccionarios de parse_tutorial()) para las páginas
        que sí entraron al corpus.
    """
    print(f"[INFO] Cargando '{capture_summary_path}'...")
    with capture_summary_path.open(encoding="utf-8") as f:
        records = json.load(f)
    print(f"[INFO] {len(records)} registros cargados desde capture_summary.json.")

    kept, excluded = filter_pages(records)

    reason_counts: dict[str, int] = {}
    for item in excluded:
        reason = item["exclusion_reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    write_exclusion_report(excluded, excluded_report_path)

    print(f"[INFO] Páginas excluidas: {len(excluded)}")
    for reason, count in sorted(reason_counts.items()):
        print(f"       - {reason}: {count}")
    print(f"[INFO] Páginas que sobreviven el filtro: {len(kept)}")

    file_index = _build_file_index(pages_dir)
    print(f"[INFO] Archivos .md indexados en disco: {len(file_index)}")

    chunks: list[dict] = []
    missing_files = 0
    for record in kept:
        file_path = _locate_page_file(record, file_index)
        if file_path is None:
            missing_files += 1
            print(
                f"[ADVERTENCIA] No se encontró el archivo .md para la página "
                f"'{record.get('id')}' ({record.get('source_url')}); se omite."
            )
            continue

        raw_text = file_path.read_text(encoding="utf-8")
        chunk = parse_tutorial(raw_text, record)
        chunks.append(chunk)

    if missing_files:
        print(f"[ADVERTENCIA] {missing_files} página(s) sobrevivientes sin archivo .md en disco.")

    with_citations = sum(1 for c in chunks if c["normativa_citations"])
    without_citations = len(chunks) - with_citations

    print(f"[INFO] Chunks producidos: {len(chunks)}")
    print(f"       - con al menos una cita de Normativa: {with_citations}")
    print(f"       - sin ninguna cita de Normativa: {without_citations}")

    try:
        documents = to_documents(chunks)
        print(f"[INFO] Documents de llama_index generados (sin embeddings ni vector store): {len(documents)}")
    except ModuleNotFoundError as e:
        print(
            f"[ADVERTENCIA] No se pudo ejecutar to_documents() en este entorno "
            f"(falta la dependencia '{e.name}'; ver chatbot/requirements.txt). "
            "Los chunks igual se devuelven sin envolver en Document."
        )

    return chunks


if __name__ == "__main__":
    run_pipeline()
