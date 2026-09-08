"""
main.py
Servidor HTTP real del chatbot RAG de ARCSA (FastAPI).

Este archivo reemplaza al antiguo `main.py` de un solo uso (que sólo hacía
una llamada de prueba a Gemini y salía). Ahora es el punto de entrada real
del backend: expone `POST /api/chat`, el endpoint que el frontend
(frontend/src/services/transport/HttpChatTransport.js) ya consume contra
`${VITE_API_URL}/api/chat` (por defecto http://localhost:8001, ver
docker-compose.yml).

Flujo por solicitud:
  1. Recibe la pregunta del usuario.
  2. La embebe con el mismo modelo de embeddings usado al cargar el índice.
  3. Busca los top-k chunks más relevantes en el índice de Pinecone.
  4. Resuelve esos IDs a texto/metadata real vía el docstore local generado
     por chatbot/vector_ingest.py (Pinecone sólo guarda id+embedding+metadata
     corta, nunca el texto completo del chunk).
  5. Arma un prompt "grounded" (respuesta basada sólo en ese contexto) y se
     lo envía a Gemini (gemini-3.5-flash-lite, igual que la versión anterior
     de este archivo).
  6. Devuelve la respuesta + las fuentes citadas, en el formato que ya
     esperan frontend/src/services/transport/processUiMessageStream.js y
     frontend/src/components/chat/RagSourcesDrawer.jsx.

NOTA sobre reutilización de chatbot/vector_store.py
----------------------------------------------------------------
Este servidor reutiliza directamente `configure_embeddings()` y
`get_vector_store()` de vector_store.py: ese módulo es la única fuente de
verdad para el modelo de embeddings ("models/gemini-embedding-001" con
output_dimensionality=768, para calzar con la dimensión fija del índice de
Pinecone) y para la normalización manual a norma 1 (ver `normalize_embedding()`
en vector_store.py).

NOTA sobre la migración Vertex AI → Pinecone (2026-09-08)
----------------------------------------------------------------
El proyecto usó originalmente Vertex AI Vector Search (ver
docs/adr/0002-vertex-ai-vector-search.md) hasta que se deshabilitó la
facturación del proyecto GCP por costo, dejándolo inoperativo (403
BILLING_DISABLED). Se migró a Pinecone (plan Starter, gratuito): sin bucket
de staging, sin cuenta de servicio de GCP, sin batch job asíncrono — el
upsert/query es una llamada directa de API. Los embeddings en sí no
cambiaron (siguen siendo Gemini), sólo el backend de almacenamiento/búsqueda
vectorial.
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

# Hosts del portal ARCSA que solo sirven por HTTPS (el puerto 80 no
# responde — ConnectTimeout confirmado). Ver _normalize_official_url_scheme.
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
# Docstore local (id -> {text, metadata}). Pinecone sólo guarda
# id + embedding + metadata corta, nunca el texto completo (ver
# chatbot/vector_ingest.py, decisión de diseño 3). Ese script es quien
# genera chatbot/data/vector_docstore.json; este servidor SÓLO LO LEE.
#
# Se cachea por mtime (no de forma permanente) porque el proceso de carga
# de datos puede seguir corriendo en paralelo y regenerar/ampliar este
# archivo mientras el servidor ya está arriba.
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
    JSON crudo en chatbot/data/normativa/ (el docstore no guarda esta URL,
    sólo articulo_numero/source/vigente, ver ingestion.py)."""
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
            # El vector existe en Pinecone pero todavía no está en el
            # docstore local (carga de datos en curso) o es de una corrida
            # anterior.
            logger.info(f"Vecino id={match.id} sin entrada en el docstore local; se omite.")
            continue
        results.append(
            {
                "id": match.id,
                # Con metric="cosine" sobre vectores normalizados, `score` de
                # Pinecone ES la similitud coseno (más alto = más similar),
                # mismo significado que tenía `distance` con Vertex (ver nota
                # más abajo sobre SIMILARITY_THRESHOLD).
                "distance": match.score,
                "text": entry.get("text", ""),
                "metadata": entry.get("metadata", {}),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Umbral de confianza de la recuperación (RAG)
# ---------------------------------------------------------------------------
# El índice usa métrica de similitud coseno sobre vectores normalizados a
# norma 1 (ver `normalize_embedding()` en vector_store.py), así que el campo
# `distance` que arma `retrieve_chunks()` (a partir de `match.score` de
# Pinecone; antes venía de `find_neighbors()` de Vertex, mismo significado)
# es, en realidad, la similitud coseno entre la pregunta y el chunk (más alto
# = más similar; no es una distancia en el sentido geométrico habitual, a
# pesar del nombre).
#
# Este umbral se calibró empíricamente (2026-09-01) llamando a
# retrieve_chunks() contra el índice real desplegado (entonces Vertex AI
# Vector Search; los valores siguen siendo válidos tras la migración a
# Pinecone porque el modelo de embeddings y la normalización no cambiaron,
# sólo el backend de búsqueda), con preguntas de control diseñadas para
# cubrir ambos extremos:
#
#   - Preguntas totalmente ajenas a ARCSA/normativa sanitaria
#     ("Dame la receta de ceviche ecuatoriano"):
#       distancia del mejor vecino = 0.6470, promedio de los 5 = 0.6350
#   - Preguntas sobre un trámite/categoría que NO existe en la normativa
#     (permiso de funcionamiento para un "dron fumigador agrícola" como
#     dispositivo médico): distancia del mejor vecino = 0.6985, promedio =
#     0.6929 (el modelo sí contestó correctamente "no tengo esa información",
#     pero isLowConfidence seguía dando False antes de este cambio)
#   - Preguntas reales con respuesta exacta y verificable en el corpus (monto
#     exacto de una tasa para una categoría específica de empresa, plazo
#     exacto en días de un trámite, fórmula de cálculo de otra tasa):
#       distancias del mejor vecino = 0.7365 / 0.7595 / 0.7865
#
# 0.70 sobre la distancia MÁXIMA (el mejor vecino, no el promedio) separa
# limpiamente ambos grupos en esta calibración. Se usa el máximo y no el
# promedio porque top_k=5 siempre trae vecinos 2..5 con relevancia
# decreciente incluso en una búsqueda exitosa; promediarlos castigaría
# preguntas bien resueltas por un único chunk fuertemente relevante (p. ej.
# la pregunta de la tasa exacta arriba tenía promedio=0.7220, por debajo de
# lo que parecería "seguro" a simple vista, pese a que el chunk correcto
# estaba ahí con distancia 0.7365).
#
# Nota: 768 dimensiones + texto en español del mismo dominio regulatorio
# generan una similitud "de fondo" no despreciable (~0.60-0.65) incluso para
# preguntas sin relación real; este umbral no pretende ser perfecto, sólo
# reflejar mejor la señal real que ya se calcula y se descartaba.
SIMILARITY_THRESHOLD = 0.70


def _is_low_confidence(chunks: list[dict]) -> bool:
    """Señal real de confianza de la recuperación: True si ni siquiera el
    mejor vecino recuperado supera SIMILARITY_THRESHOLD, es decir, si lo más
    parecido que se encontró en la base normativa no es lo bastante relevante
    como para confiar en que el CONTEXTO realmente contiene la respuesta.
    Antes de este cambio, isLowConfidence sólo era True cuando no había NINGÚN
    chunk recuperado (lista vacía), lo cual no detectaba recuperación
    irrelevante-pero-no-vacía (ver docstring de SIMILARITY_THRESHOLD)."""
    if not chunks:
        return True
    best_distance = max(chunk.get("distance", 0.0) for chunk in chunks)
    return best_distance < SIMILARITY_THRESHOLD


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
    controlsanitario.gob.ec que llegue con http://.

    Defensa en tiempo de request contra citas muertas en
    RagSourcesDrawer.jsx: el sitio real solo responde por HTTPS (el
    puerto 80 no responde, ConnectTimeout confirmado), pero
    chatbot/data/vector_docstore.json puede tener (o volver a tener, si se
    re-ingesta sin pasar por el fix de tutorial_ingestion.py) entradas de
    Tutorial con `metadata.source_url` en http://. Este parche hace que la
    corrección tome efecto de inmediato para el docstore YA existente, sin
    depender de un re-scrape/re-ingest (costoso) ni de una limpieza manual
    del JSON — es un complemento defensivo, no un reemplazo, del fix en el
    origen (tutorial_ingestion.py._normalize_source_url_scheme) y del
    parche aplicado directamente sobre vector_docstore.json.
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
        validity_date = "Vigente"
    else:
        document_title = metadata.get("source") or "Normativa ARCSA"
        articulo = metadata.get("articulo_numero")
        section = (
            f"Artículo {articulo}" if articulo and articulo != "DOCUMENTO_COMPLETO" else None
        )
        official_url = _lookup_normativa_url(metadata.get("file_id", ""))
        vigente = metadata.get("vigente", True)
        validity_date = "Vigente" if vigente else "Posiblemente desactualizada"

    official_url = _normalize_official_url_scheme(official_url)

    return {
        "id": chunk.get("id") or f"src-{index}",
        "documentTitle": document_title,
        "issuingEntity": ISSUING_ENTITY,
        "section": section,
        "validityDate": validity_date,
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
    # Puerto real del dev server de Vite usado en este proyecto (ver
    # frontend/package.json / npm run dev): sin esto, el preflight CORS de
    # /api/auth/* y /api/conversations/* falla con 400 contra un frontend
    # local recién levantado que no seteó CORS_ORIGINS a mano en .env.
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_cors_origins_env = os.getenv("CORS_ORIGINS")
_allow_origins = (
    [origin.strip() for origin in _cors_origins_env.split(",")]
    if _cors_origins_env
    else _default_cors_origins
)

# "*" combinado con allow_credentials=True es un error de configuración
# fácil de cometer (es la respuesta intuitiva a "abrir CORS") que deja la
# app rota de forma confusa: el navegador rechaza igual las respuestas con
# credenciales contra un origen wildcard. Falla rápido acá en vez de dejar
# que se descubra en producción con un error de CORS opaco en el browser.
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

# Endpoints de autenticación real (POST /api/auth/signup, /login, GET /me,
# POST /logout). Quedan cubiertos por el mismo middleware de CORS de arriba,
# no hace falta configurarlo de nuevo (ver chatbot/auth.py).
app.include_router(auth_router)

# Endpoints de persistencia de historial de conversaciones, atados al
# usuario logueado (GET/POST /api/conversations, GET/DELETE
# /api/conversations/{id}, POST /api/conversations/{id}/messages). Mismo
# middleware de CORS de arriba, ver chatbot/conversations.py.
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

    sources = [_build_source_citation(chunk, i) for i, chunk in enumerate(chunks, start=1)]
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

    # forwarded_allow_ips="": sin esto, uvicorn confía por defecto en un
    # X-Forwarded-For entrante desde loopback y reescribe la IP del cliente
    # con lo que diga ese header — evadía por completo el rate limiting de
    # /api/auth/login|signup (chatbot/auth.py) con solo rotar ese header en
    # cada intento (encontrado con fuzzing real). No hay ningún proxy real
    # delante de este servidor, así que no hay que confiar en ese header.
    # OJO: esto sólo cubre `python main.py`; si se levanta con
    # `python -m uvicorn main:app ...` a mano hay que pasar el mismo
    # `--forwarded-allow-ips=""` en la línea de comandos (ver Dockerfile).
    uvicorn.run(app, host="0.0.0.0", port=8001, forwarded_allow_ips="")
