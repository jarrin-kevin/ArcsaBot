"""
test_integration_rag.py
Suite de tests de INTEGRACIÓN REALES para el pipeline RAG completo:
Gemini (embeddings + LLM) + Pinecone (vector store real) + docstore local
(chatbot/data/vector_docstore.json) + POST /api/chat end-to-end.

A diferencia de chatbot/tests/test_auth.py y test_conversations.py (que
corren siempre, contra una base SQLite temporal, sin ninguna credencial
externa), esta suite NO usa mocks para Pinecone ni para Gemini: la gracia
de un test de integración es probar contra los servicios reales. Como
contrapartida, esta suite sólo puede dar una señal real cuando:

  1. Existe GEMINI_API_KEY real en el entorno/.env (la usan
     chatbot/vector_store.py::configure_embeddings() y chatbot/main.py
     para el LLM).
  2. Existe PINECONE_API_KEY real en el entorno/.env.
  3. El índice de Pinecone (chatbot/vector_store.py::PINECONE_INDEX_NAME,
     "arcsa-rag-index") ya existe y tiene al menos 1 vector cargado.

Mientras falte cualquiera de esas 3 condiciones, TODO este archivo se salta
limpiamente (ver _PIPELINE_READY/_SKIP_REASON y el `pytestmark` más abajo):
no falla ni da error, aparece como SKIPPED en el resumen de pytest, con un
mensaje explicando exactamente qué falta. Esto es intencional aunque, en
rigor, uno de los tests (test_configure_embeddings_and_normalize_embedding_
produce_unit_vector) sólo necesita GEMINI_API_KEY y no Pinecone: se lo
saltea igual junto con el resto para no empezar a gastar cuota real de la
API de Gemini en cada corrida de `pytest chatbot/tests/` mientras el resto
del pipeline (Pinecone) todavía no está configurado - recién tiene sentido
que este archivo empiece a correr de verdad cuando las 3 condiciones de
arriba se cumplan a la vez.

Cómo correr esto de verdad más adelante
----------------------------------------------------------------
1. Crear una cuenta de Pinecone (plan Starter, gratuito) y poner la API key
   real en PINECONE_API_KEY dentro del .env de la raíz del repo (junto a
   GEMINI_API_KEY, que ya debería existir del resto del proyecto).
2. Desde la raíz del repositorio, con las dependencias de
   chatbot/requirements.txt instaladas:

       python -m chatbot.vector_ingest

   Esto crea el índice "arcsa-rag-index" en Pinecone (dimension=768,
   metric="cosine"), sube los embeddings reales de los dos corpus
   (Normativa + Tutorial) y genera chatbot/data/vector_docstore.json
   (id -> {text, metadata}), que es lo que permite a retrieve_chunks()
   resolver los resultados de Pinecone a texto real.
3. Correr esta suite (sola o junto con el resto):

       pytest chatbot/tests/test_integration_rag.py -v
       pytest chatbot/tests/ -v

Notas de implementación descubiertas al escribir este archivo (documentado
por pedido explícito, ver el chat que originó esta suite)
----------------------------------------------------------------
- chatbot/main.py NO se puede importar como paquete "chatbot.main": sus
  imports internos son absolutos y asumen que chatbot/ (no la raíz del
  repo) está en sys.path (`from auth import ...`, `from vector_store import
  ...`; ver también el comentario equivalente en conftest.py). Por eso este
  archivo importa `main` a secas, reutilizando el mismo sys.path.insert()
  que ya hace conftest.py para chatbot/tests/.
- Al contrario de lo que se podía asumir de entrada, `import main` NO
  requiere PINECONE_API_KEY: get_vector_store()/el índice de Pinecone se
  resuelven de forma perezosa (`functools.lru_cache`) recién dentro de
  retrieve_chunks(), nunca a nivel de módulo. Lo que `import main` SÍ hace
  de forma eager (confirmado empíricamente) es:
    (a) fallar con `raise SystemExit(1)` si falta GEMINI_API_KEY
        (chatbot/main.py, ~línea 96), y
    (b) instanciar `GoogleGenAI(model="gemini-3.5-flash-lite", ...)`, lo
        cual dispara una llamada HTTP real (GET .../v1beta/models/
        gemini-3.5-flash-lite) contra la API de Gemini para validar el
        modelo, aunque no se haga ninguna consulta todavía.
  Por eso `import main` se hace acá SIEMPRE de forma perezosa, dentro del
  fixture `main_module` (nunca a nivel de módulo de este archivo): el
  código a nivel de módulo de un archivo de test corre en tiempo de
  *collection* de pytest sin importar si el test después queda SKIPPED, así
  que un `import main` top-level (a) rompería la recolección completa con
  un SystemExit crudo si faltara GEMINI_API_KEY (en vez de un SKIPPED
  prolijo), y (b) gastaría una llamada real a la API de Gemini incluso
  cuando el resto del pipeline (Pinecone) todavía no está listo.
- chatbot/vector_ingest.py importa sus dependencias internas como paquete
  ("from chatbot.vector_store import ..."), mientras que chatbot/main.py y
  chatbot/vector_store.py usan imports "planos" ("from vector_store import
  ..."), asumiendo que chatbot/ está directamente en sys.path. Son dos
  convenciones distintas que ya convivían en el repo antes de este archivo.
  Para no depender de cuál de las dos funciona según cómo se invoque pytest
  (`pytest` vs `python -m pytest`, desde la raíz del repo o no), este
  archivo NO importa `TEST_QUERY` desde chatbot/vector_ingest.py: la
  reproduce como literal (ver TEST_QUERY más abajo, copiada tal cual).
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

CHATBOT_DIR = Path(__file__).resolve().parent.parent
if str(CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(CHATBOT_DIR))

# Mismo patrón defensivo que el resto del proyecto: cargar .env por las
# dudas de que este archivo se corra sin pasar por conftest.py.
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# Pregunta de dominio ARCSA real, copiada tal cual de
# chatbot/vector_ingest.py::TEST_QUERY (ver nota de imports en el docstring
# de arriba sobre por qué se copia en vez de importarse).
TEST_QUERY = (
    "¿Qué requisitos debo cumplir para la Notificación Sanitaria Obligatoria "
    "de un dispositivo médico a través de la Ventanilla Única Ecuatoriana?"
)

# Pregunta totalmente ajena al dominio, usada como caso de calibración real
# de SIMILARITY_THRESHOLD en chatbot/main.py (ver el comentario extenso
# junto a esa constante: distancia del mejor vecino = 0.6470 para esta
# misma pregunta, bien por debajo del umbral 0.70).
OFF_TOPIC_QUERY = "Dame la receta de ceviche ecuatoriano"


# ---------------------------------------------------------------------------
# Gate de disponibilidad del pipeline real (Gemini + Pinecone + índice
# poblado). Se calcula una sola vez, en tiempo de import de este archivo, y
# decide si TODO el archivo se saltea o no (ver `pytestmark` más abajo).
# ---------------------------------------------------------------------------


def _probe_pipeline_readiness() -> tuple[bool, str]:
    """Chequea, sin nunca reventar ni hacer sys.exit, si el pipeline real
    (Gemini + Pinecone + índice ya poblado) está listo para estos tests."""
    if not GEMINI_API_KEY:
        return False, "Falta GEMINI_API_KEY real en el entorno/.env."

    if not PINECONE_API_KEY:
        return False, (
            "Falta PINECONE_API_KEY real en el entorno/.env (la migración de "
            "Vertex AI Vector Search a Pinecone ya está hecha en código, pero "
            "todavía no hay cuenta/API key de Pinecone real). Generá una key "
            "gratuita en https://app.pinecone.io/ y agregala a tu .env."
        )

    try:
        from vector_store import get_vector_store

        index = get_vector_store()
        stats = index.describe_index_stats()
        count = stats.get("total_vector_count", 0)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo real de conexión también implica "no listo"
        return False, f"No se pudo conectar al índice de Pinecone real: {exc!r}"

    if count == 0:
        return False, (
            "Índice de Pinecone vacío (0 vectores); correr "
            "`python -m chatbot.vector_ingest` primero para poblarlo."
        )

    return True, ""


_PIPELINE_READY, _SKIP_REASON = _probe_pipeline_readiness()

pytestmark = pytest.mark.skipif(not _PIPELINE_READY, reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Fixtures (todas perezosas: sólo se resuelven si pytestmark no saltea el
# test, ver nota en el docstring del archivo sobre por qué `import main` no
# puede vivir a nivel de módulo).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def main_module():
    """Importa chatbot/main.py (como módulo `main` a secas, ver docstring)
    de forma perezosa, recién cuando algún test que lo necesita corre de
    verdad."""
    import main as _main

    return _main


@pytest.fixture(scope="module")
def api_client(main_module):
    """TestClient real contra la app completa de chatbot/main.py (no un
    mini-FastAPI como el fixture `api` de conftest.py, que sólo monta los
    routers de auth/conversations)."""
    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as client:
        yield client


# ---------------------------------------------------------------------------
# 1. get_vector_store(): índice real y usable (query trivial sin reventar)
# ---------------------------------------------------------------------------


def test_get_vector_store_returns_usable_real_index():
    from vector_store import configure_embeddings, get_vector_store, normalize_embedding

    embed_model = configure_embeddings()
    index = get_vector_store()

    query_vector = normalize_embedding(embed_model.get_query_embedding(TEST_QUERY))
    response = index.query(vector=query_vector, top_k=1, include_metadata=False)

    assert response is not None
    assert hasattr(response, "matches")


# ---------------------------------------------------------------------------
# 2. configure_embeddings() + normalize_embedding(): 768 dims, norma ~= 1.0
# ---------------------------------------------------------------------------


def test_configure_embeddings_and_normalize_embedding_produce_unit_vector():
    from vector_store import EMBED_DIMENSIONS, configure_embeddings, normalize_embedding

    embed_model = configure_embeddings()
    raw_vector = embed_model.get_text_embedding("Notificación Sanitaria Obligatoria ARCSA")
    vector = normalize_embedding(raw_vector)

    assert len(vector) == EMBED_DIMENSIONS == 768

    norm = math.sqrt(sum(x * x for x in vector))
    assert norm == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 3. retrieve_chunks(): resultados reales y coherentes, con texto ya
#    resuelto vía el docstore local (no sólo IDs crudos de Pinecone)
# ---------------------------------------------------------------------------


def test_retrieve_chunks_returns_real_results_with_resolved_text(main_module):
    results = main_module.retrieve_chunks(TEST_QUERY, top_k=main_module.TOP_K)

    assert results, "retrieve_chunks() no devolvió ningún resultado para una pregunta real de dominio ARCSA."

    for chunk in results:
        assert chunk["text"].strip(), (
            f"Chunk {chunk['id']!r} resuelto sin texto: el índice devolvió el id pero el "
            "docstore local (chatbot/data/vector_docstore.json) no lo resolvió a texto real."
        )
        assert isinstance(chunk["distance"], float)


# ---------------------------------------------------------------------------
# 4. E2E real: POST /api/chat con una pregunta real de ARCSA
# ---------------------------------------------------------------------------


def test_chat_endpoint_e2e_real_arcsa_question_returns_answer_and_sources(api_client):
    response = api_client.post("/api/chat", json={"message": TEST_QUERY})

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["text"].strip()
    assert len(body["sources"]) >= 1
    for source in body["sources"]:
        assert source["documentTitle"]
        assert source["officialUrl"]


# ---------------------------------------------------------------------------
# 5. Pregunta totalmente ajena al dominio -> isLowConfidence=True
#    (caso de calibración real de SIMILARITY_THRESHOLD, ver chatbot/main.py)
# ---------------------------------------------------------------------------


def test_chat_endpoint_off_topic_question_is_low_confidence(api_client):
    response = api_client.post("/api/chat", json={"message": OFF_TOPIC_QUERY})

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["isLowConfidence"] is True
