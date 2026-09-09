"""
Módulo de limpieza y parsing del corpus de Tutorial (páginas scrapeadas de
https://www.controlsanitario.gob.ec/servicios/).

Distinto de chatbot/ingestion.py: ese módulo parsea Normativa Vigente con
estructura legal Artículo/Numeral/Literal, mientras que Tutorial son guías
en lenguaje natural sin esa estructura, así que usa su propio pipeline.

Etapas: filter_pages() descarta páginas no aprovechables dejando un reporte
explícito (ver ADR 0004 "flag, don't drop"); parse_tutorial() limpia una
página y extrae menciones a Normativa ARCSA vía regex para un cruce futuro
contra el Corpus Documental; to_documents() adapta a
llama_index.core.Document; run_pipeline() orquesta todo sobre el corpus
real en disco.

No hace embeddings ni llamadas a un vector store, y no modifica el scraper
ni chatbot/ingestion.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

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

# capture_status sin contenido aprovechable: "broken" (404 o descarga de
# Nextcloud en vez de navegación) y "empty_content" (DOM vacío tras limpieza).
_UNUSABLE_CAPTURE_STATUSES = {"broken", "empty_content"}

# Rama de section_path que es una trampa de rastreo: carpetas
# "Coordinación Zonal N / Files" con descargas de Nextcloud, no contenido
# de Trámite/Tutorial sino anexos de rendición de cuentas financiera.
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


def _canonical_url_ignoring_scheme(url: str | None) -> str:
    """
    Clave de deduplicación por URL que ignora el esquema (http/https).

    scrape_servicios.canonical_url() normaliza host/path/fragmento pero no
    el esquema, así que un enlace interno en http:// hacia una página que
    en otro lugar del sitio se referencia en https:// termina tratado como
    dos páginas distintas. Esta función es la red de seguridad en el
    filtrado de este módulo para detectar y excluir esos duplicados.

    Conserva el query string (dos páginas con distinto "?p=..." no son
    duplicadas).
    """
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.netloc.lower()}{path}{query}"


def _is_comite_expertos_bio_leaf(section_path: list[str], title: str) -> bool:
    """
    True si la página es una biografía individual del Comité de Expertos
    Externos (hoja del árbol), y no la página índice/landing del comité.

    Se distingue exigiendo section_path terminado en
    _COMITE_EXPERTOS_SECTION junto con un título que empieza con un
    prefijo honorífico; las páginas índice no cumplen ambas condiciones.
    """
    if not section_path or section_path[-1] != _COMITE_EXPERTOS_SECTION:
        return False
    return bool(_PERSON_TITLE_PATTERN.match(title.strip()))


def filter_pages(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Divide los registros de capture_summary.json en (kept, excluded).

    Cada excluido conserva su "exclusion_reason" en vez de descartarse en
    silencio (ver ADR 0004: "flag, don't drop"). Precedencia de reglas:
    (a) capture_status inutilizable, (b) trampa de rastreo de Rendición de
    Cuentas, (c) biografía de experto, (d) variante de esquema http/https
    de una URL ya conservada. La regla (d) depende del orden de `records`
    (gana la primera aparición), así que deben venir en el mismo orden que
    en capture_summary.json.

    Args:
        records: lista de diccionarios tal como vienen de capture_summary.json.

    Returns:
        (kept, excluded): páginas que entran al corpus ingestionable y
        páginas descartadas, cada una con la clave "exclusion_reason".
    """
    kept: list[dict] = []
    excluded: list[dict] = []
    seen_canonical_urls: dict[str, str] = {}  # canónica -> id del primero conservado

    for record in records:
        capture_status = record.get("capture_status")
        section_path = record.get("section_path") or []
        title = record.get("title") or ""
        canonical_url = _canonical_url_ignoring_scheme(record.get("source_url"))

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

        # (d) Duplicado de esquema http/https de una URL ya conservada.
        elif canonical_url and canonical_url in seen_canonical_urls:
            first_id = seen_canonical_urls[canonical_url]
            reason = f"duplicate_scheme_variant_of:{first_id}"

        if reason is not None:
            excluded.append({**record, "exclusion_reason": reason})
        else:
            kept.append(record)
            if canonical_url:
                seen_canonical_urls[canonical_url] = record.get("id") or ""

    return kept, excluded


