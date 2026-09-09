"""
main.py
Servidor HTTP del chatbot RAG de ARCSA (FastAPI). Expone `POST /api/chat`,
consumido por frontend/src/services/transport/HttpChatTransport.js.

Flujo por solicitud: embebe la pregunta, busca los top-k chunks más
relevantes en Pinecone, resuelve esos IDs a texto/metadata vía el docstore
local generado por vector_ingest.py (Pinecone no guarda el texto completo),
arma un prompt "grounded" para Gemini y devuelve la respuesta + fuentes
citadas en el formato que espera RagSourcesDrawer.jsx.

El modelo de embeddings y la normalización a norma 1 están centralizados en
vector_store.py (fuente de verdad única, ver `configure_embeddings()` /
`normalize_embedding()`).
"""

from __future__ import annotations

import functools
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from llama_index.llms.google_genai import GoogleGenAI
from pydantic import BaseModel, Field

from auth import router as auth_router
from conversations import router as conversations_router
from vector_store import configure_embeddings, get_vector_store, normalize_embedding

# Cargar variables de entorno desde un archivo .env si existe
load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("chatbot.main")

CHATBOT_DIR = Path(__file__).resolve().parent
NORMATIVA_DIR = CHATBOT_DIR / "data" / "normativa"
DOCSTORE_PATH = CHATBOT_DIR / "data" / "vector_docstore.json"

TOP_K = 5
ISSUING_ENTITY = "Agencia Nacional de Regulación, Control y Vigilancia Sanitaria (ARCSA)"
OFFICIAL_ARCSA_URL = "https://www.controlsanitario.gob.ec/"

# Hosts del portal ARCSA que solo responden por HTTPS (el puerto 80 no
# responde). Ver _normalize_official_url_scheme.
_HTTPS_ONLY_HOSTS = {"controlsanitario.gob.ec", "www.controlsanitario.gob.ec"}

NO_EVIDENCE_TEXT = (
    "No se encontró evidencia suficiente ni normativa oficial en la base de datos "
    "de ARCSA para responder con precisión a esta consulta."
)

# ---------------------------------------------------------------------------
# Configuración de Gemini (LLM)
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("La variable de entorno GEMINI_API_KEY no está configurada.")
    logger.error("Por favor, crea un archivo .env o configúrala en tu entorno de ejecución.")
    raise SystemExit(1)

