"""
Módulo de extracción de texto + chunking para el Corpus Documental de
Normativa ARCSA, a partir de los archivos originales (PDF/DOC/XLSX)
descargados por el scraper externo "arcsaPlayright" desde
https://www.controlsanitario.gob.ec/documentos-vigentes/.

Etapa nueva y separada del pipeline: no modifica chatbot/ingestion.py,
chatbot/tutorial_ingestion.py, chatbot/link_validation.py ni
chatbot/vector_store.py. Reutiliza parse_normativa()/to_documents() de
chatbot/ingestion.py para el chunking a nivel de Artículo (ver
CONTEXT.md); aquí solo se resuelve lo que ingestion.py no hace: leer el
manifest externo, extraer el texto crudo de cada formato binario y
escribir el resultado como chunks RAG-ready dentro del repo.

La carpeta externa (ver DEFAULT_EXTERNAL_ROOT) es de solo lectura: este
módulo nunca escribe ni modifica nada ahí, y el repo se queda solo con el
texto ya extraído y troceado en chatbot/data/normativa/ (no se copian los
binarios originales).

Estructura del manifest.json externo (árbol sections -> subsections ->
documents; se recorre recursivamente porque una subsección puede anidar
otras):

    {
      "source_url": ...,
      "generated_at": ...,
      "sections": [
        {"order": ..., "name": ..., "subsections": [
          {"order": ..., "name": ..., "documents": [
            {"title_original": ..., "status": "downloaded"|"failed",
             "local_path": "originales/_archivos/<archivo>",
             "extension_detectada": "pdf"|"doc"|"xlsx"|null,
             "file_id": "arcsa_<id>", "url_final": ..., "error": ..., ...}
          ]}
        ]}
      ],
      "sin_clasificar": [...]
    }

El mismo archivo físico puede estar listado más de una vez bajo distintas
secciones/subsecciones (documento clasificado en más de una categoría):
se deduplica por "file_id" antes de extraer texto para no generar chunks
duplicados (ver deduplicate_by_file_id). Los archivos en disco que ninguna
entrada del manifest referencia se reportan como brecha aparte pero no se
procesan, porque este pipeline es manifest-driven (ver
find_unreferenced_disk_files).

Política "flag, don't drop" (ver ADR 0004, ya usada en link_validation.py
y tutorial_ingestion.py): un documento cuya extracción falla, o cuyo texto
no tiene ningún encabezado de Artículo, nunca se descarta en silencio. Se
marca explícitamente en el reporte y, cuando hay texto aprovechable, se
conserva troceado por tamaño (ver _fallback_size_based_chunks), no como un
único chunk gigante.

LIMITACIÓN DE DISEÑO: cobertura de la segmentación por Artículo
--------------------------------------------------------------------------
La unidad de fragmentación preferida de este proyecto (un chunk por
Artículo, vía parse_normativa(), ver CONTEXT.md) no cubre todo el corpus.
Una parte de los documentos (informes de análisis de impacto regulatorio,
instructivos organizados por numerales propios, planes institucionales,
checklists, informes técnicos de organismos internacionales) no está
redactada como una secuencia de "Art. N.-": no hay una unidad jurídica que
dividir. Otra parte sí menciona "artículo", pero solo citando textualmente
otro instrumento legal (la Constitución, la Ley Orgánica de Salud, otra
Resolución) dentro de un párrafo o entre comillas; el regex de encabezado
deliberadamente no trata esas citas como encabezado propio, porque
hacerlo mezclaría el chunk con contenido ajeno al documento. Ambos casos
caen en el fallback de tamaño en vez de forzar una segmentación jurídica
que el documento no tiene.

LIMITACIÓN CONOCIDA: caracteres como proxy del tamaño en tokens
--------------------------------------------------------------------------
El chunking de tamaño de este módulo (_fallback_size_based_chunks,
_resplit_oversized_chunk) usa un presupuesto fijo en CARACTERES
(MAX_SAFE_CHUNK_CHARS), calibrado contra la API de tokens de Gemini
asumiendo una densidad de ~3.3-4.5 caracteres/token. Esa densidad no es
constante: un PDF puede incrustar una fuente con codificación de símbolos
propia que PyMuPDF no resuelve a Unicode real, devolviendo glyphs del
Área de Uso Privado (ver _strip_pua_glyphs) que el tokenizer de Gemini
trata como texto exótico de muy baja densidad. Ningún presupuesto fijo en
caracteres puede garantizar un tope exacto de tokens para contenido de
densidad atípica sin consultar el tokenizer real en cada chunk, algo que
este módulo deliberadamente no hace para mantenerse 100% local y
determinístico. Mitigación: chatbot/vector_ingest.py::embed_documents()
ya aísla y reporta como fallo individual (sin abortar la corrida) cualquier
chunk que la API de embeddings rechace por motivo de contenido.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import openpyxl

# Algunos títulos y mensajes de error traen caracteres Unicode que la
# consola de Windows (cp1252) no soporta; se reconfigura stdout/stderr a
# UTF-8 con reemplazo para que un print() no tumbe la corrida completa.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # stdout/stderr no soporta reconfigure (p.ej. ya redirigido); no es crítico

# Soporta tanto "python chatbot/normativa_extraction.py" (script suelto) como
# "python -m chatbot.normativa_extraction" (import de paquete) desde la raíz
# del repo, igual que el resto de módulos de chatbot/.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ingestion import parse_normativa
else:
    from chatbot.ingestion import parse_normativa


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

# Carpeta externa de solo lectura con el scrape original (manifest.json +
# los binarios en originales/_archivos/). Configurable vía variable de
# entorno para no hardcodear la ruta de una sola máquina.
DEFAULT_EXTERNAL_ROOT = Path(
    os.environ.get("ARCSA_SOURCE_ROOT", r"C:\Users\jarri\Downloads\arcsaPlayright")
)
MANIFEST_FILENAME = "manifest.json"
ARCHIVOS_SUBDIR = Path("originales") / "_archivos"

# Salida DENTRO del repo: solo texto/chunks, nunca los binarios originales.
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "normativa"
REPORT_PATH = Path(__file__).resolve().parent / "data" / "normativa_extraction_report.json"

# Prefijo del "articulo_numero" para los chunks de respaldo de documentos
# sin ningún encabezado de Artículo propio (ver _fallback_size_based_chunks).
# Cada fragmento se numera como f"{FRAGMENTO_SENTINEL_PREFIX}_{i}_DE_{n}"
# (p. ej. "FRAGMENTO_3_DE_45"), nunca como un único chunk "DOCUMENTO_COMPLETO".
FRAGMENTO_SENTINEL_PREFIX = "FRAGMENTO"

# Tamaño (caracteres) y solapamiento máximos seguros para cualquier chunk
# que se vaya a embeber con gemini-embedding-001 (límite real de 2048
# tokens/texto). Se usa tanto en _fallback_size_based_chunks (documentos
# sin ningún Artículo propio) como en _resplit_oversized_chunk (red de
# seguridad para un Artículo genuino que igual resulta demasiado grande):
# el límite real de la API es el mismo en ambos casos.
MAX_SAFE_CHUNK_CHARS = 4500
MAX_SAFE_CHUNK_OVERLAP_CHARS = 400

# Al cortar cerca de MAX_SAFE_CHUNK_CHARS, se retrocede como máximo esta
# cantidad de caracteres buscando un espacio en blanco para no partir una
# palabra a la mitad; si no hay ninguno en ese rango, se corta igual en el
# límite duro.
MAX_SAFE_CHUNK_BOUNDARY_LOOKBACK_CHARS = 200


# --------------------------------------------------------------------------
# Etapa 1: lectura y aplanado del manifest externo
# --------------------------------------------------------------------------

def _walk_manifest_node(node: dict, breadcrumb: list[str]) -> list[dict]:
    """
    Recorre recursivamente un nodo del árbol sections/subsections del
    manifest y devuelve todas las entradas de "documents" que encuentra,
    con el breadcrumb (nombres de sección/subsección) adjunto en la clave
    "_breadcrumb" de cada entrada (solo para trazabilidad en el reporte).
    """
    found: list[dict] = []
    name = node.get("name")
    here = breadcrumb + [name] if name else breadcrumb

    for doc in node.get("documents", []) or []:
        entry = dict(doc)
        entry["_breadcrumb"] = here
        found.append(entry)

    for sub in node.get("subsections", []) or []:
        found.extend(_walk_manifest_node(sub, here))

    return found


def load_manifest_documents(external_root: Path) -> list[dict]:
    """
    Carga manifest.json desde `external_root` y devuelve la lista aplanada
    de todas las entradas de documento, sin deduplicar todavía. Cada
    entrada conserva sus campos originales del manifest más "_breadcrumb"
    (ver _walk_manifest_node).
    """
    manifest_path = external_root / MANIFEST_FILENAME
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    documents: list[dict] = []
    for section in manifest.get("sections", []) or []:
        documents.extend(_walk_manifest_node(section, []))
    # "sin_clasificar" está vacío en la data real, pero se incluye por si
    # una corrida futura del scraper sí deja documentos ahí.
    for doc in manifest.get("sin_clasificar", []) or []:
        entry = dict(doc)
        entry["_breadcrumb"] = ["sin_clasificar"]
        documents.append(entry)

    return documents


def _is_real_url(value: object) -> bool:
    """True solo si `value` es un string que parece una URL http(s) real
    (nunca el literal "about:blank" ni vacío/None)."""
    return bool(value) and isinstance(value, str) and value != "about:blank" and value.startswith("http")


def resolve_document_url(doc: dict) -> tuple[str | None, str | None]:
    """
    Resuelve la URL pública real de un documento del manifest.

    Cuando el scraper dispara la descarga vía un evento JS en vez de
    navegar a la página del documento, "url_final" queda como el literal
    "about:blank" aunque el documento sí tenga una URL de origen real.
    Por eso la prioridad de resolución es:
      1) doc["url_final"] si es una URL real.
      2) doc["url_ver"] (el enlace "ver/descargar" de la página de origen)
         como fallback.
      3) None explícito si ninguno de los dos es una URL real (no se
         inventa una URL falsa — ver política "flag, don't drop").

    Devuelve (url_o_none, nota_de_fuente_o_none); la nota solo se genera
    cuando se usó el fallback o no hay ninguna URL real, para trazabilidad.
    """
    url_final = doc.get("url_final")
    if _is_real_url(url_final):
        return url_final, None

    url_ver = doc.get("url_ver")
    if _is_real_url(url_ver):
        return url_ver, (
            "manifest.url_ver (url_final del manifest era inválido/"
            f"'{url_final}'; ver resolve_document_url() en este módulo)"
        )

    return None, (
        "null explícito: ni manifest.url_final ni manifest.url_ver son URLs "
        "reales para este documento (no se inventa una URL)."
    )


def deduplicate_by_file_id(documents: list[dict]) -> tuple[list[dict], int]:
    """
    Deduplica documentos "downloaded" por file_id (equivalente a
    local_path: mismo archivo físico clasificado bajo más de una
    sección/subsección). Se conserva la PRIMERA aparición en el orden del
    árbol; las apariciones repetidas solo aportan su breadcrumb a
    "_also_classified_under" de la entrada conservada, para no perder esa
    información en el reporte.

    Devuelve (lista deduplicada, cantidad de duplicados descartados).
    """
    by_id: dict[str, dict] = {}
    order: list[str] = []
    duplicates = 0

    for doc in documents:
        file_id = doc.get("file_id")
        if file_id is None:
            # Las entradas "failed" no tienen file_id (nunca se descargó
            # nada); no hay nada que deduplicar para esas.
            order.append(id(doc))
            by_id[id(doc)] = doc
            continue

        if file_id in by_id:
            duplicates += 1
            by_id[file_id].setdefault("_also_classified_under", [])
            by_id[file_id]["_also_classified_under"].append(doc.get("_breadcrumb"))
            continue

        by_id[file_id] = doc
        order.append(file_id)

    return [by_id[key] for key in order], duplicates


def find_unreferenced_disk_files(external_root: Path, downloaded_docs: list[dict]) -> list[str]:
    """
    Compara los archivos realmente presentes en originales/_archivos/
    contra los "local_path" de las entradas "downloaded" del manifest.
    Devuelve los nombres de archivo que existen en disco pero que ninguna
    entrada del manifest referencia (ni siquiera como "failed").

    Este pipeline es manifest-driven (itera entradas del manifest, no el
    directorio a ciegas): estos archivos se reportan como brecha para que
    quede visible, pero no se procesan — adivinar a qué documento del
    sitio corresponde cada uno está fuera del alcance de esta etapa.
    """
    archivos_dir = external_root / ARCHIVOS_SUBDIR
    if not archivos_dir.is_dir():
        return []

    disk_files = {p.name for p in archivos_dir.iterdir() if p.is_file()}
    referenced = {
        Path(doc["local_path"]).name
        for doc in downloaded_docs
        if doc.get("local_path")
    }
    return sorted(disk_files - referenced)


# --------------------------------------------------------------------------
# Etapa 2: extracción de texto crudo por formato
# --------------------------------------------------------------------------

# Rangos del Área de Uso Privado (Private Use Area) de Unicode: puntos de
# código reservados para que CADA fuente/aplicación les asigne su propio
# significado (nunca tienen un glyph universal). Ver _strip_pua_glyphs.
_PRIVATE_USE_AREA_RANGES = (
    (0xE000, 0xF8FF),  # PUA básica
    (0xF0000, 0xFFFFD),  # PUA suplementaria A
    (0x100000, 0x10FFFD),  # PUA suplementaria B
)


def _strip_pua_glyphs(text: str) -> tuple[str, int]:
    """
    Elimina del texto extraído los caracteres del Área de Uso Privado (PUA)
    de Unicode y devuelve (texto_limpio, cantidad_eliminada).

    Algunos PDF incrustan una fuente con codificación de símbolos propia
    que PyMuPDF no resuelve a Unicode real, devolviendo glyphs de PUA sin
    significado semántico fuera de esa fuente (nunca texto real citable
    para RAG). El tokenizer de Gemini los trata como texto exótico de muy
    baja densidad, tokenizando casi carácter por carácter y rompiendo la
    garantía de tamaño de cualquier presupuesto fijo en caracteres.

    Es una excepción justificada a la política "flag, don't drop" (ADR
    0004): lo que se elimina es ruido de decodificación de fuente, no
    información real. La cantidad eliminada queda registrada en
    "extraction_warnings" del documento afectado en vez de descartarse en
    silencio.
    """
    removed = sum(
        1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _PRIVATE_USE_AREA_RANGES)
    )
    if not removed:
        return text, 0
    cleaned = "".join(
        ch for ch in text if not any(lo <= ord(ch) <= hi for lo, hi in _PRIVATE_USE_AREA_RANGES)
    )
    return cleaned, removed


class ExtractionResult:
    """Resultado de intentar extraer texto de un archivo fuente."""

    def __init__(self, text: str | None, method: str, warnings: list[str] | None = None):
        self.text = text
        self.method = method
        self.warnings = warnings or []

    @property
    def ok(self) -> bool:
        return bool(self.text and self.text.strip())


def extract_pdf_text(path: Path) -> ExtractionResult:
    """
    Extrae texto de un PDF página por página con PyMuPDF (fitz).

    Los PDF de este corpus tienen capa de texto nativa (no son escaneos),
    así que un `get_text()` directo por página basta. Una página cuyo
    texto quede vacío se registra en "warnings" en vez de descartarse en
    silencio (política "flag, don't drop"): podría ser una imagen suelta o
    un anexo escaneado colado en un documento por lo demás nativo.
    """
    warnings: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # archivo corrupto o no abrible
        return ExtractionResult(None, "pymupdf", [f"No se pudo abrir el PDF: {exc}"])

    try:
        pages_text = []
        for page_number, page in enumerate(doc, start=1):
            page_text = page.get_text()
            if not page_text.strip():
                warnings.append(f"Página {page_number}/{doc.page_count} sin texto extraíble.")
            pages_text.append(page_text)
        text = "\n".join(pages_text)
    finally:
        doc.close()

    return ExtractionResult(text, "pymupdf", warnings)


def extract_xlsx_text(path: Path) -> ExtractionResult:
    """
    Extrae el texto de un XLSX uniendo el valor de cada celda no vacía,
    hoja por hoja, fila por fila. Caso marginal en este corpus, así que se
    mantiene deliberadamente simple: no preserva la estructura tabular,
    solo recupera el texto para que parse_normativa() pueda buscar
    encabezados de Artículo en él.
    """
    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        return ExtractionResult(None, "openpyxl", [f"No se pudo abrir el XLSX: {exc}"])

    lines: list[str] = []
    try:
        for sheet in workbook.worksheets:
            lines.append(f"[Hoja: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    finally:
        workbook.close()

    return ExtractionResult("\n".join(lines), "openpyxl", [])


_word_application = None  # instancia COM de Word reutilizada entre archivos .doc


def _get_word_application():
    """
    Crea (una sola vez, reutilizada entre archivos) una instancia oculta de
    Word vía COM para abrir los .doc legacy: python-docx no soporta el
    formato binario .doc (solo .docx). Se desactivan alertas y
    confirmaciones de conversión para que abrir un .doc viejo no se quede
    esperando un diálogo que nadie va a contestar.
    """
    global _word_application
    if _word_application is not None:
        return _word_application

    import win32com.client

    app = win32com.client.DispatchEx("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0  # wdAlertsNone
    _word_application = app
    return app


def _shutdown_word_application() -> None:
    global _word_application
    if _word_application is not None:
        try:
            _word_application.Quit()
        except Exception:
            pass  # ya se está cerrando el proceso; no bloquear el reporte final por esto
        _word_application = None


def _extract_doc_via_word_com(path: Path) -> str:
    word = _get_word_application()
    document = word.Documents.Open(
        str(path), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
    )
    try:
        return document.Content.Text
    finally:
        document.Close(SaveChanges=False)


def _extract_doc_via_antiword(path: Path) -> str:
    completed = subprocess.run(
        ["antiword", str(path)],
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"antiword salió con código {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', errors='replace')[:300]}"
        )
    return completed.stdout.decode("utf-8", errors="replace")


def extract_doc_text(path: Path) -> ExtractionResult:
    """
    Extrae texto de un .doc legacy (formato binario de Word, NO .docx).
    python-docx/docx2txt no sirven aquí (solo entienden .docx). Se intenta,
    en orden: 1) Word vía COM (win32com), la opción más fiel disponible en
    este entorno; 2) antiword (binario externo) como respaldo si Word/COM
    no está disponible o falla para un archivo puntual.

    Si ambas fallan, se devuelve un ExtractionResult sin texto y con el
    motivo en "warnings": se reporta como gap, nunca se inventa contenido.
    """
    warnings: list[str] = []

    try:
        text = _extract_doc_via_word_com(path)
        return ExtractionResult(text, "word_com", warnings)
    except Exception as exc:
        warnings.append(f"Word COM falló: {exc}")

    try:
        text = _extract_doc_via_antiword(path)
        return ExtractionResult(text, "antiword", warnings)
    except Exception as exc:
        warnings.append(f"antiword falló: {exc}")

    return ExtractionResult(None, "none", warnings)


_EXTRACTORS = {
    ".pdf": extract_pdf_text,
    ".doc": extract_doc_text,
    ".xlsx": extract_xlsx_text,
}


# --------------------------------------------------------------------------
# Etapa 3: chunking (reutilizando parse_normativa) + fallback documentado
# --------------------------------------------------------------------------

def split_text_into_windows(
    text: str,
    chunk_size: int = MAX_SAFE_CHUNK_CHARS,
    overlap: int = MAX_SAFE_CHUNK_OVERLAP_CHARS,
    boundary_lookback: int = MAX_SAFE_CHUNK_BOUNDARY_LOOKBACK_CHARS,
) -> list[str]:
    """
    Divide `text` en ventanas de hasta `chunk_size` caracteres, con
    `overlap` caracteres de solapamiento entre ventanas consecutivas, sin
    cortar una palabra a la mitad cuando se puede evitar.

    Si `text` ya entra en `chunk_size`, devuelve una lista de un solo
    elemento. En caso contrario, cada corte retrocede hasta el último
    espacio en blanco dentro de `boundary_lookback` caracteres (o corta en
    el límite duro si no encuentra ninguno), y la siguiente ventana
    empieza `overlap` caracteres antes del corte anterior para no perder
    contexto cercano al límite.
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    windows: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            lookback_start = max(start, end - boundary_lookback)
            boundary = text.rfind(" ", lookback_start, end)
            if boundary > start:
                end = boundary
        window = text[start:end].strip()
        if window:
            windows.append(window)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return windows