def write_exclusion_report(excluded: list[dict], output_path: Path = EXCLUDED_PAGES_REPORT_PATH) -> None:
    """
    Escribe el reporte explícito de páginas excluidas del corpus.

    Cada entrada conserva source_url, title, section_path, capture_status
    y exclusion_reason para que sea auditable sin recruzar contra
    capture_summary.json.
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

# Front matter YAML escrito por scrape_servicios.py como "---\n{yaml}---\n".
# El match no es codicioso: solo captura el primer bloque "---" al inicio,
# sin confundirse con separadores horizontales más abajo en el Markdown.
_FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Patrones de citas a Normativa ARCSA/relacionada. El orden de las partes
# numéricas de una Resolución varía (año-número o número-año) y el scrape
# a veces introduce un espacio extra alrededor de un guion; el patrón
# tolera ambos. Acuerdo Ministerial y Decisión CAN también varían en el
# uso de "Nº"/"No."/nada.
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


# Hosts del portal ARCSA para los que se fuerza esquema https:// en
# source_url (ver _normalize_source_url_scheme). Se incluye la variante
# sin "www." por si algún enlace interno del sitio la usa.
_HTTPS_ONLY_HOSTS = {"controlsanitario.gob.ec", "www.controlsanitario.gob.ec"}


def _normalize_source_url_scheme(source_url: str | None) -> str | None:
    """
    Fuerza esquema https:// para URLs de controlsanitario.gob.ec.

    El sitio solo sirve por HTTPS, pero el scraper puede capturar un
    enlace interno escrito en http:// tal cual aparece en el HTML de
    origen. Sin normalizar, ese source_url queda horneado en el docstore
    y se expone como un enlace muerto en la UI (RagSourcesDrawer).

    No se toca el resto de la URL (path, query, fragment): solo el
    esquema, y solo para los hosts de _HTTPS_ONLY_HOSTS.
    """
    if not source_url:
        return source_url
    parsed = urlparse(source_url)
    if parsed.scheme == "http" and parsed.netloc.lower() in _HTTPS_ONLY_HOSTS:
        return parsed._replace(scheme="https").geturl()
    return source_url


def _strip_front_matter(markdown_text: str) -> str:
    """Quita el bloque de front matter YAML inicial y deja solo el cuerpo."""
    match = _FRONT_MATTER_PATTERN.match(markdown_text)
    if not match:
        return markdown_text.strip()
    return markdown_text[match.end():].strip()


def _extract_normativa_citations(body: str) -> list[str]:
    """
    Extrae menciones a Normativa ARCSA del cuerpo, deduplicadas y en orden
    de primera aparición. No resuelve si la cita está Vigente o Derogada
    (eso requiere cruzar contra el Corpus Documental, ver
    citation_crossref.py); solo extrae el string tal como aparece.
    """
    seen: dict[str, None] = {}
    for pattern in _NORMATIVA_CITATION_PATTERNS:
        for match in pattern.finditer(body):
            # Normaliza espacios internos accidentales dentro del código.
            citation = re.sub(r"\s+", " ", match.group(0)).strip()
            seen.setdefault(citation, None)
    return list(seen.keys())


def parse_tutorial(markdown_text: str, front_matter: dict) -> dict:
    """
    Convierte el contenido crudo de una página de Tutorial en un chunk
    listo para RAG.

    Args:
        markdown_text: contenido crudo del .md (incluye front matter YAML).
        front_matter: metadata de la página (típicamente el registro de
            capture_summary.json: id/title/source_url/section_path/etc.).

    Returns:
        Diccionario con "id", "title", "text" (cuerpo limpio), "source_url"
        (esquema https:// forzado, ver _normalize_source_url_scheme),
        "section_path", "captured_at" y "normativa_citations" (menciones a
        Normativa ARCSA para cruce futuro contra el Corpus Documental).
    """
    body = _strip_front_matter(markdown_text)
    citations = _extract_normativa_citations(body)

    return {
        "id": front_matter.get("id"),
        "title": front_matter.get("title"),
        "text": body,
        "source_url": _normalize_source_url_scheme(front_matter.get("source_url")),
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
    dejando el resto de campos como metadata. Espeja to_documents() de
    chatbot/ingestion.py para mantener consistencia entre pipelines.

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

    El slug del nombre de archivo puede estar truncado distinto al "id"
    corto de capture_summary.json, así que se usa el hash de 8 caracteres
    al final de ambos como clave de unión confiable.
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
