"""
Carga real de datos hacia Pinecone.

Paso final del pipeline de RAG: toma los chunks ya preparados de los dos
corpus (Normativa + Tutorial), genera embeddings con la Gemini API y los
sube al índice de Pinecone (`chatbot.vector_store.PINECONE_INDEX_NAME`) vía
`index.upsert()`.

Modo de uso (desde la raíz del repositorio, con las dependencias de
chatbot/requirements.txt instaladas):

    python -m chatbot.vector_ingest

Decisiones de diseño relevantes:

- Modelo de embeddings: `configure_embeddings()` de vector_store.py es la
  única fuente de verdad (gemini-embedding-001, output_dimensionality=768).
  Este script sólo ajusta `embed_batch_size` sobre esa instancia.

- Normalización: gemini-embedding-001 con output_dimensionality=768 no
  devuelve vectores unitarios, así que se normaliza cada embedding a norma 1
  con `normalize_embedding()` (misma función que usa main.py en consultas).

- Almacenamiento de texto: Pinecone sólo guarda id + embedding + metadata
  corta (límite ~40KB por vector), nunca el texto completo. Por eso este
  script mantiene un docstore local (chatbot/data/vector_docstore.json:
  id -> {text, metadata}) además de subir los embeddings.

- IDs deterministas + overwrite total: los IDs son estables
  ("normativa:<file_id>:<index_in_file>:<articulo_numero>" y
  "tutorial:<page_id>"), pero cada corrida reprocesa el corpus completo
  desde cero, y un reprocesamiento puede cambiar "index_in_file" y generar
  IDs "nuevos" para el mismo documento. Un upsert incremental sin borrar
  antes acumularía datapoints huérfanos indefinidamente, así que si el
  índice está vacío o tiene contenido de un corpus/chunking incompatible,
  se borra todo (`index.delete(delete_all=True)`) antes de subir de cero.

- Manejo de rate-limit: `_RateLimiter` acota requests Y tokens estimados por
  minuto (ver EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS). Un 429 de rate-limit
  reintenta el MISMO lote completo con backoff (nunca lo fragmenta, ver
  _embed_with_retry); un 429 de cuota diaria aborta la corrida entera. El
  fallback documento-por-documento sólo se usa para errores que no son 429
  (contenido puntual problemático de un documento).

- Resumibilidad: si se detecta progreso real de una corrida anterior
  interrumpida del mismo corpus (ver plan_resume()), no se borra nada — se
  sube y persiste el docstore de forma incremental (lote por lote) para que
  una interrupción nunca cueste la corrida completa.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.genai.errors import ClientError

from chatbot.ingestion import to_documents as normativa_to_documents
from chatbot.link_validation import REPORT_PATH as LINK_VALIDATION_REPORT_PATH
from chatbot.link_validation import load_broken_urls, strip_broken_links_from_text
from chatbot.normativa_extraction import MAX_SAFE_CHUNK_CHARS, split_text_into_windows
from chatbot.tutorial_ingestion import run_pipeline as run_tutorial_pipeline
from chatbot.tutorial_ingestion import to_documents as tutorial_to_documents
from chatbot.vector_store import EMBED_DIMENSIONS, configure_embeddings, get_vector_store, normalize_embedding

load_dotenv()

# --------------------------------------------------------------------------
# Rutas y constantes
# --------------------------------------------------------------------------

CHATBOT_DIR = Path(__file__).resolve().parent
NORMATIVA_DIR = CHATBOT_DIR / "data" / "normativa"
DOCSTORE_PATH = CHATBOT_DIR / "data" / "vector_docstore.json"

# Tamaño de lote para embed_content. Cada llamada a
# embed_model.get_text_embedding_batch(texts) con len(texts) <= este valor
# dispara exactamente una request HTTP. Calibrado empíricamente contra el
# TPM real de la cuenta (ver EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS): con el tope
# de tokens/minuto vigente, un lote de 25 consume sólo ~4-5% del presupuesto
# por minuto, y reduce la cantidad de requests (menos overhead, menos
# rescrituras del docstore) sin agrandar demasiado el "blast radius" de un
# lote que falle por contenido real (cae al fallback documento por
# documento).
EMBED_BATCH_SIZE = 25

# Limitador de tasa real: nunca se dispara una request si ya hubo
# EMBED_RATE_LIMIT_MAX_REQUESTS en los últimos EMBED_RATE_LIMIT_WINDOW_SECONDS
# segundos. Fijado con margen bajo el RPM real de la cuenta (Nivel 1: 3000).
# El límite de tokens/minuto de abajo es, en la práctica, el que impone el
# ritmo real; este cubre sobre todo el camino de fallback
# documento-por-documento, que puede disparar muchos más requests/minuto con
# documentos chicos.
EMBED_RATE_LIMIT_MAX_REQUESTS = 2500
EMBED_RATE_LIMIT_WINDOW_SECONDS = 60.0

# Límite de TOKENS/minuto, con margen bajo el TPM real de la cuenta (Nivel 1:
# 1 000 000). El límite de requests por sí solo no alcanza para mantenerse
# bajo este límite de tokens, así que _RateLimiter rastrea ambos en la misma
# ventana deslizante.
EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS = 850000
CHARS_PER_TOKEN_CONSERVATIVE = 3.0


def _estimate_tokens(text: str) -> int:
    """Estimación conservadora (sobreestimada a propósito) de tokens a
    partir de caracteres, ver EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS arriba para
    la calibración real usada."""
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN_CONSERVATIVE))

# Reintento de LOTE COMPLETO ante un 429 de rate-limit por minuto: cuántas
# veces se reintenta antes de darse por vencido, y el backoff a usar cuando
# Google no sugiere un retryDelay explícito en el propio error.
RATE_LIMIT_BATCH_MAX_RETRIES = 5
RATE_LIMIT_BACKOFF_INITIAL_SECONDS = 5.0
RATE_LIMIT_BACKOFF_MAX_SECONDS = 90.0

# Cada lote de EMBED_BATCH_SIZE documentos (bien por debajo del límite de
# payload de Pinecone) se sube apenas se genera su embedding
# (process_documents()), así que el lote de embedding ya es el lote de
# upsert; no hace falta un tamaño de lote de upsert separado.

# Metadata subida a Pinecone junto con cada vector (campos cortos para poder
# filtrar en el futuro; el texto completo no va acá, sólo al docstore local).
METADATA_TEXT_MAX_LEN = 128

# Pregunta de prueba en español, relevante al dominio (ARCSA/trámites).
TEST_QUERY = (
    "¿Qué requisitos debo cumplir para la Notificación Sanitaria Obligatoria "
    "de un dispositivo médico a través de la Ventanilla Única Ecuatoriana?"
)
TEST_QUERY_TOP_K = 5


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def _batched(items: list[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _write_docstore_atomic(path: Path, docstore: dict[str, dict]) -> None:
    """Escribe el docstore COMPLETO de forma atómica: vuelca a un archivo
    temporal en el mismo directorio, fuerza flush+fsync, y recién después lo
    reemplaza sobre el destino final con `os.replace()` (atómico cuando
    origen y destino están en el mismo volumen). Si el proceso se corta a
    mitad del `json.dump()`, sólo el `.tmp` queda a medio escribir."""
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(docstore, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def load_existing_docstore(path: Path) -> dict[str, dict]:
    """Carga el docstore existente en disco de forma tolerante a fallos: si
    no existe, está vacío o quedó corrupto, se trata como vacío en vez de
    tirar abajo toda la corrida. `plan_resume()` decide qué parte de este
    contenido es reutilizable."""
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError) as error:
        print(f"[ADVERTENCIA] No se pudo leer el docstore existente en '{path}' ({error}); se trata como vacío.")
        return {}


# --------------------------------------------------------------------------
# Paso 1-2: cargar los dos corpus y convertirlos a Document con id estable
# --------------------------------------------------------------------------


def load_normativa_chunks(data_dir: Path) -> list[dict]:
    """
    Aplana todos los chatbot/data/normativa/*.json en una sola lista de
    chunks (cada archivo trae varios chunks bajo la clave "chunks").

    Se le agregan las claves internas "_file_id" y "_index_in_file" a cada
    chunk para poder construir un id determinista más abajo; ingestion.
    to_documents() ignora las claves que no reconoce.

    "_index_in_file" hace falta porque "articulo_numero" no es único dentro
    de un mismo archivo (p. ej. un PDF que concatena dos resoluciones, cada
    una con su propio "Art. 1, Art. 2..."); usar sólo file_id+articulo_numero
    como id produciría colisiones silenciosas.
    """
    chunks: list[dict] = []
    files = sorted(data_dir.glob("*.json"))
    for path in files:
        with path.open(encoding="utf-8") as f:
            record = json.load(f)
        file_id = record.get("file_id") or path.stem
        for index_in_file, chunk in enumerate(record.get("chunks", [])):
            enriched = dict(chunk)
            enriched["_file_id"] = file_id
            enriched["_index_in_file"] = index_in_file
            chunks.append(enriched)

    print(f"[INFO] Normativa: {len(files)} archivos, {len(chunks)} chunks cargados desde '{data_dir}'.")
    return chunks


def build_normativa_documents() -> list:
    chunks = load_normativa_chunks(NORMATIVA_DIR)
    documents = normativa_to_documents(chunks)

    for chunk, document in zip(chunks, documents, strict=True):
        document.id_ = f"normativa:{chunk['_file_id']}:{chunk['_index_in_file']}:{chunk['articulo_numero']}"
        document.metadata["corpus"] = "normativa"
        document.metadata["file_id"] = chunk["_file_id"]

    return documents


def build_tutorial_documents() -> list:
    print("[INFO] Tutorial: regenerando chunks vía tutorial_ingestion.run_pipeline() (no se persisten en disco).")
    chunks = run_tutorial_pipeline()
    documents = tutorial_to_documents(chunks)

    # Limpieza de enlaces ya confirmados rotos antes de embeber: el LLM
    # reproduce el texto del chunk tal cual en el prompt, enlaces muertos
    # incluidos. Usa el reporte más reciente de link_validation.py; si no
    # existe, deja el corpus sin limpiar (ver load_broken_urls()).
    broken_urls = load_broken_urls()
    if broken_urls:
        cleaned_chunks = 0
        cleaned_links = 0
        for document in documents:
            new_text, removed = strip_broken_links_from_text(document.text, broken_urls)
            if removed:
                document.set_content(new_text)
                cleaned_chunks += 1
                cleaned_links += removed
        print(
            f"[INFO] Limpieza de enlaces rotos del corpus Tutorial: {cleaned_links} "
            f"enlace(s) roto(s) eliminado(s) en {cleaned_chunks}/{len(documents)} "
            f"chunk(s) (según '{LINK_VALIDATION_REPORT_PATH}')."
        )

    for chunk, document in zip(chunks, documents, strict=True):
        page_id = chunk.get("id") or document.id_
        document.id_ = f"tutorial:{page_id}"
        document.metadata["corpus"] = "tutorial"

    return documents


def enforce_max_safe_chunk_size(documents: list, corpus_label: str) -> list:
    """
    Red de seguridad de tamaño genérica aplicada a cualquier Document antes
    de llegar a process_documents(), sin importar el corpus de origen.

    Normativa ya viene troceada de forma segura desde el origen, pero
    Tutorial trocea por página HTML, no por tamaño, así que una página larga
    sin cortes internos puede quedar como un chunk único demasiado grande.
    Un texto así puede hacer que la API de embeddings devuelva un 429 sin el
    campo "quotaId" que _quota_violation_period() necesita para distinguir
    un rate-limit transitorio de una cuota agotada; sin esta función, ese
    429 terminaría clasificado como "cuota desconocida" y podría abortar la
    corrida entera por un solo chunk sobredimensionado.

    Reutiliza MAX_SAFE_CHUNK_CHARS/split_text_into_windows de
    normativa_extraction.py (mismo límite de tamaño, sin duplicar la
    lógica). Es un no-op para el resto del corpus. El id de cada parte usa
    el sufijo ":PARTE_<i>_DE_<n>" sobre el id determinista ya asignado.
    """
    result: list = []
    split_count = 0
    for document in documents:
        text = document.text
        if len(text) <= MAX_SAFE_CHUNK_CHARS:
            result.append(document)
            continue

        windows = split_text_into_windows(text)
        total = len(windows)
        split_count += 1
        base_id = document.id_
        for i, window_text in enumerate(windows, start=1):
            part = deepcopy(document)
            part.set_content(window_text)
            part.id_ = f"{base_id}:PARTE_{i}_DE_{total}"
            result.append(part)

    if split_count:
        print(
            f"[ADVERTENCIA] Corpus '{corpus_label}': {split_count} documento(s) superaban "
            f"MAX_SAFE_CHUNK_CHARS ({MAX_SAFE_CHUNK_CHARS} caracteres) y se dividieron en "
            f"{len(result) - (len(documents) - split_count)} parte(s) más chicas antes de "
            "embeber (ver enforce_max_safe_chunk_size)."
        )
    return result


# --------------------------------------------------------------------------
# Paso 3: generar embeddings reales, con aislamiento de fallos por documento
# --------------------------------------------------------------------------


class _RateLimiter:
    """Ventana deslizante real: garantiza que nunca se disparen más de
    `max_requests` llamadas ni más de `max_tokens` tokens (estimados, ver
    _estimate_tokens) en cualquier ventana de `window_seconds` segundos
    consecutivos. `wait_for_slot(tokens)` debe llamarse inmediatamente antes
    de cada request HTTP real a embed_content. `max_tokens=None` desactiva
    ese chequeo."""

    def __init__(self, max_requests: int, window_seconds: float, max_tokens: int | None = None) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tokens = max_tokens
        self._entries: deque[tuple[float, int]] = deque()  # (timestamp, tokens)

    def _drop_expired(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self.window_seconds:
            self._entries.popleft()

    def wait_for_slot(self, tokens: int = 0) -> None:
        while True:
            now = time.monotonic()
            self._drop_expired(now)

            over_requests = len(self._entries) >= self.max_requests
            tokens_in_window = sum(t for _, t in self._entries)
            over_tokens = (
                self.max_tokens is not None
                and bool(self._entries)
                and tokens_in_window + tokens > self.max_tokens
            )
            if not over_requests and not over_tokens:
                break

            sleep_seconds = self.window_seconds - (now - self._entries[0][0])
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        self._entries.append((time.monotonic(), tokens))


_embed_rate_limiter = _RateLimiter(
    EMBED_RATE_LIMIT_MAX_REQUESTS,
    EMBED_RATE_LIMIT_WINDOW_SECONDS,
    max_tokens=EMBED_TOKEN_RATE_LIMIT_MAX_TOKENS,
)


class EmbeddingQuotaAbortError(RuntimeError):
    """Se lanza para cortar process_documents() ante un 429 de Gemini que no
    tiene sentido seguir reintentando dentro de la misma corrida: cuota
    DIARIA confirmada agotada, o cuota por minuto que sigue fallando después
    de agotar RATE_LIMIT_BATCH_MAX_RETRIES reintentos del lote/documento
    completo."""


def _is_rate_limit_error(error: BaseException) -> bool:
    """True si `error` es un 429 real de la API de Gemini (google-genai
    clasifica cualquier status 4xx como `ClientError`, con `.code` = status
    HTTP)."""
    return isinstance(error, ClientError) and getattr(error, "code", None) == 429


def _quota_violation_period(error: BaseException) -> str | None:
    """Distingue si el 429 viola la cuota DIARIA o la de POR MINUTO,
    inspeccionando el campo "quotaId" que Gemini incluye en el detalle
    QuotaFailure del error (p. ej. "...PerDay..." vs "...PerMinute...").

    Returns: "day", "minute" o None si no se pudo determinar.
    """
    details_text = str(getattr(error, "details", "") or "")
    if "PerDay" in details_text:
        return "day"
    if "PerMinute" in details_text:
        return "minute"
    return None


def _retry_delay_seconds(error: BaseException) -> float | None:
    """Extrae el retryDelay sugerido por Google (p. ej. "48s") del detalle
    RetryInfo del 429, si está presente. Devuelve None si no está, para que
    el llamador use su propio backoff exponencial."""
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None
    nested = details.get("error")
    if not isinstance(nested, dict):
        return None
    for item in nested.get("details") or []:
        if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s", str(item.get("retryDelay", "")))
            if match:
                return float(match.group(1))
    return None


def _embed_with_retry(embed_call, label: str, tokens: int = 0):
    """Ejecuta `embed_call()` respetando el rate limiter (`tokens` es la
    estimación conservadora de _estimate_tokens para esta llamada),
    reintentando la MISMA llamada completa ante un 429 de rate-limit (nunca
    fragmentándola), con backoff (usa el retryDelay de Google cuando está
    presente, si no un backoff exponencial propio). Aborta con
    EmbeddingQuotaAbortError si el 429 es de cuota DIARIA, o si se agotan
    los reintentos de un 429 por minuto. Cualquier otra excepción se
    re-lanza tal cual para que el llamador decida."""
    rate_limit_attempt = 0
    while True:
        _embed_rate_limiter.wait_for_slot(tokens)
        try:
            return embed_call()
        except Exception as error:  # noqa: BLE001 - se clasifica abajo
            if not _is_rate_limit_error(error):
                raise

            quota_period = _quota_violation_period(error)
            if quota_period == "day":
                raise EmbeddingQuotaAbortError(
                    f"Cuota DIARIA de Gemini para embed_content agotada en {label}. Esperar dentro de "
                    "esta misma corrida no sirve: la cuota diaria no resetea hasta el próximo ciclo de "
                    f"24hs de Google. Detalle real: {error}"
                ) from error

            rate_limit_attempt += 1
            if rate_limit_attempt > RATE_LIMIT_BATCH_MAX_RETRIES:
                raise EmbeddingQuotaAbortError(
                    f"{label}: se agotaron los {RATE_LIMIT_BATCH_MAX_RETRIES} reintentos completos ante "
                    f"un 429 de rate-limit (cuota={quota_period or 'desconocida'}) sin recuperarse. "
                    f"Detalle real: {error}"
                ) from error

            wait_seconds = _retry_delay_seconds(error)
            if wait_seconds is not None:
                wait_seconds += 2.0  # margen de seguridad sobre lo que sugiere Google
            else:
                wait_seconds = min(
                    RATE_LIMIT_BACKOFF_INITIAL_SECONDS * (2 ** (rate_limit_attempt - 1)),
                    RATE_LIMIT_BACKOFF_MAX_SECONDS,
                )
            print(
                f"[ADVERTENCIA] {label}: 429 rate-limit (cuota={quota_period or 'desconocida'}); "
                f"reintento {rate_limit_attempt}/{RATE_LIMIT_BATCH_MAX_RETRIES} de la llamada completa "
                f"en {wait_seconds:.0f}s..."
            )
            time.sleep(wait_seconds)


def process_documents(
    embed_model,
    index,
    documents: list,
    docstore: dict[str, dict],
) -> tuple[int, list[dict]]:
    """
    Genera embeddings para `documents` en lotes de EMBED_BATCH_SIZE y sube
    cada lote a Pinecone + persiste el docstore local de forma INCREMENTAL,
    inmediatamente después de generar el embedding de ese lote (para que una
    interrupción a mitad de corrida no pierda el progreso ya subido).

    `docstore` se recibe y se MUTA in-place (ya viene con las entradas
    resumidas de una corrida anterior, si las hay — ver plan_resume()).

    Orden dentro de cada lote: primero se persiste el docstore, después se
    hace el upsert a Pinecone, para que si el proceso muere entre medio el
    peor caso sea un lote re-embebido de más al reanudar (upsert es
    idempotente), nunca un vector en Pinecone sin texto local. Un 429 de
    rate-limit se reintenta sobre el MISMO LOTE COMPLETO vía
    _embed_with_retry() (nunca fragmentado); si la cuota violada es la
    DIARIA, o se agotan los reintentos de un 429 por minuto, se aborta la
    corrida entera (EmbeddingQuotaAbortError) — lo subido en lotes
    anteriores ya quedó persistido, así que no se pierde.

    El fallback documento por documento (para aislar el/los chunk(s)
    problemático(s)) sólo se alcanza para excepciones que NO son un 429.

    Returns:
        (uploaded_count, failures) donde uploaded_count es la cantidad total
        de vectores subidos a Pinecone en esta llamada, y failures es una
        lista de {"id", "corpus", "source", "error"}.

    Raises:
        EmbeddingQuotaAbortError: cuota diaria confirmada agotada, o cuota
        por minuto que no se recupera después de agotar los reintentos.
    """
    failures: list[dict] = []
    uploaded_total = 0

    # Los documentos con texto vacío no se pueden embeber de forma útil.
    embeddable = [d for d in documents if d.text and d.text.strip()]
    skipped_empty = len(documents) - len(embeddable)
    if skipped_empty:
        print(f"[ADVERTENCIA] {skipped_empty} documento(s) con texto vacío se omiten del embedding.")

    total = len(embeddable)
    done = 0
    batches = list(_batched(embeddable, EMBED_BATCH_SIZE))
    print(
        f"[INFO] Generando embeddings reales para {total} documentos en {len(batches)} lotes de hasta "
        f"{EMBED_BATCH_SIZE} (subida a Pinecone y persistencia del docstore INMEDIATAS tras cada lote, "
        "ver decisión de diseño 9)..."
    )

    for batch_idx, batch in enumerate(batches, start=1):
        texts = [d.text for d in batch]
        vectors: list[list[float]] | None = None
        try:
            vectors = _embed_with_retry(
                lambda texts=texts: embed_model.get_text_embedding_batch(texts),
                label=f"lote {batch_idx}/{len(batches)}",
                tokens=sum(_estimate_tokens(t) for t in texts),
            )
        except EmbeddingQuotaAbortError:
            # Cuota agotada: abortar la corrida (ver main()), nunca caer al
            # fallback documento por documento de abajo.
            raise
        except Exception as batch_error:  # noqa: BLE001 - error real de contenido, no un 429
            print(
                f"[ADVERTENCIA] Lote {batch_idx}/{len(batches)} falló completo (no es un 429: "
                f"{batch_error}); reintentando documento por documento para aislar el/los chunk(s) "
                "problemático(s)."
            )

        # (documento, vector_normalizado) del lote actual únicamente.
        batch_results: list[tuple[Any, list[float]]] = []
        if vectors is not None:
            for document, vector in zip(batch, vectors, strict=True):
                batch_results.append((document, normalize_embedding(vector)))
        else:
            for document in batch:
                try:
                    vector = _embed_with_retry(
                        lambda document=document: embed_model.get_text_embedding_batch([document.text])[0],
                        label=f"documento {document.id_!r}",
                        tokens=_estimate_tokens(document.text),
                    )
                    batch_results.append((document, normalize_embedding(vector)))
                except EmbeddingQuotaAbortError:
                    raise
                except Exception as doc_error:  # noqa: BLE001
                    failures.append(
                        {
                            "id": document.id_,
                            "corpus": document.metadata.get("corpus"),
                            "source": document.metadata.get("source") or document.metadata.get("source_url"),
                            "error": str(doc_error),
                        }
                    )

        if batch_results:
            # 1) Docstore primero (ver docstring de la función para el motivo).
            for document, _vector in batch_results:
                docstore[document.id_] = {"text": document.text, "metadata": document.metadata}
            _write_docstore_atomic(DOCSTORE_PATH, docstore)

            # 2) Upsert del mismo lote a Pinecone.
            vectors_payload = [
                {"id": document.id_, "values": vector, "metadata": build_metadata(document)}
                for document, vector in batch_results
            ]
            index.upsert(vectors=vectors_payload)
            uploaded_total += len(vectors_payload)

        done += len(batch)
        print(
            f"[INFO]   ... {done}/{total} documentos procesados, {uploaded_total} vector(es) subidos a "
            f"Pinecone hasta ahora (lote {batch_idx}/{len(batches)})."
        )

    print(
        f"[INFO] Proceso incremental terminado: {uploaded_total} subidos OK, {len(failures)} fallidos, "
        f"{skipped_empty} omitidos por texto vacío."
    )
    return uploaded_total, failures


# --------------------------------------------------------------------------
# Paso 4: resumibilidad real + overwrite total
# del índice de Pinecone para una corrida nueva / incompatible
# --------------------------------------------------------------------------


def build_metadata(document) -> dict[str, Any]:
    """Metadata corta y filtrable; el texto completo no va aquí, sólo al docstore local."""
    corpus = str(document.metadata.get("corpus", "desconocido"))
    metadata: dict[str, Any] = {"corpus": corpus}

    if corpus == "normativa":
        metadata["vigente"] = bool(document.metadata.get("vigente", True))
        articulo = str(document.metadata.get("articulo_numero", ""))[:METADATA_TEXT_MAX_LEN]
        if articulo:
            metadata["articulo_numero"] = articulo

    return metadata


def clear_index(index) -> None:
    """Borra TODO el contenido existente del índice antes de subir el corpus
    completo de esta corrida (overwrite total, para no acumular datapoints
    huérfanos con IDs "nuevos" tras un reprocesamiento)."""
    stats_before = index.describe_index_stats()
    count_before = stats_before.get("total_vector_count", 0)
    if count_before == 0:
        print("[INFO] El índice ya está vacío; no hace falta borrar nada.")
        return

    print(f"[INFO] Borrando los {count_before} vectores existentes del índice antes del overwrite total...")
    index.delete(delete_all=True)

    # delete_all() es async del lado de Pinecone; esperamos a que el conteo
    # confirme el borrado real antes de seguir.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if index.describe_index_stats().get("total_vector_count", 0) == 0:
            print("[INFO] Índice confirmado vacío.")
            return
        time.sleep(2)
    print("[ADVERTENCIA] No se pudo confirmar que el índice quedó vacío dentro del timeout; se sigue igual.")


def list_uploaded_ids(index) -> set[str]:
    """Enumera TODOS los IDs de vectores realmente presentes en el índice de
    Pinecone en este momento: es la fuente de verdad real para decidir qué
    ya se subió, en vez de confiar en la sola existencia del docstore local
    (que puede corresponder a una corrida vieja con chunking/IDs distintos).

    Usa `index.list()` (paginado, sólo trae IDs) en vez de `fetch()`, para
    no pagar el costo de traer vectores/metadata que acá no hacen falta."""
    existing: set[str] = set()
    for page in index.list(limit=100):
        for item in page.vectors:
            existing.add(item.id)
    return existing


def plan_resume(
    current_ids: set[str],
    existing_ids_in_pinecone: set[str],
    existing_docstore: dict[str, dict],
) -> tuple[str, set[str], dict[str, dict]]:
    """
    Decide, de forma PURA (sin tocar Pinecone ni disco, para poder testearla
    con datos sintéticos sin mocks), si esta corrida debe tratarse como
    nueva/overwrite o como resume real de una corrida interrumpida.

    Args:
        current_ids: IDs de TODOS los documentos que esta corrida está por
            procesar (después de build_*_documents()+enforce_max_safe_chunk_size()).
        existing_ids_in_pinecone: IDs realmente presentes en Pinecone ahora
            mismo (ver list_uploaded_ids()).
        existing_docstore: contenido crudo de vector_docstore.json ya en
            disco al arrancar (ver load_existing_docstore()).

    Returns:
        (reason, resumable_ids, docstore_kept)
        - reason: "empty_index" (índice vacío, corrida nueva),
          "incompatible_corpus" (índice con contenido pero sin ningún id en
          común con el corpus actual: datos de una corrida vieja
          incompatible) o "resume" (progreso real reutilizable).
        - resumable_ids: subconjunto de current_ids que ya está subido en
          Pinecone Y tiene texto en existing_docstore -> se SALTEA al
          procesar. Vacío salvo en el caso "resume".
        - docstore_kept: subconjunto de existing_docstore a usar como punto
          de partida del docstore de esta corrida (se descarta cualquier
          entrada que no sea parte del progreso real resumible, para no
          arrastrar basura de corpus/corridas viejas). Vacío salvo en el
          caso "resume".
    """
    if not existing_ids_in_pinecone:
        return "empty_index", set(), {}

    overlap = existing_ids_in_pinecone & current_ids
    if not overlap:
        return "incompatible_corpus", set(), {}

    # Sólo se conserva/saltea lo que está en Pinecone Y tiene texto local
    # (un id en Pinecone sin texto local se re-procesa en vez de darse por
    # perdido).
    docstore_kept = {doc_id: entry for doc_id, entry in existing_docstore.items() if doc_id in overlap}
    resumable_ids = overlap & docstore_kept.keys()
    return "resume", resumable_ids, docstore_kept


# --------------------------------------------------------------------------
# Paso 5: consulta de prueba real contra el índice
# --------------------------------------------------------------------------


def run_test_query(embed_model, index, docstore: dict[str, dict]) -> None:
    print(f"\n[INFO] Consulta de prueba: \"{TEST_QUERY}\"")

    query_vector = normalize_embedding(embed_model.get_query_embedding(TEST_QUERY))
    response = index.query(vector=query_vector, top_k=TEST_QUERY_TOP_K, include_metadata=False)
    matches = response.matches if response else []

    if not matches:
        print("[ERROR] La consulta de prueba no devolvió ningún resultado.")
        return

    print(f"[INFO] {len(matches)} resultado(s) devueltos por el índice:\n")
    for rank, match in enumerate(matches, start=1):
        entry = docstore.get(match.id, {})
        text = entry.get("text", "<sin texto local para este id>")
        metadata = entry.get("metadata", {})
        snippet = " ".join(text.split())[:300]
        print(f"  #{rank} id={match.id} score={match.score:.4f}")
        print(f"      corpus={metadata.get('corpus')} fuente={metadata.get('source') or metadata.get('source_url')}")
        print(f"      texto: {snippet}...\n")


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------


def main() -> None:
    embed_model = configure_embeddings()
    embed_model.embed_batch_size = EMBED_BATCH_SIZE

    print("\n=== Paso 1-2: cargando y convirtiendo los dos corpus a Document ===")
    normativa_documents = build_normativa_documents()
    tutorial_documents = build_tutorial_documents()

    # Red de seguridad de tamaño (ver enforce_max_safe_chunk_size): no-op
    # para normativa, divide páginas largas de tutorial antes de embeber.
    normativa_documents = enforce_max_safe_chunk_size(normativa_documents, "normativa")
    tutorial_documents = enforce_max_safe_chunk_size(tutorial_documents, "tutorial")

    all_documents = normativa_documents + tutorial_documents
    print(
        f"[INFO] Total de documentos combinados: {len(all_documents)} "
        f"(normativa={len(normativa_documents)}, tutorial={len(tutorial_documents)})."
    )
    current_ids = {d.id_ for d in all_documents}

    print("\n=== Paso 3: determinando progreso previo real (resumibilidad, ver decisión de diseño 9) ===")
    index = get_vector_store()
    existing_ids_in_pinecone = list_uploaded_ids(index)
    existing_docstore = load_existing_docstore(DOCSTORE_PATH)

    reason, resumable_ids, docstore = plan_resume(current_ids, existing_ids_in_pinecone, existing_docstore)

    if reason == "empty_index":
        print("[INFO] El índice de Pinecone está vacío: corrida nueva, no hay progreso previo que resumir.")
        clear_index(index)
    elif reason == "incompatible_corpus":
        print(
            f"[ADVERTENCIA] El índice tiene {len(existing_ids_in_pinecone)} vector(es) pero NINGUNO "
            "coincide con los IDs del corpus actual (son de una corrida vieja con corpus/chunking "
            "distinto, ver decisión de diseño 4). Se trata como corrida nueva: overwrite total."
        )
        clear_index(index)
    else:  # "resume"
        overlap = existing_ids_in_pinecone & current_ids
        missing_text = overlap - resumable_ids
        if missing_text:
            print(
                f"[ADVERTENCIA] {len(missing_text)} id(s) están subidos en Pinecone pero sin texto en "
                "el docstore local; se re-procesan (re-embeben y re-suben; upsert es idempotente, no "
                "genera duplicados) para no perder el texto local de esos chunks."
            )
        print(
            f"[INFO] Progreso previo real detectado: {len(resumable_ids)}/{len(current_ids)} documentos "
            "del corpus actual ya están subidos en Pinecone (corrida interrumpida anteriormente, mismo "
            "corpus/IDs deterministas). Se SALTEA clear_index() para no perder ese progreso; se sigue "
            "sólo con los documentos faltantes."
        )

    documents_to_process = [d for d in all_documents if d.id_ not in resumable_ids]
    print(
        f"[INFO] Documentos a procesar en esta corrida: {len(documents_to_process)}/{len(all_documents)} "
        f"({len(resumable_ids)} ya subido(s) previamente, se saltean)."
    )

    failures: list[dict] = []
    uploaded = 0
    if not documents_to_process:
        print("[INFO] No hay documentos pendientes: todo el corpus ya estaba subido. No se genera ningún embedding nuevo.")
        if reason == "resume":
            # Caso borde (corpus ya completo al reanudar): process_documents()
            # nunca corre, así que se persiste acá el `docstore` ya filtrado
            # por plan_resume() para no arrastrar entradas viejas.
            _write_docstore_atomic(DOCSTORE_PATH, docstore)
    else:
        print("\n=== Paso 4: generando embeddings y subiendo a Pinecone de forma incremental ===")
        try:
            uploaded, failures = process_documents(embed_model, index, documents_to_process, docstore)
        except EmbeddingQuotaAbortError as quota_error:
            print(f"\n[ERROR] {quota_error}")
            print(
                "[ERROR] Corrida abortada. El progreso subido HASTA este punto ya quedó persistido de "
                "forma incremental en Pinecone y en el docstore local (ver decisión de diseño 9): no se "
                "perdió. Para continuar, volvé a correr `python -m chatbot.vector_ingest` más tarde "
                "(cuando la cuota correspondiente de Gemini se recupere) — la próxima corrida detecta "
                "automáticamente lo ya subido y sólo procesa lo que falta."
            )
            sys.exit(1)

        if failures:
            print(f"\n[ADVERTENCIA] {len(failures)} documento(s) no se pudieron embeber:")
            for failure in failures:
                print(f"  - id={failure['id']} corpus={failure['corpus']} fuente={failure['source']}: {failure['error']}")

    fresh_stats = index.describe_index_stats()
    print(f"[INFO] Stats del índice tras esta corrida: {fresh_stats}")

    print("\n=== Paso 5: consulta de prueba real contra el índice ===")
    try:
        run_test_query(embed_model, index, docstore)
    except Exception as e:  # noqa: BLE001 - no queremos perder el resumen final por un fallo aquí
        print(f"[ERROR] La consulta de prueba falló: {e}")

    print("\n=== Resumen final ===")
    print(f"Documentos combinados:    {len(all_documents)}")
    print(f"Ya subidos previamente:   {len(resumable_ids)}")
    print(f"Subidos en esta corrida:  {uploaded}")
    print(f"Fallos de embedding:      {len(failures)}")
    print(f"Total en docstore local:  {len(docstore)}")


if __name__ == "__main__":
    main()
