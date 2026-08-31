import os
from dotenv import load_dotenv
from llama_index.core import Settings
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
from llama_index.vector_stores.vertexaivectorsearch import VertexAIVectorStore

# Cargar variables de entorno desde un archivo .env si existe
load_dotenv()

# Variables de entorno requeridas para Vertex AI Vector Search
REQUIRED_ENV_VARS = [
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "VERTEX_INDEX_ID",
    "VERTEX_INDEX_ENDPOINT_ID",
    "GCS_BUCKET_NAME",
]


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

    # Configurar Gemini (text-embedding-004) como el modelo de embeddings por defecto en LlamaIndex
    embed_model = GoogleGenAIEmbedding(model_name="models/text-embedding-004", api_key=api_key)
    Settings.embed_model = embed_model

    return embed_model


def get_vector_store() -> VertexAIVectorStore:
    """Crea y retorna una instancia configurada de VertexAIVectorStore para usar con StorageContext."""
    env = _get_required_env_vars()

    print("Inicializando el vector store de Vertex AI Vector Search...")

    vector_store = VertexAIVectorStore(
        project_id=env["GOOGLE_CLOUD_PROJECT"],
        region=env["GOOGLE_CLOUD_LOCATION"],
        index_id=env["VERTEX_INDEX_ID"],
        endpoint_id=env["VERTEX_INDEX_ENDPOINT_ID"],
        gcs_bucket_name=env["GCS_BUCKET_NAME"],
    )

    return vector_store
