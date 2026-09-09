"""
Valida los enlaces citados DENTRO del cuerpo de las páginas de Tutorial que
sobreviven el pipeline de chatbot/tutorial_ingestion.py.

Distinto de capture_summary.json (que valida si la página en sí cargó): acá
se valida si los enlaces que esa página CITA en su texto (pasarelas de pago,
trámites relacionados, PDFs, etc.) siguen resolviendo. Sigue el principio de
ADR 0004 ("flag, don't drop"): un enlace roto o con año desactualizado se
reporta, no se borra del contenido.

Pasos: reutiliza run_pipeline() para los chunks sobrevivientes, extrae toda
URL de su cuerpo Markdown, deduplica y verifica cada una por HTTP (HEAD con
fallback a GET), y escribe un reporte JSON con el estado de cada URL, qué
página(s) la referencian, y si su path/query contiene un año desactualizado.

No modifica tutorial_ingestion.py, ingestion.py, el scraper ni el vector
store: es un pase de validación separado sobre el mismo corpus.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

# Algunas URLs/títulos del corpus traen Unicode que la consola de Windows
# (cp1252) no puede codificar, lo que cortaría una corrida larga por un
# simple print(). Se reconfigura stdout/stderr a UTF-8 con reemplazo.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # stdout/stderr no soporta reconfigure (p.ej. ya redirigido); no es crítico

# Soporta tanto "python chatbot/link_validation.py" como
# "python -m chatbot.link_validation", igual que tutorial_ingestion.py.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tutorial_ingestion import run_pipeline
else:
    from chatbot.tutorial_ingestion import run_pipeline


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

REPORT_PATH = Path(__file__).resolve().parent / "scraping" / "link_validation_report.json"

# Dominio base para resolver enlaces relativos (p.ej. "/certificados/") que
# aparecen en el cuerpo del Tutorial: son enlaces internos del mismo sitio.
BASE_SITE_URL = "https://www.controlsanitario.gob.ec/"

REQUEST_TIMEOUT_SECONDS = 10
REQUEST_DELAY_SECONDS = 0.8  # pausa entre peticiones a URLs distintas
FALLBACK_DELAY_SECONDS = 0.3  # pausa extra entre el intento HEAD y el GET de respaldo
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2.0

# Tope de tiempo total de la corrida: si se excede, corta limpio, escribe lo
# revisado hasta ahí como reporte PARCIAL, y termina en vez de quedar colgada.
MAX_RUNTIME_SECONDS = 3 * 60 * 60  # 3 horas, con margen sobre el corpus real

# Cada cuántas URLs revisadas se reescribe el reporte a disco como checkpoint,
# para no perder el progreso si la corrida se corta a mitad de camino.
CHECKPOINT_EVERY = 1

# User-Agent descriptivo: identifica el bot, su propósito (auditoría interna
# de enlaces, no scraping masivo) y un contacto, como corresponde al pegarle
# a un sitio de gobierno real y a posibles sitios externos enlazados.
USER_AGENT = (
    "ARCSA-RagChatbot-LinkValidator/1.0 "
    "(auditoria interna de enlaces citados en el corpus Tutorial; "
    "contacto: jarrink50@gmail.com)"
)

# Años considerados "desactualizados": cualquier año de 4 dígitos anterior
# al año actual. Se calcula en vez de hardcodear 2023/2024/2025 para que el
# script siga siendo correcto sin tocar el código el año que viene.
_CURRENT_YEAR = datetime.now().year
_STALE_YEARS = {str(y) for y in range(2015, _CURRENT_YEAR)}


# --------------------------------------------------------------------------
# Etapa 1: extracción de URLs del cuerpo Markdown de una página
# --------------------------------------------------------------------------

# Enlace o imagen Markdown: ![alt](url) o [texto](url), tolera un título
# opcional entre comillas después de la URL: [texto](url "título").
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\(\s*(\S+?)(?:\s+\"[^\"]*\")?\s*\)")

# URL suelta en texto plano (no envuelta en sintaxis Markdown), para casos
# como "más información en https://... " o "visite www.sri.gob.ec".
_BARE_URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"'\)\]]+")

# Esquemas/pseudo-URLs que no son enlaces web reales y se descartan.
_IGNORED_SCHEMES = ("mailto:", "tel:", "javascript:", "data:")

# Puntuación de cierre de oración que a veces queda pegada al final de una
# URL suelta capturada por el regex de arriba (p.ej. "...ver el sitio.").
_TRAILING_PUNCTUATION = ".,;:!?)]}’”\"'"


def _clean_url(raw_url: str) -> str | None:
    """
    Normaliza una URL cruda extraída del cuerpo Markdown: quita puntuación
    de cierre pegada, descarta pseudo-URLs (mailto:, tel:, anclas "#..."),
    resuelve enlaces relativos contra BASE_SITE_URL y quita el fragmento.

    Returns:
        La URL limpia, o None si no es un enlace web válido para revisar.
    """
    url = raw_url.strip().strip(_TRAILING_PUNCTUATION)
    if not url or url.startswith("#"):
        return None
    if any(url.lower().startswith(scheme) for scheme in _IGNORED_SCHEMES):
        return None

    if url.startswith("www."):
        url = "https://" + url
    elif url.startswith("/"):
        url = urljoin(BASE_SITE_URL, url)

    if not url.lower().startswith(("http://", "https://")):
        return None

    url = url.split("#", 1)[0].strip()
    if not url:
        return None

    # Un hostname real siempre tiene un punto (dominio.tld). Sin uno, no es
    # una URL verificable (p.ej. un enlace Markdown mal formado en el HTML
    # original) y se descarta acá en vez de reportarse como "roto".
    if "." not in urlsplit(url).netloc:
        return None

    return url


def extract_links_from_text(markdown_body: str) -> list[dict]:
    """
    Extrae toda URL referenciada en el cuerpo Markdown de una página.

    Devuelve una lista de {"url": ..., "link_text": ...} en orden de
    aparición, sin deduplicar (eso lo hace build_link_index()).
    """
    found: list[dict] = []
    covered_spans: list[tuple[int, int]] = []

    for match in _MARKDOWN_LINK_PATTERN.finditer(markdown_body):
        link_text, raw_url = match.group(1), match.group(2)
        covered_spans.append(match.span())
        cleaned = _clean_url(raw_url)
        if cleaned:
            found.append({"url": cleaned, "link_text": link_text.strip() or None})

    # Evita recapturar como URL suelta lo que ya vino de un enlace Markdown,
    # borrando esos tramos del texto antes de aplicar el segundo regex.
    remainder = list(markdown_body)
    for start, end in covered_spans:
        for i in range(start, end):
            remainder[i] = " "
    remainder_text = "".join(remainder)

    for match in _BARE_URL_PATTERN.finditer(remainder_text):
        cleaned = _clean_url(match.group(0))
        if cleaned:
            found.append({"url": cleaned, "link_text": None})

    return found


def build_link_index(chunks: list[dict]) -> dict[str, dict]:
    """
    Agrega, para cada URL única del corpus, qué página(s) la referencian y
    con qué texto de enlace. Una URL repetida en la misma página se lista
    una sola vez en "referenced_by" (y se revisa una sola vez a nivel global).
    """
    index: dict[str, dict] = {}
    for chunk in chunks:
        body = chunk.get("text") or ""
        links = extract_links_from_text(body)
        seen_on_this_page: set[str] = set()
        for link in links:
            url = link["url"]
            if url in seen_on_this_page:
                continue
            seen_on_this_page.add(url)
            entry = index.setdefault(url, {"referenced_by": []})
            entry["referenced_by"].append(
                {
                    "page_id": chunk.get("id"),
                    "page_title": chunk.get("title"),
                    "page_source_url": chunk.get("source_url"),
                    "link_text": link["link_text"],
                }
            )
    return index


def _flagged_for_stale_year(url: str) -> str | None:
    """
    Devuelve el año detectado si la URL contiene, en su path o query, un
    año de 4 dígitos anterior al actual (p.ej. ".../2023/"). None si no
    aplica. Independiente de si la URL resuelve: una página viva puede
    seguir citando la tarifa del año pasado (ADR 0004: flag, don't drop).
    """
    parsed = urlsplit(url)
    path_and_query = f"{parsed.path}?{parsed.query}"
    for year in sorted(_STALE_YEARS, reverse=True):
        if year in path_and_query:
            return year
    return None


# --------------------------------------------------------------------------
# Etapa 2: verificación HTTP real de cada URL única
# --------------------------------------------------------------------------

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _request_with_fallback(session: requests.Session, url: str) -> requests.Response:
    """
    Intenta primero HEAD (más liviano). Si el servidor no lo soporta bien
    (403/404/405/5xx, o rechaza la conexión) reintenta con GET.

    Si HEAD se agota por timeout, no se reintenta con GET en el mismo
    intento (evita duplicar la espera); el bucle de check_url() decide si
    vale la pena reintentar desde cero.
    """
    response: requests.Response | None = None
    try:
        response = session.head(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.exceptions.Timeout:
        raise
    except requests.exceptions.RequestException:
        response = None  # HEAD no soportado / conexión rechazada: probamos GET

    if response is not None and response.status_code not in (403, 404, 405, 501) and response.status_code < 500:
        return response

    time.sleep(FALLBACK_DELAY_SECONDS)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True, stream=True)
    response.close()
    return response


def _classify_response(response: requests.Response) -> dict:
    result: dict = {"http_status": response.status_code}
    if response.history:
        # Se reporta "redirect" en vez de "valid" aunque el destino final
        # resuelva: suele ser señal de una URL vieja movida de lugar.
        result["status"] = "redirect"
        result["redirect_target"] = response.url
        result["redirect_final_status"] = response.status_code
        if not (200 <= response.status_code < 400):
            result["note"] = "el destino final del redirect tampoco resuelve correctamente"
    elif 200 <= response.status_code < 400:
        result["status"] = "valid"
    else:
        result["status"] = "broken"
    return result


def check_url(session: requests.Session, url: str) -> dict:
    """
    Verifica una URL con reintentos acotados y clasifica el resultado.

    Incluye un respaldo de esquema (http -> https): el vhost principal de
    controlsanitario.gob.ec no responde en el puerto 80, y buena parte de
    los enlaces del Tutorial usan "http://" por ser previos a la migración
    del sitio a HTTPS. Sin este respaldo, esos enlaces agotaban todo el
    presupuesto de reintentos sobre un esquema que nunca iba a responder y
    se reportaban como "broken" pese a existir vía https.

    El respaldo se intenta una sola vez (no consume un reintento); si
    también falla, el resto del presupuesto se gasta sobre la variante
    https en vez de insistir con el esquema que ya falló.

    Returns:
        Diccionario con al menos "status" en
        {"valid", "broken", "timeout", "redirect"}, más detalle según el
        caso (http_status, redirect_target, detail, checked_url si se
        verificó una URL distinta a la original, etc.).
    """
    original_url = url
    candidate_url = url
    tried_scheme_fallback = False
    last_exception: Exception | None = None
    timed_out = False

    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            response = _request_with_fallback(session, candidate_url)
            result = _classify_response(response)
            if candidate_url != original_url:
                result["checked_url"] = candidate_url
                result["note"] = (
                    f"{result.get('note', '')} "
                    f"la URL original ({original_url}) no respondió en su esquema "
                    f"original; se verificó {candidate_url} en su lugar."
                ).strip()
            return result
        except requests.exceptions.Timeout as exc:
            timed_out, last_exception = True, exc
        except requests.exceptions.RequestException as exc:
            timed_out, last_exception = False, exc

        if not tried_scheme_fallback and candidate_url.lower().startswith("http://"):
            tried_scheme_fallback = True
            candidate_url = "https://" + candidate_url[len("http://"):]
            continue  # no consume presupuesto de reintentos: es un esquema distinto

        attempt += 1
        if attempt <= MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    detail = {
        "detail": str(last_exception) if timed_out else f"{type(last_exception).__name__}: {last_exception}",
    }
    if candidate_url != original_url:
        detail["checked_url"] = candidate_url
        detail["note"] = (
            f"ni la URL original ({original_url}) ni su variante https "
            f"({candidate_url}) respondieron."
        )
    detail["status"] = "timeout" if timed_out else "broken"
    return detail


# --------------------------------------------------------------------------
# Etapa 3: orquestación sobre el corpus real y escritura del reporte
# --------------------------------------------------------------------------

def _build_summary(
    results: dict[str, dict],
    total_unique_urls: int,
    elapsed_seconds: float,
    partial: bool,
    partial_reason: str | None = None,
) -> dict:
    status_counts: dict[str, int] = {}
    stale_year_count = 0
    for entry in results.values():
        status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1
        if "posiblemente_desactualizado_por_anio" in entry:
            stale_year_count += 1

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_unique_links_found": total_unique_urls,
        "total_unique_links_checked": len(results),
        "by_status": status_counts,
        "flagged_stale_year_count": stale_year_count,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "partial": partial,
    }
    if partial:
        summary["partial_reason"] = partial_reason
        summary["remaining_unchecked"] = total_unique_urls - len(results)
    return summary


def write_report(report: dict, output_path: Path = REPORT_PATH) -> None:
    """
    Escribe el reporte de forma atómica: primero a un archivo temporal en
    el mismo directorio, luego os.replace() (rename atómico). Así, si el
    proceso se corta a mitad de una escritura, el reporte en disco queda o
    la versión anterior completa, o la nueva completa, nunca un JSON a
    medio escribir. Se usa tanto para checkpoints como para el reporte final.

    El nombre del temporal incluye el PID, para que un solape accidental de
    dos procesos contra el mismo REPORT_PATH sea inofensivo en vez de un
    PermissionError. El replace() final se reintenta unas pocas veces
    porque en Windows puede fallar de forma transitoria si otro proceso
    tiene el archivo destino abierto para lectura en ese instante (a
    diferencia de POSIX); la condición se resuelve sola en milisegundos.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(f".{os.getpid()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    last_exception: OSError | None = None
    for attempt in range(5):
        try:
            os.replace(tmp_path, output_path)
            return
        except PermissionError as exc:
            last_exception = exc
            time.sleep(0.2 * (attempt + 1))
    raise last_exception


def _load_previous_results(output_path: Path, expected_urls: set[str]) -> dict[str, dict]:
    """
    Si ya existe un reporte previo (completo o parcial) para este mismo
    conjunto de URLs, recupera las entradas ya revisadas para no volver a
    pegarle a esos servidores ni perder ese trabajo. Ignora entradas de
    URLs que ya no estén en el conjunto actual (corpus cambiado).

    Devuelve un diccionario vacío si no hay reporte previo o no se puede
    leer (nunca falla la corrida por esto).
    """
    if not output_path.exists():
        return {}
    try:
        with output_path.open(encoding="utf-8") as f:
            previous = json.load(f)
        previous_results = previous.get("results", [])
    except (json.JSONDecodeError, OSError, AttributeError):
        print(f"[ADVERTENCIA] No se pudo leer el reporte previo en '{output_path}'; se empieza de cero.")
        return {}

    resumed = {
        entry["url"]: entry
        for entry in previous_results
        if isinstance(entry, dict) and entry.get("url") in expected_urls
    }
    return resumed


def validate_links(chunks: list[dict] | None = None, resume: bool = True) -> dict:
    """
    Ejecuta el pipeline completo de validación de enlaces sobre `chunks`
    (por defecto, los que produce chatbot.tutorial_ingestion.run_pipeline()).

    Escribe un checkpoint tras cada URL revisada y respeta el tope de
    tiempo MAX_RUNTIME_SECONDS, cortando limpio y marcando el reporte como
    parcial si se excede. Si `resume=True` (default) y ya existe un reporte
    previo para este mismo conjunto de URLs, retoma desde ahí.

    Returns:
        Diccionario {"summary": {...}, "results": [...]} listo para
        escribirse como el reporte JSON.
    """
    if chunks is None:
        chunks = run_pipeline()

    print(f"[INFO] Extrayendo enlaces del cuerpo de {len(chunks)} páginas sobrevivientes...")
    link_index = build_link_index(chunks)
    unique_urls = sorted(link_index.keys())
    total_references = sum(len(v["referenced_by"]) for v in link_index.values())
    print(
        f"[INFO] {len(unique_urls)} URLs únicas encontradas "
        f"({total_references} referencias totales antes de deduplicar por página)."
    )

    results: dict[str, dict] = {}
    if resume:
        results = _load_previous_results(REPORT_PATH, set(unique_urls))
        if results:
            print(f"[INFO] Reanudando: {len(results)} URLs ya revisadas en una corrida previa, se reutilizan.")

    pending_urls = [u for u in unique_urls if u not in results]

    session = _make_session()
    started_at = time.monotonic()
    partial = False
    partial_reason = None

    for i, url in enumerate(pending_urls, start=1):
        elapsed_so_far = time.monotonic() - started_at
        if elapsed_so_far > MAX_RUNTIME_SECONDS:
            partial = True
            partial_reason = (
                f"se alcanzó el tope de tiempo de la corrida "
                f"({MAX_RUNTIME_SECONDS}s) con {len(results)}/{len(unique_urls)} URLs revisadas; "
                "se cortó limpio en vez de seguir corriendo indefinidamente."
            )
            print(f"[ADVERTENCIA] {partial_reason}")
            break

        check = check_url(session, url)
        stale_year = _flagged_for_stale_year(url)

        entry: dict = {
            "url": url,
            "status": check["status"],
            "referenced_by": link_index[url]["referenced_by"],
        }
        entry.update({k: v for k, v in check.items() if k != "status"})
        if stale_year:
            entry["posiblemente_desactualizado_por_anio"] = stale_year

        results[url] = entry
        print(f"[{len(results)}/{len(unique_urls)}] {check['status']:8s} {url}")

        if i % CHECKPOINT_EVERY == 0:
            checkpoint_elapsed = time.monotonic() - started_at
            checkpoint_summary = _build_summary(
                results, len(unique_urls), checkpoint_elapsed, partial=True,
                partial_reason="corrida en curso (checkpoint intermedio, todavía no terminó).",
            )
            write_report({"summary": checkpoint_summary, "results": list(results.values())})

        if i < len(pending_urls):
            time.sleep(REQUEST_DELAY_SECONDS)

    elapsed_seconds = time.monotonic() - started_at
    summary = _build_summary(results, len(unique_urls), elapsed_seconds, partial, partial_reason)

    return {"summary": summary, "results": list(results.values())}


# --------------------------------------------------------------------------
# Etapa 4: limpieza de enlaces ya confirmados rotos, sobre el texto servido
# --------------------------------------------------------------------------
#
# validate_links()/run_validation() son de sólo lectura (ADR 0004 aplica al
# año desactualizado: se reporta, no se borra). Un enlace "broken"/"timeout"
# es distinto: no aporta nada al usuario, así que acá sí se elimina del
# texto servido, conservando el texto descriptivo. "valid"/"redirect" no
# se tocan.
#
# Reutilizado por vector_ingest.py (build_tutorial_documents()) para limpiar
# el corpus contra el reporte más reciente en disco en cada corrida.


def normalize_url_for_comparison(url: str) -> str:
    """
    Normaliza una URL para compararla contra el reporte de validación,
    ignorando diferencias que no cambian el recurso real: barra final de
    más/menos en el path, mayúsculas/minúsculas en esquema/host. Mismo
    criterio que scrape_servicios.canonical_url() usa en el resto del
    pipeline.
    """
    if not url:
        return ""
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") if parsed.path not in ("", "/") else parsed.path
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


# Colapsa corridas de espacios/tabs horizontales que puede dejar sacar una
# URL suelta de en medio de una frase. No toca saltos de línea: la
# estructura de párrafos/tablas Markdown del cuerpo se conserva intacta.
_MULTI_SPACE_PATTERN = re.compile(r"[ \t]{2,}")
# Espacio colgante justo antes de puntuación de cierre de oración, típico
# de sacar una URL pegada a un "." o ":" (p.ej. "ver aquí : ." -> "ver aquí.").
_SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(r"[ \t]+([.,;:!?])")
# Espacio colgante al final de una línea.
_TRAILING_LINE_SPACE_PATTERN = re.compile(r"[ \t]+(\n|$)")


def strip_broken_links_from_text(text: str, broken_urls: set[str]) -> tuple[str, int]:
    """
    Elimina de `text` todo enlace cuya URL esté en `broken_urls` (se espera
    el set de URLs "broken"/"timeout" de load_broken_urls()); la
    comparación usa normalize_url_for_comparison(), no string exacto.

    - Enlace/imagen Markdown roto: se reemplaza por sólo el texto/alt
      descriptivo (se conserva la información, se pierde el link muerto).
      Si queda vacío, el enlace se elimina por completo.
    - URL suelta rota en texto plano: se elimina, conservando la
      puntuación de cierre de oración que hubiera quedado pegada.

    Enlaces "valid"/"redirect" no se tocan.

    Returns:
        (texto_limpio, cantidad_eliminada). Si no se eliminó nada, se
        devuelve el texto original sin cambios.
    """
    if not text or not broken_urls:
        return text, 0

    normalized_broken = {normalize_url_for_comparison(u) for u in broken_urls if u}
    if not normalized_broken:
        return text, 0

    removed = 0

    def _is_broken(raw_url: str) -> bool:
        cleaned = _clean_url(raw_url)
        return bool(cleaned) and normalize_url_for_comparison(cleaned) in normalized_broken

    def _replace_markdown(match: re.Match) -> str:
        nonlocal removed
        link_text, raw_url = match.group(1), match.group(2)
        if _is_broken(raw_url):
            removed += 1
            return link_text.strip()
        return match.group(0)

    text = _MARKDOWN_LINK_PATTERN.sub(_replace_markdown, text)

    def _replace_bare(match: re.Match) -> str:
        nonlocal removed
        raw = match.group(0)
        if _is_broken(raw):
            removed += 1
            # Conserva la puntuación de cierre pegada al final de la URL
            # (es de la frase, no parte del enlace).
            core = raw.rstrip(_TRAILING_PUNCTUATION)
            return raw[len(core):]
        return raw

    text = _BARE_URL_PATTERN.sub(_replace_bare, text)

    if removed:
        text = _SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", text)
        text = _MULTI_SPACE_PATTERN.sub(" ", text)
        text = _TRAILING_LINE_SPACE_PATTERN.sub(r"\1", text)
        text = text.strip()

    return text, removed


def load_broken_urls(report_path: Path = REPORT_PATH) -> set[str]:
    """
    Carga del reporte de validación más reciente en disco el conjunto de
    URLs marcadas "broken"/"timeout" (las que ameritan limpiarse del
    corpus; "valid"/"redirect" quedan afuera).

    Si el reporte no existe o no se puede leer, no rompe el pipeline:
    devuelve un set vacío y logea una advertencia.
    """
    if not report_path.exists():
        print(
            f"[ADVERTENCIA] No se encontró el reporte de validación de enlaces en "
            f"'{report_path}'; esta corrida NO limpiará ningún enlace roto del "
            "corpus de Tutorial. Corré 'python -m chatbot.link_validation' al "
            "menos una vez para generarlo."
        )
        return set()

    try:
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        results = report.get("results", [])
    except (json.JSONDecodeError, OSError, AttributeError) as exc:
        print(
            f"[ADVERTENCIA] No se pudo leer el reporte de validación de enlaces en "
            f"'{report_path}' ({exc}); esta corrida NO limpiará ningún enlace roto "
            "del corpus de Tutorial."
        )
        return set()

    broken = {
        entry["url"]
        for entry in results
        if isinstance(entry, dict) and entry.get("status") in ("broken", "timeout") and entry.get("url")
    }
    print(
        f"[INFO] {len(broken)} URL(s) marcada(s) broken/timeout cargada(s) desde "
        f"'{report_path}' para limpieza del corpus de Tutorial."
    )
    return broken


def run_validation() -> dict:
    """Punto de entrada: valida los enlaces del corpus real y escribe el reporte."""
    report = validate_links()
    write_report(report)

    summary = report["summary"]
    print(f"[INFO] Enlaces únicos revisados: {summary['total_unique_links_checked']}/{summary['total_unique_links_found']}")
    for status, count in sorted(summary["by_status"].items()):
        print(f"       - {status}: {count}")
    print(f"[INFO] Marcados por año posiblemente desactualizado: {summary['flagged_stale_year_count']}")
    print(f"[INFO] Tiempo total: {summary['elapsed_seconds']}s")
    if summary["partial"]:
        print(f"[ADVERTENCIA] Reporte PARCIAL: {summary['partial_reason']}")
    return report


if __name__ == "__main__":
    run_validation()
