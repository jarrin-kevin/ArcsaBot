"""
Módulo de extracción de texto + chunking para el Corpus Documental de
Normativa ARCSA, a partir de los 320 archivos originales (PDF/DOC/XLSX)
descargados por el scraper externo "arcsaPlayright" desde
https://www.controlsanitario.gob.ec/documentos-vigentes/.

Esta es una etapa NUEVA y SEPARADA del pipeline: NO modifica
chatbot/ingestion.py, chatbot/tutorial_ingestion.py, chatbot/link_validation.py
ni chatbot/vector_store.py. Reutiliza parse_normativa()/to_documents() de
chatbot/ingestion.py para el chunking a nivel de Artículo (ver CONTEXT.md);
aquí solo se resuelve la parte que ingestion.py no hace: leer el manifest
externo, extraer el texto crudo de cada formato binario (PDF/DOC/XLSX), y
escribir el resultado como chunks RAG-ready dentro del repo.

La carpeta externa (C:\\Users\\jarri\\Downloads\\arcsaPlayright, ver
DEFAULT_EXTERNAL_ROOT más abajo) es de SOLO LECTURA: este módulo nunca
escribe ni modifica nada ahí. Tampoco copia los binarios originales
(PDF/DOC/XLSX) al repo — el repo se queda solo con el texto ya extraído y
troceado (mucho más liviano), en chatbot/data/normativa/.

Estructura real del manifest.json externo (verificada contra el archivo
real, NO es una lista plana de 359 entradas como se asumió inicialmente):

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

Es un árbol sections -> subsections -> documents; hay que recorrerlo
recursivamente (una subsección puede a su vez tener sub-subsecciones). Tras
aplanar el árbol hay 359 entradas de documento en total, pero el MISMO
archivo físico puede estar listado más de una vez bajo distintas
secciones/subsecciones (un documento clasificado en más de una categoría):
se deduplica por "file_id" (equivalente a deduplicar por "local_path") antes
de extraer texto, para no generar chunks duplicados. Deduplicado: 303
documentos "downloaded" únicos + 16 "failed" (sin archivo local, ver más
abajo) = 319 entradas únicas contables. El disco tiene 320 archivos porque
hay 17 archivos extra en _archivos/ que NO están referenciados por NINGUNA
entrada del manifest (ver `find_unreferenced_disk_files()`): se reportan
como una brecha aparte, pero NO se procesan aquí (este pipeline es
manifest-driven, tal como se especificó; inventar a qué entrada
corresponden esos 17 archivos sería adivinar, no verificar).

Política "flag, don't drop" (ver ADR 0004, ya usada en link_validation.py y
tutorial_ingestion.py): un documento cuya extracción falla, o cuyo texto no
tiene ningún encabezado de Artículo, NUNCA se descarta en silencio. Se
marca explícitamente en el reporte y, cuando hay texto aprovechable, se
conserva igual — ver `_fallback_size_based_chunks` para cómo se trocea ese
texto (fallback de tamaño con solapamiento, no un único chunk gigante).

LIMITACIÓN DE DISEÑO: identificación de requisitos / no-cobertura de la
segmentación por Artículo (documentada aquí porque es evidencia real para
la sección de "identificación de requisitos" y limitaciones de este
proyecto, no solo una nota de implementación)
--------------------------------------------------------------------------
`parse_normativa()` (chatbot/ingestion.py) implementa la unidad de
fragmentación PREFERIDA de este proyecto: un chunk por Artículo, para que
una obligación y sus excepciones nunca queden cortadas a la mitad (ver
CONTEXT.md). Esa vía sigue siendo la principal y NO se modifica acá. Pero
al samplear manualmente el texto real de los documentos donde
`ARTICULO_HEADER_PATTERN` no encuentra ningún encabezado (159 de 317
archivos del corpus real al momento de esta investigación, 2026-09-08), se
confirmó que NO es un bug de extracción de PDF ni una falla del regex:

  a) ~55 documentos (35%) no contienen la palabra "Artículo"/"Art." en
     ningún lugar del texto: son Informes AIR (análisis de impacto
     regulatorio), Instructivos Externos/Internos organizados por
     numerales propios (no por "Art. N.-"), Planes Regulatorios
     institucionales, cuestionarios PUIP-UE, checklists (incluyendo el
     único .xlsx del corpus) e informes técnicos de la OMS/WHO. Ninguno de
     estos usa la convención de Artículo: no hay unidad jurídica que
     dividir, el documento completo (o sus secciones propias) ES la unidad
     natural.

  b) ~104 documentos (65%) SÍ contienen la palabra "artículo"/"Art." pero
     el regex correctamente NO la trata como encabezado propio, porque
     aparece citando un artículo de OTRO instrumento (la Constitución, la
     Ley Orgánica de Salud, otra Resolución) dentro de un párrafo de
     "CONSIDERANDO" o entre comillas — nunca al inicio de línea con el
     formato real de encabezado. Ejemplo real verificado (arcsa_11236.json):
     el texto contiene '"Art.  20.-  Todas  las  reacciones..."' pero
     precedido por una comilla de apertura (“) como cita textual de otra
     Resolución, no como el Artículo 20 de ESTE documento. Relajar el
     regex para capturar estos casos rompería la segmentación jurídica real
     (crearía un "Artículo" falso a partir de una cita ajena, mezclado con
     el texto del propio documento). Por eso este caso se atiende con el
     fallback de tamaño, no con un ajuste de ARTICULO_HEADER_PATTERN.

  Una sub-variante menor detectada (9/159, ~6%) sí sería recuperable con
  una mejora futura y de bajo riesgo del regex: encabezados reales de tipo
  "Artículo Único.-"/"Artículo Primero.-" (ordinales en vez de dígitos),
  usados en Resoluciones de un solo artículo. Se documenta como mejora
  futura y se deja fuera de esta corrección para no tocar el camino ya
  verificado que funciona para el 93%+ del corpus.

LIMITACIÓN CONOCIDA Y ACOTADA: el tamaño en CARACTERES no es un proxy
perfecto del tamaño en TOKENS reales
--------------------------------------------------------------------------
El chunking de tamaño de este módulo (_fallback_size_based_chunks,
_resplit_oversized_chunk) usa un presupuesto fijo en CARACTERES
(MAX_SAFE_CHUNK_CHARS), calibrado empíricamente contra la API real de
tokens de Gemini (ver esas funciones). Esa calibración asume una densidad
de ~3.3-4.5 caracteres/token, verificada sobre una muestra amplia de
documentos reales del corpus (español jurídico, inglés técnico OMS,
checklists tabulares). Durante la verificación final de este mismo fix se
encontró UN documento real (arcsa_15413.json, "Resolución CID-001-2025",
un anexo con tablas de sustancias controladas y números CAS) cuya
densidad real es muchísimo mayor — hasta ~0.64 tokens/carácter, casi 2
veces peor que el peor caso muestreado — por dos motivos verificados:
  1) Una fuente PDF incrustada con codificación de símbolos propia que
     PyMuPDF no resuelve a Unicode real (glyphs del Área de Uso Privado,
     ver _strip_pua_glyphs, que ya limpia este caso — era el 8.7% de los
     caracteres del documento).
  2) Incluso ya limpio de esos glyphs, el texto remanente (nombres
     químicos IUPAC largos, números CAS con guiones, símbolos como "α")
     sigue tokenizando de forma más densa que el texto jurídico normal.
  Esto es INHERENTE a cualquier presupuesto de chunking basado en
  caracteres (no solo a este): ningún tamaño fijo en caracteres puede
  garantizar un tope de tokens exacto para contenido de densidad atípica
  sin consultar el tokenizer real en cada chunk — algo que este módulo
  deliberadamente NO hace, porque agregaría una dependencia de red/API a
  una etapa de extracción que hoy es 100% local y determinística, solo
  para 1 de 317 documentos reales del corpus (verificado: ningún otro
  archivo supera el 1% de caracteres PUA, ver _strip_pua_glyphs).
  Mitigación real: chatbot/vector_ingest.py::embed_documents() ya aísla y
  reporta como fallo individual (sin abortar la corrida) cualquier chunk
  que la API de embeddings rechace por motivo de contenido — el mismo
  mecanismo de resiliencia que ya cubre cualquier otro error de contenido
  puntual. Un puñado de fragmentos de este único documento pathológico
  puede terminar en esa lista de fallos reportados en vez de embeberse; se
  documenta acá como limitación conocida y acotada, no como un bug sin
  investigar.
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

# Algunos títulos reales del corpus (y algún mensaje de error del scraper)
# traen caracteres Unicode que la consola de Windows (cp1252) no puede
# codificar. Igual que en link_validation.py: se reconfigura stdout/stderr a
# UTF-8 con reemplazo de caracteres no soportados para que una corrida sobre
# los 320 archivos reales no se caiga a mitad de camino solo por un print().
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
# los 320 binarios en originales/_archivos/). Configurable vía variable de
# entorno para no dejar la ruta absoluta de una sola máquina hardcodeada de
# forma rígida, pero con el valor real de este proyecto como default.
DEFAULT_EXTERNAL_ROOT = Path(
    os.environ.get("ARCSA_SOURCE_ROOT", r"C:\Users\jarri\Downloads\arcsaPlayright")
)
MANIFEST_FILENAME = "manifest.json"
ARCHIVOS_SUBDIR = Path("originales") / "_archivos"

# Salida DENTRO del repo: solo texto/chunks, nunca los binarios originales.
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "normativa"
REPORT_PATH = Path(__file__).resolve().parent / "data" / "normativa_extraction_report.json"

# Prefijo usado para el "articulo_numero" de los chunks de respaldo de
# documentos sin ningún encabezado de Artículo propio (ver decisión
# documentada en el docstring del módulo y en _fallback_size_based_chunks).
# Cada fragmento se numera como f"{FRAGMENTO_SENTINEL_PREFIX}_{i}_DE_{n}"
# (p. ej. "FRAGMENTO_3_DE_45"), nunca como un único "DOCUMENTO_COMPLETO":
# ver el fix del 2026-09-08 documentado en _fallback_size_based_chunks.
FRAGMENTO_SENTINEL_PREFIX = "FRAGMENTO"

# Tamaño (en caracteres) y solapamiento máximos seguros para CUALQUIER
# chunk que se vaya a embeber con gemini-embedding-001 (límite real de
# 2048 tokens/texto). Se usan en dos lugares distintos de este módulo:
#   1) _fallback_size_based_chunks: documentos SIN ningún Artículo propio
#      (parse_normativa devolvió []) — ver esa función para la
#      justificación completa y la medición empírica real contra la API
#      de tokens de Gemini que sustenta estos dos números.
#   2) _resplit_oversized_chunk: red de seguridad para el caso (raro pero
#      real, ver esa función) en que un chunk de ARTÍCULO GENUINO
#      (parse_normativa SÍ encontró headers) igual resulta demasiado
#      grande para embeberse.
# Mismos números en ambos casos porque el límite real de la API es el
# mismo — no hay motivo para dos presupuestos de tamaño distintos.
MAX_SAFE_CHUNK_CHARS = 4500
MAX_SAFE_CHUNK_OVERLAP_CHARS = 400

# Al buscar dónde cortar cerca de MAX_SAFE_CHUNK_CHARS, se retrocede como
# máximo esta cantidad de caracteres buscando un espacio en blanco, para
# no cortar una palabra a la mitad. Si no se encuentra ninguno en ese
# rango (texto sin espacios, caso extremo), se corta igual en el límite
# duro: es preferible una palabra partida a un chunk sin límite de tamaño.
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
    de TODAS las entradas de documento (359 en la data real), sin deduplicar
    todavía. Cada entrada conserva sus campos originales del manifest más
    "_breadcrumb" (ver _walk_manifest_node).
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
    Resuelve la URL pública real de un documento del manifest, con
    fallback documentado.

    HALLAZGO REAL (investigación 2026-09-08, 145/317 archivos de
    chatbot/data/normativa/ con url_final == "about:blank", 46% del
    corpus): el manifest.json externo trae, por documento, "url_final"
    (la URL a la que Playwright navegó tras intentar la descarga) y
    "url_ver" (la URL del enlace "ver/descargar" tal como aparece en la
    página de origen — el endpoint real de WordPress Download Monitor,
    .../download-monitor/download.php?id=<N>&force=0). Para 150
    documentos del corpus real, el manifest registra
    "strategy_used": "direct_download_event": el scraper disparó la
    descarga vía un evento JS (sin navegación real de página), así que
    Playwright capturó el literal "about:blank" en "url_final" en vez de
    una URL real — NO es un documento sin URL de origen, es un artefacto
    de esa estrategia de descarga puntual. "url_ver" sí queda intacto en
    esos casos porque se captura del enlace de la página ANTES de
    disparar la descarga, sea cual sea la estrategia usada después.
    Verificado con una descarga real (WebFetch) que "url_ver" sirve el
    mismo PDF (mismo tamaño en bytes que el manifest registró vía
    sha256/bytes), así que es una URL real y no una URL inventada.

    Por eso la prioridad de resolución es:
      1) doc["url_final"] si es una URL real (caso normal: la enorme
         mayoría de estrategias sí navegan a una URL real).
      2) doc["url_ver"] si "url_final" no es real (fallback para el caso
         "direct_download_event" descrito arriba).
      3) None explícito si ninguno de los dos es una URL real (no se
         inventa una URL falsa — ver política "flag, don't drop").

    Devuelve (url_o_none, nota_de_fuente_o_none). La nota solo se genera
    cuando se usó el fallback o cuando no hay ninguna URL real, para que
    quede trazable en el JSON de salida por qué el valor no vino
    directamente de "url_final".
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
    Compara los archivos realmente presentes en originales/_archivos/ contra
    los "local_path" de las entradas "downloaded" del manifest. Devuelve los
    nombres de archivo que existen en disco pero que NINGUNA entrada del
    manifest referencia (ni siquiera como "failed", que de por sí no tiene
    archivo local).

    Verificado contra la data real: hay 17 de estos. Incluyen documentos que
    parecen legítimos de ARCSA (p.ej. cuestionarios PUIP-UE) que el scraper
    nunca llegó a registrar, y al menos un archivo que NO es una normativa
    ARCSA en absoluto ("Precios y Comparativa de Modelos IA.pdf", claramente
    ajeno al scrape). Este pipeline es manifest-driven según lo especificado
    (itera entradas del manifest, no el directorio a ciegas): estos 17
    archivos se REPORTAN como brecha para que quede visible, pero NO se
    procesan — adivinar a qué documento del sitio corresponde cada uno (y si
    de verdad es una Normativa ARCSA, como el caso claro que no lo es) está
    fuera del alcance de esta etapa.
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

    HALLAZGO REAL que motiva esta limpieza (2026-09-08, durante la
    verificación de este mismo fix de chunking): al auditar tokens reales
    contra la API de Gemini sobre una muestra de chunks ya generados, se
    encontró que dos fragmentos de arcsa_15413.json ("Resolución
    CID-001-2025", un anexo con tablas de sustancias controladas y sus
    números CAS) medían 4500 caracteres pero ¡3760 y 4411 TOKENS reales! —
    muy por encima del límite de 2048, y muy por encima de la conversión de
    ~3.3-4.5 caracteres/token observada en el resto del corpus (ver
    _fallback_size_based_chunks). La causa real: ese PDF incrusta una
    fuente con codificación de símbolos propia (probablemente para
    notación química), y PyMuPDF, al no poder resolver el cmap de esa
    fuente a Unicode real, devuelve los códigos de glyph crudos como
    puntos de código del Área de Uso Privado (p. ej. "\\uf063\\uf061\\uf063\\uf069\\uf064"
    donde debería haber texto legible). Son bytes sin significado
    semántico fuera de esa fuente específica — nunca texto real citable
    para RAG — y el tokenizer de Gemini los trata como texto exótico de
    baja frecuencia, tokenizando casi carácter por carácter (~1
    token/carácter en vez de ~0.3), lo que rompe la garantía de tamaño de
    CUALQUIER presupuesto fijo en caracteres.

    Verificado que es un caso aislado en el corpus real (1 de 317
    archivos, 8.7% de los caracteres de ese documento — ningún otro
    archivo supera el 1%), así que la solución no es reducir el tamaño de
    chunk para todo el corpus (penalizaría innecesariamente al resto con
    muchos más chunks), sino eliminar este contenido no-textual en la
    fuente: es una excepción justificada a la política "flag, don't drop"
    (ver ADR 0004) porque lo que se elimina no es información real, es
    ruido de decodificación de fuente que ya era inútil para RAG antes de
    este fix (un LLM no puede leer glyphs de una fuente de símbolos como
    texto). Se documenta la cantidad eliminada en "extraction_warnings"
    del documento afectado en vez de descartarla en silencio.
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

    Este proyecto ya verificó por separado (diagnóstico previo) que estos
    310 PDF tienen capa de texto nativa (no son escaneos), así que un
    `get_text()` directo por página basta. Aun así, cualquier página cuyo
    texto extraído quede vacío/en blanco se registra en "warnings" — no se
    descarta la página en silencio, se deja constancia (ver política
    "flag, don't drop"), porque una página en blanco inesperada dentro de un
    documento nativo puede ser una imagen incrustada suelta o un anexo
    escaneado colado en medio de un documento por lo demás nativo.
    """
    warnings: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # archivo corrupto/no abrible pese al diagnóstico previo
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
    hoja por hoja, fila por fila. Es un caso marginal (1 solo archivo en el
    corpus real, un checklist), así que se mantiene deliberadamente simple:
    no se intenta preservar la estructura tabular, solo recuperar el texto
    para que parse_normativa() pueda buscar encabezados de Artículo en él
    (lo más probable, dado que es un checklist, es que no tenga ninguno y
    caiga en el flujo sin_estructura_articulo).
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
    Microsoft Word vía COM para abrir los .doc legacy. python-docx NO
    soporta el formato binario .doc (solo .docx), y no hay una librería
    Python pura instalada en este entorno que lo soporte limpiamente; Word
    ya está instalado en esta máquina (verificado: version 16.0), así que
    es la vía más fiel disponible para estos 9 archivos. Se desactivan
    alertas y confirmaciones de conversión para que abrir un .doc viejo
    nunca se quede esperando un diálogo que nadie va a contestar.
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
    en orden:

      1. Microsoft Word vía COM (win32com): la opción más fiel, disponible
         en este entorno (Word 16.0 instalado). Verificado contra un
         archivo real del corpus (cuestionario PUIP-UE): extrae texto
         limpio y completo.
      2. antiword (binario externo, presente en este entorno vía
         Git for Windows): respaldo si Word/COM no está disponible o falla
         para un archivo puntual.

    Si ambas fallan, se devuelve un ExtractionResult sin texto y con el
    motivo en "warnings": el documento se reporta como
    "unsupported_format"/gap, nunca se inventa contenido (ver política
    "honest gap is better than garbage output" del enunciado de esta tarea).
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

    Si `text` ya entra dentro de `chunk_size`, devuelve una lista de un solo
    elemento (no fuerza una división innecesaria de documentos ya
    pequeños). En caso contrario:

      1. Avanza una ventana [start, start+chunk_size).
      2. Si esa ventana no llega al final del texto, retrocede desde el
         corte hasta el último espacio en blanco dentro de
         `boundary_lookback` caracteres, para cortar entre palabras en vez
         de partir una a la mitad. Si no hay ningún espacio en ese rango
         (texto sin espacios, caso extremo no observado en el corpus real
         pero posible), corta igual en el límite duro.
      3. La siguiente ventana empieza `overlap` caracteres antes del corte
         anterior, para que una obligación que quedó cerca del límite no
         pierda su contexto inmediato en el chunk siguiente. Siempre avanza
         al menos 1 carácter para garantizar terminación.
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
    un documento cuyo texto NO contiene ningún encabezado de Artículo
    propio (parse_normativa devolvió []).

    POR QUÉ EXISTE ESTE FALLBACK (y por qué no es la vía preferida)
    ------------------------------------------------------------------
    La unidad de fragmentación preferida de este proyecto es el Artículo
    (parse_normativa() en chatbot/ingestion.py, sin modificar por este
    fix): una obligación jurídica y sus excepciones nunca deben quedar
    cortadas a la mitad entre dos chunks (ver CONTEXT.md). Ese criterio
    solo es aplicable a documentos que EFECTIVAMENTE están redactados como
    una secuencia de "Art. N.-"/"Artículo N.-". Para el resto —
    Instructivos organizados por numerales propios, Informes AIR,
    checklists, cuestionarios, Planes institucionales, informes técnicos
    de la OMS/WHO (ver el análisis completo en el docstring del módulo,
    sección "LIMITACIÓN DE DISEÑO")— no existe un Artículo que preservar:
    la única alternativa razonable a descartar el documento es trocearlo
    por tamaño.

    FIX del 2026-09-08 (por qué YA NO es un único chunk "DOCUMENTO_COMPLETO")
    ------------------------------------------------------------------
    Antes de este fix, todo documento sin Artículo se guardaba como UN
    solo chunk con el texto completo (hasta 1 339 954 caracteres en el
    caso real más extremo del corpus, arcsa_13953.json). La API de
    embeddings usada por este proyecto (gemini-embedding-001, ver
    chatbot/vector_store.py) tiene un límite real de 2048 tokens por texto
    de entrada. Medido empíricamente contra la API real (no asumido) con
    `google.genai.Client().models.count_tokens(model="models/gemini-
    embedding-001", contents=...)` sobre varios documentos reales de este
    corpus:

        8000 caracteres  -> 2335 tokens  (texto legal en español)
        8192 caracteres  -> 2385 tokens  (¡ya por encima del límite real!)
        6000 caracteres  -> 1716-1841 tokens según el documento
        5000 caracteres  -> 1118-1530 tokens según el documento

    La conversión real observada varía entre ~3.3 y ~4.5 caracteres/token
    según el documento (más densa en español jurídico, más laxa en un
    informe técnico en inglés de la OMS o en un checklist tabular). Esto
    invalida la suposición ingenua de "~4 caracteres/token" que llevaría a
    pensar que 8192 caracteres son un límite seguro: NO lo son, ya exceden
    2048 tokens en la muestra real. De los 159 documentos sin Artículo
    verificados en el corpus real, 145 (91%) superan los 7000 caracteres,
    es decir, casi todos habrían excedido el límite real de la API con el
    chunk único anterior (y de hecho jamás llegaron a embeberse: ver
    chatbot/vector_ingest.py).

    Por eso, `MAX_SAFE_CHUNK_CHARS = 4500` (con
    `MAX_SAFE_CHUNK_OVERLAP_CHARS = 400` de solapamiento) se eligió con
    margen amplio por debajo del límite real: incluso en el documento más
    denso en tokens muestreado (arcsa_14441.json), 4500 caracteres midieron
    ~1530 tokens reales, ~75% del límite de 2048 — deja margen para
    variación de densidad entre documentos sin acercarse al límite. El
    solapamiento de 400 caracteres (~9% del tamaño de chunk) evita que una
    frase que caiga justo en el límite de un chunk pierda su contexto
    inmediato en el fragmento siguiente, sin inflar demasiado el total de
    chunks generados.

    IDENTIFICADOR ESTABLE
    ------------------------------------------------------------------
    Cada fragmento usa "articulo_numero" = f"FRAGMENTO_{i}_DE_{n}" (p. ej.
    "FRAGMENTO_3_DE_45"): estable entre corridas (la extracción de texto es
    determinística para el mismo archivo fuente) y legible, ya que no existe
    un número de Artículo real que citar. Compatible sin cambios con el
    esquema de IDs deterministas de chatbot/vector_ingest.py
    ("normativa:<file_id>:<index_in_file>:<articulo_numero>"): i nunca se
    repite dentro del mismo documento, así que no hay colisión aunque
    "_index_in_file" ya lo distinga igual por separado. Si el documento ya
    entra en un solo chunk (no necesitó dividirse), n=1 y solo se genera
    "FRAGMENTO_1_DE_1" — no se fuerza una división innecesaria de
    documentos ya pequeños (11/159 en el corpus real).
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
    parse_normativa(), no del fallback): si de por sí ya entra dentro de
    MAX_SAFE_CHUNK_CHARS, se devuelve sin cambios (no-op para la enorme
    mayoría del corpus). Si no entra, se divide con el mismo criterio de
    sliding-window + solapamiento que _fallback_size_based_chunks.

    HALLAZGO ADICIONAL (2026-09-08, durante la verificación de este mismo
    fix): al auditar el corpus completo para confirmar que NINGÚN chunk
    quedara por encima del límite seguro tras el fallback de tamaño, se
    encontró que el camino de Artículo genuino — que este fix
    explícitamente NO debía tocar — también produce chunks demasiado
    grandes para embeberse en 156 de ~4200 casos reales, hasta 219 534
    caracteres en un solo "Artículo 3" (arcsa_15660.json). Causa real
    verificada: cuando un documento largo (anexos, tablas de tasas,
    especificaciones técnicas) solo tiene unos pocos encabezados de
    Artículo reales y ninguno más en el resto del texto,
    ARTICULO_HEADER_PATTERN encuentra correctamente esos pocos
    encabezados, pero parse_normativa() atribuye TODO el texto hasta el
    siguiente encabezado (o el final del documento) al último Artículo
    encontrado — comportamiento correcto y esperado de esa función para
    un Artículo genuinamente largo, pero indistinguible aquí de un Artículo
    corto seguido de contenido sin estructura que igual quedó adentro.

    Esta función NO modifica parse_normativa()/ARTICULO_HEADER_PATTERN (la
    vía preferida sigue intacta) ni cambia el resultado para el 96%+ de los
    chunks que ya son chicos: solo agrega una división adicional, tras el
    hecho, cuando el chunk que esa vía ya produjo sigue siendo inembebible.
    El "articulo_numero" original se conserva como prefijo
    (f"{articulo_numero}_PARTE_{i}_DE_{n}", p. ej. "48_PARTE_2_DE_9") para
    que quede claro que estas partes pertenecen al mismo Artículo real, a
    diferencia del prefijo "FRAGMENTO_" reservado para documentos sin
    Artículo. Se marca "articulo_dividido_por_tamano": True (distinto de
    "sin_estructura_articulo", que sigue en False: el Artículo SÍ existe,
    solo se dividió por tamaño).
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
    crudo ya extraído.

    Si SÍ se encontraron Artículos, cada chunk todavía pasa por
    _resplit_oversized_chunk() como red de seguridad de tamaño (no-op para
    la enorme mayoría — ver esa función para el hallazgo real que la
    justifica). Si no se encontró ningún Artículo, aplica el fallback de
    tamaño con solapamiento (ver _fallback_size_based_chunks).

    Devuelve (chunks, sin_estructura_articulo). "sin_estructura_articulo"
    describe al DOCUMENTO (True solo cuando no tiene ningún Artículo
    propio), no a cada chunk individual — un documento con Artículos reales
    sigue reportando False aquí aunque alguno de sus chunks se haya
    dividido por tamaño (ver "articulo_dividido_por_tamano" en el chunk).
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
