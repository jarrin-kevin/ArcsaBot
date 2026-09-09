import math
import os
import time

from dotenv import load_dotenv
from google.genai import types
from llama_index.core import Settings
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
from pinecone import Pinecone, ServerlessSpec

# Cargar variables de entorno desde un archivo .env si existe
load_dotenv()

# Variables de entorno requeridas para Pinecone
REQUIRED_ENV_VARS = [
    "PINECONE_API_KEY",
]

# "models/text-embedding-004" ya no existe para esta cuenta de la Gemini API
# (404 NOT_FOUND); se usa gemini-embedding-001 truncado a 768 dimensiones. El
# índice de Pinecone se crea con esa misma dimensión fija (ver get_vector_store()).
EMBED_MODEL_NAME = "models/gemini-embedding-001"
EMBED_DIMENSIONS = 768

# Nombre fijo del índice de Pinecone (no hace falta que sea configurable: este
# proyecto usa un único índice). Región fija en us-east-1/aws porque es la
# única región soportada por el plan Starter (gratuito) de Pinecone.
PINECONE_INDEX_NAME = "arcsa-rag-index"
PINECONE_CLOUD = "aws"
PINECONE_REGION = "us-east-1"


def _get_required_env_vars() -> dict:
    """Lee y valida las variables de entorno requeridas, fallando rápido si falta alguna."""
    valores = {nombre: os.getenv(nombre) for nombre in REQUIRED_ENV_VARS}
    faltantes = [nombre for nombre, valor in valores.items() if not valor]

    if faltantes:
        print(f"[ERROR] Faltan variables de entorno requeridas: {', '.join(faltantes)}")
        print("Por favor, configúralas en tu archivo .env antes de continuar.")
        exit(1)

    return valores


def configure_embeddings() -> GoogleGenAIEmbedding:
    """Configura el modelo de embeddings de Google GenAI como el modelo por defecto en LlamaIndex."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] La variable de entorno GEMINI_API_KEY no está configurada.")
        print("Por favor, crea un archivo .env o configúrala en tu entorno de ejecución.")
        exit(1)

    print("Inicializando el modelo de embeddings de Google GenAI...")

    # Configurar gemini-embedding-001 (output_dimensionality=768) como el
    # modelo de embeddings por defecto en LlamaIndex.
    embed_model = GoogleGenAIEmbedding(
        model_name=EMBED_MODEL_NAME,
        api_key=api_key,
        embedding_config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMENSIONS),
    )
    Settings.embed_model = embed_model

    return embed_model


def normalize_embedding(vector: list[float]) -> list[float]:
    """Normaliza un embedding a norma 1: con output_dimensionality=768,
    gemini-embedding-001 no devuelve vectores unitarios."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def get_pinecone_client() -> Pinecone:
    """Crea el cliente de Pinecone a partir de PINECONE_API_KEY."""
    env = _get_required_env_vars()
    return Pinecone(api_key=env["PINECONE_API_KEY"])


def get_vector_store():
    """Crea (si no existe) y retorna el índice de Pinecone, listo para
    upsert()/query()."""
    pc = get_pinecone_client()

    if not pc.has_index(name=PINECONE_INDEX_NAME):
        print(f"Creando índice de Pinecone '{PINECONE_INDEX_NAME}' (dimension={EMBED_DIMENSIONS})...")
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=EMBED_DIMENSIONS,
            metric="cosine",
            spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
        )
        # create_index() es asíncrono del lado de Pinecone; hay que esperar a
        # que el índice quede listo antes de poder usarlo (upsert/query).
        while not pc.describe_index(PINECONE_INDEX_NAME).status["ready"]:
            time.sleep(1)

    return pc.Index(PINECONE_INDEX_NAME)
