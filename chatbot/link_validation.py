"""
Módulo de validación de enlaces DENTRO del cuerpo de las páginas de Tutorial
que sobreviven el pipeline de limpieza de chatbot/tutorial_ingestion.py.

Esto es DISTINTO de la validación de página completa que ya hace
capture_summary.json (http_status/capture_status de la página en sí): aquí
no se valida si la página cargó, sino si los ENLACES QUE ESA PÁGINA
CONTIENE en su cuerpo (a pasarelas de pago, otros trámites relacionados,
recursos externos, PDFs, etc.) siguen resolviendo. Una página puede estar
perfectamente "captured" (HTTP 200) y aun así citar en su texto un enlace
roto o desactualizado.

Seguimos el mismo principio del ADR 0004 ("flag, don't drop"): un enlace
roto o con año desactualizado se REPORTA, no se elimina del contenido del
Tutorial — el resto del procedimiento sigue siendo útil aunque un enlace
puntual ya no resuelva.

Este módulo:
  1. reutiliza chatbot.tutorial_ingestion.run_pipeline() para obtener los
     chunks de páginas sobrevivientes (NO vuelve a derivar qué páginas
     sobreviven al filtro: eso ya lo decide filter_pages()/parse_tutorial());
  2. extrae toda URL referenciada en el campo "text" (cuerpo Markdown) de
     cada chunk: enlaces Markdown [texto](url) e imágenes ![alt](url), más
     URLs sueltas en texto plano;
  3. deduplica esas URLs (una URL vista en varias páginas se revisa UNA
     sola vez) y les hace una petición HTTP real (HEAD con fallback a GET,
     con reintentos acotados y una pausa entre peticiones distintas para
     ser respetuosos con el sitio real y con sitios externos enlazados);
  4. escribe un reporte JSON con el resultado de cada URL (valid/broken/
     timeout/redirect), qué página(s) la referencian, el texto del enlace
     si está disponible, y marca aparte cualquier URL cuyo path/query
     contenga un año claramente desactualizado (aunque la URL todavía
     resuelva: una página viva puede seguir citando la tarifa o el portal
     de pago del año pasado).

NO modifica chatbot/tutorial_ingestion.py, chatbot/ingestion.py, el scraper,
ni ningún código de GCP/vector store: es un pase de validación nuevo y
separado sobre el mismo corpus.
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

# Algunas URLs/títulos reales del corpus traen caracteres Unicode que la
# consola de Windows (cp1252) no puede codificar (incluso alguna marca
# diacrítica combinante suelta, verificada en el dato real), lo que
# tumbaría un proceso largo a mitad de camino solo por un print(). Se
# reconfigura stdout/stderr a UTF-8 con reemplazo de caracteres no
# soportados para que una corrida de horas contra el sitio real no se
# pierda por un error de consola.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # stdout/stderr no soporta reconfigure (p.ej. ya redirigido); no es crítico

# Soporta tanto "python chatbot/link_validation.py" (script suelto, sin
# paquete) como "python -m chatbot.link_validation" (import de paquete)
# desde la raíz del repo, igual que tutorial_ingestion.py permite ambos
# estilos de invocación.
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

# Tope de tiempo total de la corrida (ver incidente real: una corrida previa
# sin este tope quedó corriendo sin escribir el reporte hasta que el proceso
# fue terminado externamente, perdiendo todo el progreso). Si se excede, la
# corrida se corta limpio, escribe lo que alcanzó a revisar como reporte
# PARCIAL, y termina — nunca queda colgada indefinidamente.
MAX_RUNTIME_SECONDS = 3 * 60 * 60  # 3 horas (estimado real: ~189 enlaces http://
# a www.controlsanitario.gob.ec necesitan el respaldo a https descrito en
# check_url, a ~11-12s cada uno, más ~1800 enlaces https a ~1-2s cada uno:
# la corrida completa debería tomar entre 1.5 y 2.5 horas; se deja margen).

# Cada cuántas URLs revisadas se vuelve a escribir el reporte a disco como
# checkpoint (ver mismo incidente: el reporte solo se escribía al final, así
# que un crash a la URL 121/2016 no dejó ningún artefacto en disco). 1 =
# checkpoint tras cada URL; es barato porque escribir el JSON acumulado es
# mucho más rápido que la pausa de red entre peticiones.
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
    de cierre pegada por accidente, descarta pseudo-URLs (mailto:, tel:,
    anclas locales "#..."), resuelve enlaces relativos del propio sitio
    contra BASE_SITE_URL, y quita el fragmento "#..." (no cambia qué
    recurso del servidor se está pidiendo).

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

    # Saneamiento contra basura de scraping: se encontraron casos reales en
    # el corpus donde un enlace Markdown mal formado en el HTML original
    # (p.ej. "[texto](http://Informe resumen ...)", sin URL real dentro del
    # paréntesis) hace que el regex de URL suelta capture solo la primera
    # palabra antes del espacio ("http://Informe"). Un hostname real
    # siempre tiene un punto (dominio.tld); si no lo tiene, no es una URL
    # verificable y se descarta aquí en vez de reportarla como "enlace
    # roto" (sería un falso positivo: nunca fue un enlace real).
    if "." not in urlsplit(url).netloc:
        return None

    return url


def extract_links_from_text(markdown_body: str) -> list[dict]:
    """
    Extrae toda URL referenciada en el cuerpo Markdown de una página.

    Devuelve una lista de diccionarios {"url": ..., "link_text": ...} en
    orden de aparición, SIN deduplicar (la deduplicación global entre
    páginas se hace en build_link_index()).
    """
    found: list[dict] = []
    covered_spans: list[tuple[int, int]] = []

    for match in _MARKDOWN_LINK_PATTERN.finditer(markdown_body):
        link_text, raw_url = match.group(1), match.group(2)
        covered_spans.append(match.span())
        cleaned = _clean_url(raw_url)
        if cleaned:
            found.append({"url": cleaned, "link_text": link_text.strip() or None})

    # Para las URLs sueltas, evitamos volver a capturar lo que ya vino de un
    # enlace Markdown (ya cubierto arriba) borrando esos tramos del texto
    # antes de aplicar el segundo regex.
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
    Agrega, para cada URL única encontrada en el corpus, qué página(s) del
    Tutorial la referencian y con qué texto de enlace (si lo hay).

    Si la misma URL aparece más de una vez en la MISMA página, esa página
    solo se lista una vez en "referenced_by" (pero la URL igual se revisa
    una sola vez a nivel global, que es lo que importa para ser
    respetuosos con el sitio).
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
    año de 4 dígitos anterior al año actual (p.ej. ".../2023/" o
    "?anio=2024"). None si no aplica.

    Esto es independiente de si la URL todavía resuelve: una página viva
    puede seguir citando la tarifa o el portal de pago del año pasado, y
    eso también merece una advertencia (ver ADR 0004: flag, don't drop).
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
    Intenta primero HEAD (más liviano, no descarga el cuerpo). Si el
    servidor no lo soporta bien (403/404/405/5xx, o de plano rechaza la
    conexión — algunos sitios cierran la conexión ante HEAD aunque el
    recurso exista) reintenta con GET, que casi cualquier servidor soporta.

    Si HEAD directamente se agota por timeout, NO se reintenta con GET en
    el mismo intento (para no duplicar el tiempo de espera por URL): se
    deja que el bucle de reintentos de check_url() decida si vale la pena
    reintentar desde cero.
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
        # Hubo al menos una redirección: se reporta como "redirect" en vez
        # de "valid" aunque el destino final sí resuelva, porque un enlace
        # que redirige suele ser señal de una URL vieja movida de lugar
        # (p.ej. el portal de pago de un año anterior).
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

    Incluye un respaldo de esquema (http -> https): se confirmó contra el
    sitio real que el vhost principal de controlsanitario.gob.ec NO
    responde en el puerto 80 (cuelga hasta agotar el timeout en el 100% de
    los casos probados, incluida la raíz "/"), mientras que https sí
    funciona con normalidad. Muchos enlaces del cuerpo del Tutorial usan
    "http://" porque son de antes de la migración del sitio a HTTPS. Sin
    este respaldo, cada uno de esos enlaces gastaba TODO el presupuesto de
    reintentos (hasta ~36s) en un esquema que nunca iba a responder, y
    encima se reportaba como "broken"/"timeout" aunque el recurso sí
    existiera vía https — un falso positivo que además hacía la corrida
    completa (2016 URLs) impracticablemente lenta.

    El respaldo se intenta UNA sola vez ante la primera falla de un enlace
    "http://" (no cuenta como uno de los reintentos), y si también falla,
    el resto del presupuesto de reintentos se gasta sobre la variante
    https (más probable de ser la correcta) en vez de seguir insistiendo
    con el esquema que ya falló.

    Returns:
        Diccionario con al menos la clave "status" en
        {"valid", "broken", "timeout", "redirect"}, más detalle según el
        caso (http_status, redirect_target, detail del error, checked_url
        si se terminó verificando una URL distinta a la original, etc.).
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
    Escribe el reporte de forma atómica: primero a un archivo temporal en el
    mismo directorio, luego un os.replace() (rename atómico en Windows y
    POSIX). Así, si el proceso se corta a mitad de una escritura (crash,
    kill externo, corte de luz), el reporte en disco queda o bien la
    versión anterior completa, o bien la nueva completa — nunca un JSON a
    medio escribir. Se llama tanto para checkpoints intermedios como para
    el reporte final.

    El nombre del archivo temporal incluye el PID: se detectó en la práctica
    que si dos procesos llegan a correr contra el mismo REPORT_PATH al mismo
    tiempo (p.ej. una corrida de verificación que no había terminado de
    cerrarse cuando arrancó la corrida completa), ambos competían por el
    MISMO archivo ".tmp" y uno de los dos podía toparse con un
    PermissionError de Windows al abrirlo. Solo debería correr un proceso a
    la vez contra un REPORT_PATH dado, pero incluir el PID hace que un
    solape accidental sea inofensivo en vez de un crash.

    El os.replace() final también se reintenta unas pocas veces: se
    confirmó en la práctica (WinError 5 "Acceso denegado" real, con el PID
    ya en el nombre del .tmp, así que no era el choque de arriba) que en
    Windows, si OTRO proceso tiene el archivo destino abierto para lectura
    en el instante exacto del rename — p.ej. un chequeo de progreso externo
    que hace open()/json.load() sobre el mismo REPORT_PATH mientras esta
    corrida hace un checkpoint tras CADA URL — el rename puede fallar de
    forma transitoria (a diferencia de POSIX, donde un lector no bloquea un
    rename). La condición se resuelve sola en milisegundos apenas el lector
    cierra el archivo, así que un par de reintentos cortos la absorben en
    vez de tumbar una corrida de horas por un simple `cat` del reporte.
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
    Si ya existe un reporte (completo o parcial, p.ej. de una corrida
    anterior que se cortó) para este mismo conjunto de URLs, recupera las
    URLs que ya se revisaron para no volver a pegarle a esos servidores de
    nuevo ni perder ese trabajo. Solo se reutilizan entradas cuya URL siga
    estando en el conjunto actual de URLs únicas (si el corpus cambió,
    entradas viejas de URLs que ya no aplican se ignoran).

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
    (por defecto, los chunks reales que produce
    chatbot.tutorial_ingestion.run_pipeline()).

    Escribe un checkpoint del reporte a disco tras cada URL revisada (ver
    CHECKPOINT_EVERY) y respeta un tope global de tiempo (ver
    MAX_RUNTIME_SECONDS): si se excede, corta la corrida limpio y marca el
    reporte como parcial en vez de quedarse corriendo indefinidamente. Si
    `resume=True` (default) y ya existe un reporte previo para este mismo
    conjunto de URLs, retoma desde ahí en vez de revisar todo de nuevo.

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
# Lo de arriba (validate_links()/run_validation()) es de sólo lectura: audita
# qué enlaces citados en el cuerpo del Tutorial ya no resuelven, pero no toca
# el corpus (ver ADR 0004: flag, don't drop — aplica al AÑO desactualizado).
# Un enlace confirmado "broken"/"timeout" es distinto: no aporta nada al
# usuario y sólo puede llevarlo a una página muerta, así que ACÁ SÍ se
# elimina del texto servido, conservando el texto descriptivo que lo
# acompañaba. Los "valid"/"redirect" no se tocan: siguen resolviendo y
# siguen siendo información útil.
#
# Reutilizado por chatbot/vector_ingest.py (build_tutorial_documents()) para
# que cada corrida completa del pipeline limpie automáticamente el corpus de
# Tutorial contra el reporte de validación más reciente en disco, y por
# chatbot/.tools/fix_tutorial_broken_links.py (fix puntual ya aplicado sobre
# el chatbot/data/vector_docstore.json existente, sin tener que
# re-embeber/re-subir nada a Pinecone).


def normalize_url_for_comparison(url: str) -> str:
    """
    Normaliza una URL para compararla contra el reporte de validación,
    ignorando diferencias que no cambian el recurso real: una barra final
    "/" de más o de menos en el path, y mayúsculas/minúsculas en
    esquema/host. Mismo criterio que ya usa scrape_servicios.canonical_url()
    (quita fragmento y barra final redundante) para deduplicar URLs en el
    resto del pipeline, para no reinventar la normalización acá.
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
    el conjunto de URLs "broken"/"timeout" del reporte, ver
    load_broken_urls()). La comparación es normalizada
    (normalize_url_for_comparison()), no exige coincidencia exacta de
    string.

    - Enlace o imagen Markdown roto ("[texto](url)" / "![alt](url)"): se
      reemplaza por sólo el texto/alt descriptivo, sin el link muerto (no
      se pierde la información, sólo deja de ser un hipervínculo muerto).
      Si el texto/alt queda vacío tras recortar espacios, el enlace se
      elimina por completo.
    - URL suelta rota en texto plano (sin sintaxis Markdown): se elimina la
      URL, conservando cualquier puntuación de cierre de oración que
      hubiera quedado pegada a ella (ver _TRAILING_PUNCTUATION) y el resto
      del texto intacto.

    Enlaces "valid"/"redirect" (cualquier URL que NO esté en `broken_urls`)
    no se tocan.

    Returns:
        (texto_limpio, cantidad_de_enlaces_rotos_eliminados). Si no se
        eliminó ningún enlace, se devuelve el texto original sin cambios
        (no se aplica el recorte de espacios cuando no hubo nada que
        limpiar, para no introducir diffs irrelevantes).
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
            # Se conserva la puntuación de cierre de oración pegada al
            # final de la URL (p.ej. el "." de "...ver el sitio: URL.");
            # _clean_url() la ignora para validar, pero acá SÍ importa
            # devolverla: es puntuación de la frase, no parte del enlace.
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
    Carga, del reporte de validación de enlaces más reciente en disco
    (chatbot/scraping/link_validation_report.json por defecto), el conjunto
    de URLs marcadas "broken" o "timeout" (las que ameritan limpiarse del
    corpus servido; "valid"/"redirect" quedan afuera porque siguen
    resolviendo y son información útil).

    Si el reporte todavía no existe (p.ej. checkout limpio antes de correr
    `python -m chatbot.link_validation` una primera vez) o no se puede leer,
    NO rompe el pipeline: devuelve un set vacío y logea una advertencia
    clara, dejando el corpus sin limpiar en esa corrida en particular.
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
