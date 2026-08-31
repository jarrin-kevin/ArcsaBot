import os
from dotenv import load_dotenv
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.core import Settings

# Cargar variables de entorno desde un archivo .env si existe
load_dotenv()

# Verificar que la clave de API esté configurada
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("[ERROR] La variable de entorno GEMINI_API_KEY no está configurada.")
    print("Por favor, crea un archivo .env o configúrala en tu entorno de ejecución.")
    exit(1)

print("Inicializando el modelo Gemini LLM...")

# Configurar Gemini (gemini-3.5-flash-lite) como el LLM por defecto en LlamaIndex
llm = GoogleGenAI(model="gemini-3.5-flash-lite", api_key=api_key)
Settings.llm = llm

# Opcional: Configurar embeddings de Google GenAI
# from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
# Settings.embed_model = GoogleGenAIEmbedding(model_name="models/text-embedding-004", api_key=api_key)

print("Enviando una consulta de prueba a Gemini...")
try:
    response = llm.complete("Hola Gemini. Confirma en una sola frase corta que estás conectado y funcionando correctamente con LlamaIndex.")
    print("\nRespuesta de Gemini:")
    print("=" * 60)
    print(response.text)
    print("=" * 60)
    print("¡Verificación exitosa!")
except Exception as e:
    print(f"\n[ERROR] Ocurrió un error al comunicarse con la API de Gemini: {e}")