def _fallback_size_based_chunks(text: str, source_name: str) -> list[dict]:
    """
    Chunking de respaldo por TAMAÑO (sliding window con solapamiento) para
    un documento cuyo texto no contiene ningún encabezado de Artículo
    propio (parse_normativa devolvió []) — ver la sección "LIMITACIÓN DE
    DISEÑO" en el docstring del módulo.

    MAX_SAFE_CHUNK_CHARS/MAX_SAFE_CHUNK_OVERLAP_CHARS se calibraron con
    margen amplio por debajo del límite real de tokens de la API de
    embeddings (ver esas constantes), ya que la densidad caracteres/token
    varía según el documento y un único chunk con el texto completo podía
    superar fácilmente ese límite en documentos largos.

    Cada fragmento usa "articulo_numero" = f"FRAGMENTO_{i}_DE_{n}" (p. ej.
    "FRAGMENTO_3_DE_45"): estable entre corridas y compatible sin cambios
    con el esquema de IDs de chatbot/vector_ingest.py. Si el documento ya
    entra en un solo chunk, n=1 y solo se genera "FRAGMENTO_1_DE_1".
    """
    windows = split_text_into_windows(text)
    total = len(windows)
    return [
        {
            "articulo_numero": f"{FRAGMENTO_SENTINEL_PREFIX}_{i}_DE_{total}",
            "texto": window_text,
            "source": source_name,
            "vigente": True,
            "sin_estructura_articulo": True,
        }
        for i, window_text in enumerate(windows, start=1)
    ]


