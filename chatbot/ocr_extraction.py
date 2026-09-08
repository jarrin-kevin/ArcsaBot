"""
Módulo de extracción vía OCR para los 7 PDF de Normativa ARCSA que
`chatbot/normativa_extraction.py` NO pudo procesar porque son escaneos
puros (cada página es una sola imagen rasterizada de página completa, sin
ninguna capa de texto extraíble — verificado página por página antes de
escribir este módulo, ver `chatbot/data/normativa_extraction_report.json`,
sección "extraccion_fallida").

Decisión de herramienta (ver docs/adr/0003-self-hosted-ocr.md): el ADR ya
decidió OCR self-hosted (vendor-independiente, sin API de nube) con
Tesseract vía pytesseract como opción por defecto, escalando a
PaddleOCR/docTR solo si la precisión de Tesseract resulta insuficiente.

En ESTE entorno (Windows, sin privilegios de administrador interactivos)
Tesseract NO se pudo instalar de forma headless:
  - No hay binario de Tesseract ya instalado (ni en PATH ni en
    "C:\\Program Files\\Tesseract-OCR\\").
  - El instalador oficial de Tesseract para Windows (NSIS, UB-Mannheim)
    trae un manifiesto que exige elevación de UAC sin importar el
    directorio de instalación elegido (se probó instalar en una carpeta
    de usuario vía `/D=`, y aun así Windows rechazó la elevación con
    "El usuario ha cancelado la operación" — no hay ningún usuario
    interactivo en este entorno para aceptar el UAC).
  - `pip install tesserocr` tampoco sirve de atajo: no hay wheel
    precompilado para Windows/Python 3.12 y su build intenta enlazar
    contra una libtesseract del sistema que no existe aquí.
Por lo tanto, siguiendo lo que el propio ADR 0003 ya autoriza como
escalón siguiente (PaddleOCR/docTR — ambos self-hosted, sin API de
nube, cumpliendo el mismo requisito de independencia de proveedor que
motivó el ADR), este módulo usa PaddleOCR. Se instaló en un entorno
virtual aparte en `C:\\ocrenv` (fuera del `.venv` del proyecto) porque el
intérprete de Python de Microsoft Store usado por el proyecto tiene una
ruta de site-packages tan profunda que instalar PaddlePaddle (que incluye
árboles de headers C++ muy anidados, p. ej. rutas bajo
`.../cutlass_extensions/epilogue/...`) supera el límite MAX_PATH de
Windows. Este módulo se ejecuta con ese intérprete
(`C:\\ocrenv\\Scripts\\python.exe`), pero solo importa
`chatbot.ingestion.parse_normativa` (mismo chunking a nivel de Artículo
que usa el resto del pipeline) — no depende de nada específico de ese
entorno salvo `paddleocr` y `pymupdf`.

Alcance deliberadamente acotado: NO reintenta los 296 documentos que ya
se extrajeron con éxito por vía nativa, NO modifica
`chatbot/normativa_extraction.py` ni su reporte
(`chatbot/data/normativa_extraction_report.json` se lee, nunca se
escribe), y reutiliza `parse_normativa()` de `chatbot/ingestion.py` sin
tocar ese módulo. Escribe sus propios archivos de salida:
  - Un JSON por documento en `chatbot/data/normativa/` (mismo directorio
    y mismo formato de esquema que usa normativa_extraction.py, para que
    un futuro paso de indexado los trate exactamente igual), con
    "extraction_method": "ocr" tanto a nivel de documento como dentro de
    cada chunk (el chunk-level no existía en el esquema previo — se
    agrega aquí de forma aditiva, sin tocar parse_normativa(), para que
    cualquier consumidor pueda distinguir un chunk nativo, implícitamente
    "native", de uno OCR sin ambigüedad).
  - Un reporte aparte, `chatbot/data/ocr_extraction_report.json`, que dejar
    explícito que estos 7 documentos vienen de OCR (confianza menor que
    la extracción nativa) y no pisa el reporte de la etapa anterior.

Política "flag, don't drop" (igual que en normativa_extraction.py, ADR
0004): un documento cuyo OCR sale vacío o ilegible NUNCA se fuerza dentro
del corpus disfrazado de bueno. Se marca `ocr_quality: "failed"` (o
"poor") en el reporte para que quede visible y un humano decida.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Igual que en normativa_extraction.py/link_validation.py: algunos títulos
# y textos reales (y este propio log, que imprime títulos con tildes) usan
# caracteres que la consola de Windows (cp1252) no puede codificar. Se
# reconfigura stdout/stderr a UTF-8 con reemplazo para que una corrida real
# no se caiga a mitad de camino solo por un print().
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Debe fijarse ANTES de importar paddleocr (lee el flag al importar
# paddlex.utils.flags): en este entorno, PP-OCRv6_medium_det con MKL-DNN
# habilitado (el modo por defecto en CPU) revienta con
# "NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
# [pir::ArrayAttribute<pir::DoubleAttribute>]" al correr el modelo de
# detección de texto — un bug de la combinación paddlepaddle 3.3.1 +
# oneDNN + nuevo IR (PIR) en este build de Windows/CPU, no un problema de
# nuestro código. Desactivar MKL-DNN (ejecución en modo "paddle" puro,
# más lenta pero funcional en CPU) evita el bug. Verificado con un smoke
# test real antes de escribir este módulo.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

import fitz  # PyMuPDF
import json

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ingestion import parse_normativa
else:
    from chatbot.ingestion import parse_normativa


# --------------------------------------------------------------------------
# Rutas (mismo patrón que normativa_extraction.py)
# --------------------------------------------------------------------------

DEFAULT_EXTERNAL_ROOT = Path(
    os.environ.get("ARCSA_SOURCE_ROOT", r"C:\Users\jarri\Downloads\arcsaPlayright")
)
ARCHIVOS_SUBDIR = Path("originales") / "_archivos"

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "normativa"
NATIVE_REPORT_PATH = Path(__file__).resolve().parent / "data" / "normativa_extraction_report.json"
OCR_REPORT_PATH = Path(__file__).resolve().parent / "data" / "ocr_extraction_report.json"

# DPI de renderizado de página a imagen. 300 da buena densidad de detalle
# para OCR de texto impreso; PaddleOCR reescala internamente si supera su
# límite interno de lado máximo (4000px), así que un DPI algo generoso acá
# no rompe nada, solo agrega el resize automático (se ve como advertencia
# en el log, no como error).
RENDER_DPI = 300

# Umbral de confianza (promedio de rec_scores por página) por debajo del
# cual se marca la página como "poor" en vez de "ok" en el reporte — no
# afecta si el chunk se conserva (ver política flag-don't-drop: igual se
# conserva el texto, pero el reporte deja constancia de que es sospechoso).
LOW_CONFIDENCE_THRESHOLD = 0.70


# --------------------------------------------------------------------------
# Etapa 1: los 7 documentos a procesar, leídos del reporte de la etapa
# nativa (solo lectura, nunca se escribe ahí)
# --------------------------------------------------------------------------

def load_ocr_targets(native_report_path: Path = NATIVE_REPORT_PATH) -> list[dict]:
    """
    Lee `chatbot/data/normativa_extraction_report.json` (generado por
    normativa_extraction.py, que este módulo NUNCA modifica) y devuelve
    las entradas de "extraccion_fallida" cuya extensión es ".pdf" — los 7
    escaneos puros verificados manualmente antes de esta etapa. Cualquier
    entrada .doc/.xlsx fallida (no hay ninguna en la corrida real, pero
    por robustez) se ignora aquí: esta etapa es específicamente para
    escaneos de imagen, no para otros tipos de fallo de extracción.
    """
    with native_report_path.open(encoding="utf-8") as f:
        report = json.load(f)

    fallidos = report.get("extraccion_fallida", [])
    objetivos = [d for d in fallidos if d.get("extension") == ".pdf"]
    return objetivos


# --------------------------------------------------------------------------
# Etapa 2: renderizado de página a imagen + OCR
# --------------------------------------------------------------------------

class PageOcrResult:
    """Resultado de aplicar OCR a una sola página ya renderizada a imagen."""

    def __init__(self, text: str, avg_confidence: float | None, n_boxes: int):
        self.text = text
        self.avg_confidence = avg_confidence
        self.n_boxes = n_boxes


def _get_ocr_engine():
    """
    Crea (una sola vez, reutilizada entre documentos) la instancia de
    PaddleOCR. Se instancia perezosamente porque la primera vez descarga
    los modelos (~decenas de MB) desde el hoster configurado.

    use_doc_orientation_classify/use_doc_unwarping/use_textline_orientation
    se desactivan: los 7 escaneos son fotocopias/escaneos derechos de
    documentos oficiales ARCSA (verificado visualmente), no fotos torcidas
    ni dobladas, así que ese preprocesamiento extra solo agregaría tiempo
    de cómputo sin beneficio.
    """
    global _OCR_ENGINE
    try:
        return _OCR_ENGINE
    except NameError:
        pass

    from paddleocr import PaddleOCR

    _OCR_ENGINE = PaddleOCR(
        lang="es",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    return _OCR_ENGINE


def ocr_pdf(path: Path, tmp_dir: Path) -> tuple[str, list[dict]]:
    """
    Renderiza cada página de `path` a PNG (vía PyMuPDF) y le aplica OCR
    (PaddleOCR). Devuelve (texto_completo_del_documento, detalle_por_pagina)
    donde detalle_por_pagina es una lista de dicts con
    {"pagina", "n_lineas", "avg_confidence", "calidad"} para el reporte.

    El texto de cada página se une con líneas en el orden que devuelve
    PaddleOCR (que ya ordena las cajas de texto detectadas de arriba hacia
    abajo / izquierda a derecha para el pipeline general de OCR, sin
    análisis de layout adicional) — suficiente para que el patrón de
    encabezado de Artículo de `parse_normativa()` (que busca inicio de
    línea) encuentre los "Art. N.-" reales del documento.
    """
    ocr = _get_ocr_engine()
    doc = fitz.open(path)
    pages_text: list[str] = []
    detalle: list[dict] = []

    try:
        for page_number, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=RENDER_DPI)
            img_path = tmp_dir / f"page_{page_number}.png"
            pixmap.save(img_path)

            result = ocr.predict(str(img_path))
            texts: list[str] = []
            scores: list[float] = []
            for res in result:
                texts.extend(res.get("rec_texts", []) or [])
                scores.extend(res.get("rec_scores", []) or [])

            page_text = "\n".join(texts)
            pages_text.append(page_text)

            avg_conf = sum(scores) / len(scores) if scores else None
            calidad = "sin_texto_detectado"
            if texts:
                calidad = "ok" if (avg_conf or 0) >= LOW_CONFIDENCE_THRESHOLD else "baja_confianza"

            detalle.append({
                "pagina": page_number,
                "n_lineas_detectadas": len(texts),
                "avg_confidence": round(avg_conf, 4) if avg_conf is not None else None,
                "calidad": calidad,
            })

            img_path.unlink(missing_ok=True)
    finally:
        doc.close()

    return "\n\n".join(pages_text), detalle


# --------------------------------------------------------------------------
# Etapa 3: chunking (reutilizando parse_normativa, sin modificarlo) +
# marcado explícito de extraction_method a nivel de chunk
# --------------------------------------------------------------------------

SIN_ESTRUCTURA_SENTINEL = "DOCUMENTO_COMPLETO"


def _fallback_whole_document_chunk(text: str, source_name: str) -> dict:
    """Mismo fallback documentado que usa normativa_extraction.py para
    documentos sin ningún encabezado de Artículo (ver ADR 0004,
    "flag, don't drop"): se conserva el documento completo como un único
    chunk en vez de descartarlo."""
    return {
        "articulo_numero": SIN_ESTRUCTURA_SENTINEL,
        "texto": text.strip(),
        "source": source_name,
        "vigente": True,
        "sin_estructura_articulo": True,
    }


def chunk_ocr_text(text: str, source_name: str) -> tuple[list[dict], bool]:
    """
    Aplica parse_normativa() (chatbot/ingestion.py, SIN modificar) al texto
    ya reconocido por OCR, igual que hace normativa_extraction.py con el
    texto nativo. A cada chunk resultante se le agrega "extraction_method":
    "ocr" — parse_normativa() no conoce ese campo (es información de ESTA
    etapa, no del parser genérico), así que se añade aquí de forma
    aditiva sobre los dicts que devuelve, sin tocar ingestion.py.
    """
    chunks = parse_normativa(text, source_name=source_name)
    sin_estructura = False
    if not chunks:
        chunks = [_fallback_whole_document_chunk(text, source_name)]
        sin_estructura = True

    for chunk in chunks:
        chunk["extraction_method"] = "ocr"

    return chunks, sin_estructura


# --------------------------------------------------------------------------
# Etapa 4: orquestación sobre los 7 documentos + reporte
# --------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_ocr_extraction(external_root: Path | None = None) -> dict:
    """
    Ejecuta el pipeline de OCR sobre los 7 PDF escaneados identificados en
    el reporte de la etapa nativa. Escribe un JSON por documento en
    chatbot/data/normativa/ (mismo formato que la etapa nativa, más
    extraction_method a nivel de chunk) y su propio reporte en
    chatbot/data/ocr_extraction_report.json.
    """
    external_root = external_root or DEFAULT_EXTERNAL_ROOT
    archivos_dir = external_root / ARCHIVOS_SUBDIR

    objetivos = load_ocr_targets()
    print(f"[INFO] {len(objetivos)} documento(s) objetivo para OCR (ver extraccion_fallida en el reporte nativo).")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    resultados: list[dict] = []
    total_chunks = 0
    documentos_ocr_fallido: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="arcsa_ocr_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        for i, doc in enumerate(objetivos, start=1):
            file_id = doc["file_id"]
            title = doc["title"]
            local_path = doc["local_path"]
            full_path = archivos_dir / Path(local_path).name

            print(f"[{i}/{len(objetivos)}] OCR de ({file_id}): {title}")

            if not full_path.is_file():
                documentos_ocr_fallido.append({
                    "file_id": file_id, "title": title,
                    "reason": "Archivo no encontrado en disco.",
                })
                continue

            text, detalle_paginas = ocr_pdf(full_path, tmp_dir)

            n_paginas_sin_texto = sum(1 for d in detalle_paginas if d["calidad"] == "sin_texto_detectado")
            confidences = [d["avg_confidence"] for d in detalle_paginas if d["avg_confidence"] is not None]
            avg_doc_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None

            if not text.strip():
                documentos_ocr_fallido.append({
                    "file_id": file_id, "title": title,
                    "reason": "OCR no reconoció ningún texto en ninguna página.",
                    "detalle_paginas": detalle_paginas,
                })
                print(f"    [ADVERTENCIA] OCR vacío para '{title}'. No se genera chunk (flag, don't drop != forzar basura).")
                continue

            chunks, sin_estructura = chunk_ocr_text(text, source_name=title)
            total_chunks += len(chunks)

            doc_record = {
                "file_id": file_id,
                "title": title,
                "local_path": local_path,
                "url_final": doc.get("url_final"),
                "extension": ".pdf",
                "extraction_method": "ocr",
                "extraction_warnings": [
                    "Documento escaneado (0 texto nativo extraíble); texto obtenido vía OCR (PaddleOCR, ver docs/adr/0003-self-hosted-ocr.md)."
                ],
                "ocr_avg_confidence": avg_doc_confidence,
                "ocr_paginas_sin_texto": n_paginas_sin_texto,
                "ocr_detalle_paginas": detalle_paginas,
                "sin_estructura_articulo": sin_estructura,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
            _write_json(OUTPUT_DIR / f"{file_id}.json", doc_record)

            resultados.append({
                "file_id": file_id,
                "title": title,
                "chunk_count": len(chunks),
                "sin_estructura_articulo": sin_estructura,
                "ocr_avg_confidence": avg_doc_confidence,
                "ocr_paginas_sin_texto": n_paginas_sin_texto,
                "texto_muestra": chunks[0]["texto"][:300],
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "nota": (
            "Reporte de la etapa de OCR (chatbot/ocr_extraction.py), separado del "
            "reporte de la etapa nativa (chatbot/data/normativa_extraction_report.json, "
            "que este módulo nunca modifica). Cubre exactamente los 7 PDF que la etapa "
            "nativa marcó como 'sin texto extraíble' (escaneos de imagen puros). "
            "Herramienta: PaddleOCR (ver docstring del módulo para por qué no fue "
            "posible usar Tesseract, la opción por defecto de docs/adr/0003-self-hosted-ocr.md, "
            "en este entorno)."
        ),
        "herramienta_ocr": "PaddleOCR (lang=es)",
        "motivo_no_tesseract": (
            "Tesseract (opción por defecto del ADR 0003) no tiene binario instalado en "
            "esta máquina y su instalador NSIS exige elevación UAC interactiva incluso "
            "instalando en una carpeta de usuario; no hay usuario interactivo en este "
            "entorno para aceptar el UAC. Se escaló a PaddleOCR, ya contemplado como "
            "alternativa self-hosted en el propio ADR 0003."
        ),
        "documentos_objetivo": len(objetivos),
        "documentos_procesados_exitosamente": len(resultados),
        "documentos_ocr_fallido": documentos_ocr_fallido,
        "total_chunks_producidos": total_chunks,
        "resultados": resultados,
        "output_dir": str(OUTPUT_DIR),
    }
    _write_json(OCR_REPORT_PATH, report)

    print(f"[INFO] Documentos OCR procesados con éxito: {len(resultados)}/{len(objetivos)}")
    print(f"[INFO] Documentos con OCR fallido (0 texto): {len(documentos_ocr_fallido)}")
    print(f"[INFO] Total de chunks producidos: {total_chunks}")
    print(f"[INFO] Reporte escrito en '{OCR_REPORT_PATH}'.")

    return report


if __name__ == "__main__":
    run_ocr_extraction()