logger.info("Inicializando el modelo Gemini LLM (gemini-3.5-flash-lite)...")
llm = GoogleGenAI(model="gemini-3.5-flash-lite", api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# Configuración de embeddings para las consultas RAG (fuente de verdad:
# chatbot/vector_store.py, ver nota en el docstring del módulo).
# ---------------------------------------------------------------------------

embed_model = configure_embeddings()


# ---------------------------------------------------------------------------
# Acceso al índice de Pinecone (ver chatbot/vector_store.py).
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _get_pinecone_index():
    return get_vector_store()


# ---------------------------------------------------------------------------
# Docstore local (id -> {text, metadata}). Pinecone no guarda el texto
# completo del chunk; lo genera vector_ingest.py y este servidor sólo lo lee.
# Se cachea por mtime (no de forma permanente) porque la ingesta puede seguir
# corriendo en paralelo y regenerar el archivo con el servidor ya arriba.
# ---------------------------------------------------------------------------

_docstore_cache: dict[str, Any] = {"mtime": None, "data": {}}


def _load_docstore() -> dict[str, dict]:
    if not DOCSTORE_PATH.exists():
        if _docstore_cache["mtime"] is not None:
            logger.warning(f"'{DOCSTORE_PATH}' ya no existe; se limpia la caché local.")
        _docstore_cache["mtime"] = None
        _docstore_cache["data"] = {}
        return {}

    mtime = DOCSTORE_PATH.stat().st_mtime
    if _docstore_cache["mtime"] != mtime:
        logger.info(f"(Re)cargando docstore local desde '{DOCSTORE_PATH}'...")
        with DOCSTORE_PATH.open(encoding="utf-8") as f:
            _docstore_cache["data"] = json.load(f)
        _docstore_cache["mtime"] = mtime
        logger.info(f"Docstore cargado: {len(_docstore_cache['data'])} entradas.")

    return _docstore_cache["data"]


@functools.lru_cache(maxsize=512)
def _lookup_normativa_url(file_id: str) -> str | None:
    """Resuelve la URL oficial de un documento de Normativa a partir de su
    JSON crudo en chatbot/data/normativa/ (el docstore no guarda esta URL)."""
    if not file_id:
        return None
    path = NORMATIVA_DIR / f"{file_id}.json"
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            record = json.load(f)
        return record.get("url_final")
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Recuperación de chunks relevantes
# ---------------------------------------------------------------------------


def retrieve_chunks(query: str, top_k: int = TOP_K) -> list[dict]:
    """Embebe la consulta, busca los vecinos más cercanos en el índice de
    Pinecone y resuelve su texto/metadata real vía el docstore local."""
    docstore = _load_docstore()

    query_vector = normalize_embedding(embed_model.get_query_embedding(query))

    index = _get_pinecone_index()
    response = index.query(vector=query_vector, top_k=top_k, include_metadata=False)
    matches = response.matches if response else []

    results = []
    for match in matches:
        entry = docstore.get(match.id)
        if not entry:
            # Vector en Pinecone sin entrada todavía en el docstore local
            # (carga en curso) o de una corrida anterior.
            logger.info(f"Vecino id={match.id} sin entrada en el docstore local; se omite.")
            continue
        results.append(
            {
                "id": match.id,
                # Con metric="cosine" sobre vectores normalizados, `score` de
                # Pinecone es directamente la similitud coseno (más alto =
                # más similar), pese al nombre "distance" del campo.
                "distance": match.score,
                "text": entry.get("text", ""),
                "metadata": entry.get("metadata", {}),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Umbral de confianza de la recuperación (RAG)
# ---------------------------------------------------------------------------
# `distance` es en realidad la similitud coseno (vectores normalizados,
# métrica cosine); más alto = más similar, pese al nombre del campo.
#
# 0.70 se calibró empíricamente comparando preguntas fuera de dominio
# (similitud ~0.63-0.70) contra preguntas reales con respuesta verificable
# en el corpus (similitud >0.73). Se usa el máximo de los top-k, no el
# promedio: top_k=5 siempre trae vecinos con relevancia decreciente incluso
# en una búsqueda exitosa, así que promediar castigaría preguntas bien
# resueltas por un único chunk muy relevante.
SIMILARITY_THRESHOLD = 0.70


def _is_low_confidence(chunks: list[dict]) -> bool:
    """True si ni siquiera el mejor vecino recuperado supera
    SIMILARITY_THRESHOLD, es decir, la base normativa no tiene nada lo
    bastante relevante como para confiar en el CONTEXTO."""
    if not chunks:
        return True
    best_distance = max(chunk.get("distance", 0.0) for chunk in chunks)
    return best_distance < SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# Filtrado de fuentes citadas por relevancia INDIVIDUAL (por chunk)
# ---------------------------------------------------------------------------
# Sin este filtro, los 5 chunks de top_k se citaban siempre en bloque como
# fuente aunque sólo 1-2 fueran realmente relevantes (medido en la
# evaluación de chatbot/eval/). Se reutiliza el mismo SIMILARITY_THRESHOLD
# ya calibrado, pero aplicado por chunk en vez de sólo al máximo del grupo.
def _filter_citable_sources(chunks: list[dict]) -> list[tuple[int, dict]]:
    """Devuelve pares (índice_original_1-based, chunk) sólo para los chunks
    cuya `distance` individual alcanza SIMILARITY_THRESHOLD.

    Se preserva el índice ORIGINAL porque es el mismo número que ve Gemini
    como "Fuente N" en el prompt; renumerar rompería esa correspondencia.

    Si ningún chunk supera el umbral se devuelve una lista vacía (sin
    fallback al "mejor de los 5"): ese caso coincide con
    `_is_low_confidence()=True`, donde el prompt ya advierte a Gemini de la
    baja confianza.
    """
    return [
        (i, chunk)
        for i, chunk in enumerate(chunks, start=1)
        if chunk.get("distance", 0.0) >= SIMILARITY_THRESHOLD
    ]


# ---------------------------------------------------------------------------
# Construcción del prompt "grounded" y de las fuentes citadas
# ---------------------------------------------------------------------------


def _build_grounded_prompt(question: str, chunks: list[dict], *, low_confidence: bool = False) -> str:
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        etiqueta = metadata.get("source") or metadata.get("title") or "Fuente ARCSA"
        articulo = metadata.get("articulo_numero")
        if articulo and articulo != "DOCUMENTO_COMPLETO":
            etiqueta = f"{etiqueta} - Artículo {articulo}"
        context_blocks.append(f"[Fuente {i}: {etiqueta}]\n{chunk.get('text', '')}")

    context_text = "\n\n".join(context_blocks)

    low_confidence_warning = (
        "\nADVERTENCIA DE BAJA RELEVANCIA: la búsqueda en la base normativa no "
        "encontró contenido claramente relevante para esta pregunta (similitud "
        "baja con el CONTEXTO). Es probable que el CONTEXTO de abajo NO "
        "contenga la respuesta exacta, aunque hable de temas relacionados. "
        "Sé especialmente cauteloso: ante la mínima duda, indica que no "
        "tienes información suficiente en vez de responder con precisión "
        "aparente.\n"
        if low_confidence
        else ""
    )

    return (
        "Eres un asistente virtual oficial de ARCSA (Agencia Nacional de Regulación, "
        "Control y Vigilancia Sanitaria de Ecuador). Debes responder EXCLUSIVAMENTE "
        "con base en el CONTEXTO que se entrega más abajo. Sigue estas reglas de "
        "forma estricta, sin excepción:\n"
        "1. No uses conocimiento general propio ni supuestos externos al CONTEXTO, "
        "aunque creas conocer la respuesta o te parezca razonable: si un dato no "
        "está en el CONTEXTO, no lo sabes.\n"
        "2. Nunca afirmes un dato específico (monto, tasa, plazo en días, "
        "porcentaje, número de artículo o resolución, requisito, fórmula, etc.) "
        "que no aparezca textualmente en el CONTEXTO. Antes de citar una cifra, "
        "verifica que esa cifra exacta esté escrita en el CONTEXTO.\n"
        "3. Si el CONTEXTO no contiene información suficiente para responder con "
        "precisión -total o parcialmente-, dilo explícitamente (por ejemplo: 'No "
        "tengo información suficiente en la base normativa de ARCSA para "
        "responder esto con precisión') en lugar de adivinar, inferir o "
        "completar con suposiciones.\n"
        "4. Si la pregunta del usuario da por cierto un dato (monto, plazo, "
        "vigencia, etc.) que no puedes confirmar textualmente en el CONTEXTO, "
        "señálalo explícitamente como no confirmado en vez de asumirlo como "
        "válido y seguir adelante.\n"
        "5. Cita el número de Artículo y/o el nombre del documento del que "
        "proviene cada dato relevante que menciones.\n"
        "Responde en español, de forma clara y concisa.\n"
        f"{low_confidence_warning}\n"
        f"CONTEXTO:\n{context_text}\n\n"
        f"PREGUNTA DEL USUARIO:\n{question}\n\n"
        "RESPUESTA:"
    )


def _normalize_official_url_scheme(url: str | None) -> str | None:
    """
    Fuerza esquema https:// para cualquier officialUrl de
    controlsanitario.gob.ec que llegue con http:// (el sitio no responde por
    puerto 80). Defensa en tiempo de request para docstores existentes que
    puedan tener entradas antiguas en http://; el fix de origen está en
    tutorial_ingestion.py._normalize_source_url_scheme.
    """
    if not url or not url.startswith("http://"):
        return url
    parsed = urlparse(url)
    if parsed.netloc.lower() in _HTTPS_ONLY_HOSTS:
        return parsed._replace(scheme="https").geturl()
    return url


def _build_source_citation(chunk: dict, index: int) -> dict:
    """Arma una fuente en el formato que espera
    frontend/src/components/chat/RagSourcesDrawer.jsx."""
    metadata = chunk.get("metadata", {})
    corpus = metadata.get("corpus")
    text = chunk.get("text", "")
    snippet = " ".join(text.split())[:300]

    if corpus == "tutorial":
        document_title = metadata.get("title") or "Instructivo ARCSA"
        section = None
        official_url = metadata.get("source_url")
        validity_status = "Vigente"
    else:
        document_title = metadata.get("source") or "Normativa ARCSA"
        articulo = metadata.get("articulo_numero")
        section = (
            f"Artículo {articulo}" if articulo and articulo != "DOCUMENTO_COMPLETO" else None
        )
        official_url = _lookup_normativa_url(metadata.get("file_id", ""))
        vigente = metadata.get("vigente", True)
        validity_status = "Vigente" if vigente else "Posiblemente desactualizada"

    official_url = _normalize_official_url_scheme(official_url)

    return {
        "id": chunk.get("id") or f"src-{index}",
        "documentTitle": document_title,
        "issuingEntity": ISSUING_ENTITY,
        "section": section,
        "validityStatus": validity_status,
        "snippet": snippet,
        "officialUrl": official_url or OFFICIAL_ARCSA_URL,
    }


# ---------------------------------------------------------------------------
# API HTTP (FastAPI)
# ---------------------------------------------------------------------------

app = FastAPI(title="ARCSA RAG Chatbot API")

_default_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Puerto del dev server de Vite (npm run dev).
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_cors_origins_env = os.getenv("CORS_ORIGINS")
_allow_origins = (
    [origin.strip() for origin in _cors_origins_env.split(",")]
    if _cors_origins_env
    else _default_cors_origins
)

# "*" con allow_credentials=True es inválido (el navegador rechaza igual la
# respuesta); falla rápido acá en vez de un error de CORS opaco en runtime.
if "*" in _allow_origins:
    raise SystemExit(
        "CORS_ORIGINS no puede incluir '*' porque allow_credentials=True está "
        "activado (necesario para el token Bearer de auth). Listá orígenes "
        "exactos separados por coma, p. ej. https://mi-frontend.com."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints de autenticación (ver chatbot/auth.py).
app.include_router(auth_router)

# Endpoints de historial de conversaciones (ver chatbot/conversations.py).
app.include_router(conversations_router)


class ChatRequest(BaseModel):
    """Cuerpo esperado por POST /api/chat, igual al que envía
    frontend/src/services/transport/HttpChatTransport.js."""

    message: str = Field(..., min_length=1)
    provider: str | None = None
    messages: list[dict] | None = None


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    question = payload.message.strip()
    if not question:
        return JSONResponse(
            status_code=400, content={"error": "El campo 'message' no puede estar vacío."}
        )

    logger.info(f"Consulta recibida: {question!r}")

    try:
        chunks = retrieve_chunks(question, top_k=TOP_K)
    except Exception as exc:  # noqa: BLE001 - se reporta al cliente igual
        logger.exception("Error al consultar el índice de Pinecone.")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error al consultar la base vectorial: {exc}"},
        )

    if not chunks:
        logger.info(
            "No se encontraron chunks relevantes (índice vacío/incompleto todavía o "
            "sin coincidencias reales para esta consulta)."
        )
        return {
            "text": NO_EVIDENCE_TEXT,
            "sources": [],
            "isLowConfidence": True,
            "officialUrl": OFFICIAL_ARCSA_URL,
        }

    citable_sources = _filter_citable_sources(chunks)
    sources = [_build_source_citation(chunk, i) for i, chunk in citable_sources]
    if len(sources) < len(chunks):
        logger.info(
            f"Se citan {len(sources)}/{len(chunks)} chunks recuperados como fuente "
            f"(el resto no alcanzó SIMILARITY_THRESHOLD={SIMILARITY_THRESHOLD} de "
            f"relevancia individual, ver _filter_citable_sources) para la consulta "
            f"{question!r}."
        )
    is_low_confidence = _is_low_confidence(chunks)
    if is_low_confidence:
        best_distance = max(chunk.get("distance", 0.0) for chunk in chunks)
        logger.info(
            f"Recuperación de baja confianza (mejor distancia={best_distance:.4f} "
            f"< umbral={SIMILARITY_THRESHOLD}) para la consulta {question!r}."
        )
    prompt = _build_grounded_prompt(question, chunks, low_confidence=is_low_confidence)

    try:
        response = llm.complete(prompt)
        answer_text = response.text
    except Exception as exc:  # noqa: BLE001 - se traduce a un status HTTP razonable
        logger.exception("Error al llamar a la API de Gemini.")
        status_code = getattr(exc, "code", None)
        if status_code not in (401, 402, 403, 429):
            status_code = 500
        return JSONResponse(
            status_code=status_code,
            content={"error": f"Error al generar la respuesta con Gemini: {exc}"},
        )

    return {
        "text": answer_text,
        "sources": sources,
        "isLowConfidence": is_low_confidence,
    }


if __name__ == "__main__":
    import uvicorn

    # forwarded_allow_ips="": sin esto, uvicorn confía en X-Forwarded-For
    # entrante desde loopback y reescribe la IP del cliente con ese header,
    # lo que permite evadir el rate limiting de /api/auth/* (chatbot/auth.py)
    # rotándolo en cada intento. No hay proxy real delante de este servidor.
    # Si se levanta con `uvicorn main:app` a mano, pasar el mismo flag
    # `--forwarded-allow-ips=""` (ver Dockerfile).
    uvicorn.run(app, host="0.0.0.0", port=8001, forwarded_allow_ips="")