def _resplit_oversized_chunk(chunk: dict) -> list[dict]:
    """
    Red de seguridad de tamaño para un chunk de ARTÍCULO GENUINO (viene de
    parse_normativa(), no del fallback): si ya entra en
    MAX_SAFE_CHUNK_CHARS se devuelve sin cambios. Si no entra, se divide
    con el mismo criterio de sliding-window + solapamiento que
    _fallback_size_based_chunks.

    Un Artículo real puede resultar demasiado grande cuando el texto entre
    su encabezado y el siguiente incluye anexos o tablas extensas:
    parse_normativa() atribuye correctamente ese texto al Artículo, pero
    el resultado puede superar el límite seguro para embeber.

    No modifica parse_normativa()/ARTICULO_HEADER_PATTERN. El
    "articulo_numero" original se conserva como prefijo
    (f"{articulo_numero}_PARTE_{i}_DE_{n}", p. ej. "48_PARTE_2_DE_9") y se
    marca "articulo_dividido_por_tamano": True (distinto de
    "sin_estructura_articulo", que sigue en False: el Artículo sí existe).
    """
    text = chunk["texto"]
    if len(text) <= MAX_SAFE_CHUNK_CHARS:
        return [chunk]

    windows = split_text_into_windows(text)
    total = len(windows)
    base_articulo = chunk["articulo_numero"]
    return [
        {
            **chunk,
            "articulo_numero": f"{base_articulo}_PARTE_{i}_DE_{total}",
            "texto": window_text,
            "articulo_dividido_por_tamano": True,
        }
        for i, window_text in enumerate(windows, start=1)
    ]


def chunk_document_text(text: str, source_name: str) -> tuple[list[dict], bool]:
    """
    Aplica parse_normativa() (chatbot/ingestion.py, sin modificar) al texto
    crudo ya extraído. Si se encontraron Artículos, cada chunk pasa además
    por _resplit_oversized_chunk() como red de seguridad de tamaño. Si no
    se encontró ningún Artículo, aplica el fallback de tamaño con
    solapamiento (ver _fallback_size_based_chunks).

    Devuelve (chunks, sin_estructura_articulo); este último describe al
    documento completo, no a cada chunk individual.
    """
    chunks = parse_normativa(text, source_name=source_name)
    if chunks:
        safe_chunks: list[dict] = []
        for chunk in chunks:
            safe_chunks.extend(_resplit_oversized_chunk(chunk))
        return safe_chunks, False
    return _fallback_size_based_chunks(text, source_name), True


# --------------------------------------------------------------------------
# Etapa 4: orquestación sobre el corpus real + reporte
# --------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    """Escritura simple a disco (ver nota de atomicidad en link_validation.py;
    aquí no hace falta ese nivel de robustez porque esta corrida es local,
    rápida y no comparte el archivo con ningún proceso concurrente)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_extraction(external_root: Path | None = None) -> dict:
    """
    Ejecuta el pipeline completo: lee el manifest real, extrae texto de
    cada documento "downloaded" único, lo trocea con parse_normativa(),
    escribe un JSON por documento en chatbot/data/normativa/, y devuelve
    (y también escribe) el reporte de extracción.
    """
    external_root = external_root or DEFAULT_EXTERNAL_ROOT
    archivos_dir = external_root / ARCHIVOS_SUBDIR

    print(f"[INFO] Leyendo manifest desde '{external_root / MANIFEST_FILENAME}'...")
    all_documents = load_manifest_documents(external_root)
    print(f"[INFO] {len(all_documents)} entradas totales en el manifest (antes de deduplicar).")

    downloaded_raw = [d for d in all_documents if d.get("status") == "downloaded"]
    failed_raw = [d for d in all_documents if d.get("status") != "downloaded"]

    downloaded, duplicate_count = deduplicate_by_file_id(downloaded_raw)
    print(
        f"[INFO] {len(downloaded_raw)} entradas 'downloaded' "
        f"({len(downloaded)} únicas tras deduplicar por file_id, "
        f"{duplicate_count} duplicados descartados por estar clasificados en más de una sección)."
    )
    print(f"[ADVERTENCIA] {len(failed_raw)} entradas 'failed' (sin archivo local, descarga fallida). Se reportan como brecha.")

    unreferenced_on_disk = find_unreferenced_disk_files(external_root, downloaded)
    if unreferenced_on_disk:
        print(
            f"[ADVERTENCIA] {len(unreferenced_on_disk)} archivo(s) en disco NO referenciado(s) "
            "por ninguna entrada del manifest (no se procesan, solo se reportan)."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    per_format_stats: dict[str, dict[str, int]] = {
        ext: {"exitosos": 0, "fallidos": 0} for ext in _EXTRACTORS
    }
    extraction_failures: list[dict] = []
    processed_documents: list[dict] = []
    sin_estructura_examples: list[dict] = []
    success_examples: list[dict] = []
    total_chunks = 0

    started_at = time.monotonic()
    try:
        for i, doc in enumerate(downloaded, start=1):
            local_path = doc.get("local_path")
            extension = Path(local_path).suffix.lower() if local_path else ""
            title = doc.get("title_original") or local_path or doc.get("file_id")
            file_id = doc.get("file_id") or f"sin_file_id_{i}"

            print(f"[{i}/{len(downloaded)}] Procesando ({extension}): {title}")

            extractor = _EXTRACTORS.get(extension)
            if extractor is None:
                extraction_failures.append({
                    "file_id": file_id,
                    "title": title,
                    "local_path": local_path,
                    "reason": f"Extensión no soportada por esta etapa: '{extension}'.",
                })
                continue

            full_path = archivos_dir / Path(local_path).name
            if not full_path.is_file():
                extraction_failures.append({
                    "file_id": file_id,
                    "title": title,
                    "local_path": local_path,
                    "reason": "El manifest lo marca 'downloaded' pero el archivo no existe en disco.",
                })
                per_format_stats.setdefault(extension, {"exitosos": 0, "fallidos": 0})
                per_format_stats[extension]["fallidos"] += 1
                continue

            try:
                result = extractor(full_path)
            except Exception as exc:  # defensivo: un archivo puntual corrupto no debe tumbar la corrida completa
                result = ExtractionResult(None, "excepcion", [str(exc)])

            if not result.ok:
                per_format_stats[extension]["fallidos"] += 1
                extraction_failures.append({
                    "file_id": file_id,
                    "title": title,
                    "local_path": local_path,
                    "extension": extension,
                    "reason": "; ".join(result.warnings) or "Extracción devolvió texto vacío.",
                })
                continue

            cleaned_text, pua_removed = _strip_pua_glyphs(result.text)
            if pua_removed:
                result.warnings.append(
                    f"Se eliminaron {pua_removed} caracteres del Área de Uso Privado "
                    "Unicode (glyphs de una fuente incrustada no resuelta correctamente "
                    "a texto real; ver _strip_pua_glyphs en este módulo)."
                )
                print(
                    f"[ADVERTENCIA] '{title}': se limpiaron {pua_removed} caracteres "
                    "de glyphs no-textuales (fuente de símbolos incrustada) antes de trocear."
                )

            chunks, sin_estructura = chunk_document_text(cleaned_text, source_name=title)
            total_chunks += len(chunks)
            per_format_stats[extension]["exitosos"] += 1

            resolved_url, url_fuente = resolve_document_url(doc)
            doc_record = {
                "file_id": file_id,
                "title": title,
                "local_path": local_path,
                "url_final": resolved_url,
                "extension": extension,
                "extraction_method": result.method,
                "extraction_warnings": result.warnings,
                "sin_estructura_articulo": sin_estructura,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
            if url_fuente is not None:
                # Solo se agrega cuando url_final NO vino directo de
                # manifest.url_final (fallback a url_ver, o null explícito
                # sin URL real disponible) — ver resolve_document_url().
                doc_record["url_final_fuente"] = url_fuente
            _write_json(OUTPUT_DIR / f"{file_id}.json", doc_record)

            processed_documents.append({
                "file_id": file_id,
                "title": title,
                "extension": extension,
                "extraction_method": result.method,
                "chunk_count": len(chunks),
                "sin_estructura_articulo": sin_estructura,
            })

            if sin_estructura and len(sin_estructura_examples) < 8:
                sin_estructura_examples.append({"file_id": file_id, "title": title, "extension": extension})
            if not sin_estructura and len(success_examples) < 5:
                success_examples.append({
                    "file_id": file_id,
                    "title": title,
                    "articulo_numero": chunks[0]["articulo_numero"],
                    "texto_snippet": chunks[0]["texto"][:220],
                })
    finally:
        _shutdown_word_application()

    elapsed = time.monotonic() - started_at

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "external_source": {
            "manifest_path": str(external_root / MANIFEST_FILENAME),
            "archivos_dir": str(archivos_dir),
        },
        "manifest_totals": {
            "entradas_totales": len(all_documents),
            "downloaded_raw": len(downloaded_raw),
            "downloaded_unicos": len(downloaded),
            "duplicados_descartados": duplicate_count,
            "failed": len(failed_raw),
        },
        "archivos_en_disco_no_referenciados_por_manifest": {
            "cantidad": len(unreferenced_on_disk),
            "nota": (
                "Archivos presentes en originales/_archivos/ que ninguna entrada del "
                "manifest referencia (ni siquiera como 'failed'); no se procesan en esta "
                "etapa (pipeline manifest-driven), solo se listan para que la brecha "
                "quede visible. Incluye al menos un archivo que no es una Normativa "
                "ARCSA ('Precios y Comparativa de Modelos IA.pdf')."
            ),
            "archivos": unreferenced_on_disk,
        },
        "descargas_fallidas_gap": [
            {
                "title": d.get("title_original"),
                "url_final": d.get("url_final") or d.get("url_ver"),
                "error": d.get("error"),
                "breadcrumb": d.get("_breadcrumb"),
            }
            for d in failed_raw
        ],
        "extraccion_por_formato": per_format_stats,
        "extraccion_fallida": extraction_failures,
        "total_chunks_producidos": total_chunks,
        "documentos_procesados_exitosamente": len(processed_documents),
        "documentos_sin_estructura_articulo": {
            "cantidad": sum(1 for d in processed_documents if d["sin_estructura_articulo"]),
            "decision": (
                "Se conserva el documento completo, troceado por tamaño con "
                f"solapamiento en fragmentos de hasta {MAX_SAFE_CHUNK_CHARS} "
                "caracteres (articulo_numero='FRAGMENTO_<i>_DE_<n>', campo "
                "'sin_estructura_articulo': true) en vez de descartarlo o de "
                "guardarlo como un único chunk gigante no embebible — ver "
                "_fallback_size_based_chunks() en este módulo."
            ),
            "ejemplos": sin_estructura_examples,
        },
        "ejemplos_chunks_con_estructura_articulo": success_examples,
        "elapsed_seconds": round(elapsed, 1),
        "output_dir": str(OUTPUT_DIR),
    }

    _write_json(REPORT_PATH, report)

    print(f"[INFO] Documentos procesados con éxito: {len(processed_documents)}/{len(downloaded)}")
    print(f"[INFO] Total de chunks producidos: {total_chunks}")
    print(f"[INFO] Documentos sin estructura de Artículo (fallback aplicado): {report['documentos_sin_estructura_articulo']['cantidad']}")
    print(f"[INFO] Fallos de extracción: {len(extraction_failures)}")
    print(f"[INFO] Reporte escrito en '{REPORT_PATH}'.")
    print(f"[INFO] Tiempo total: {report['elapsed_seconds']}s")

    return report


if __name__ == "__main__":
    run_extraction()
