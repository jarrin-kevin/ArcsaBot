"""
conftest.py
Fixtures compartidas para la suite de tests de chatbot/auth.py y
chatbot/conversations.py.

Por qué existe este archivo (y no basta con `from auth import router`
directo en cada test):
-----------------------------------------------------------------------
chatbot/auth.py y chatbot/conversations.py inicializan su propia conexión
SQLite (chatbot/data/users.db en producción) apenas se importan, vía
`_init_db()` a nivel de módulo. Para que la suite NUNCA toque esa base de
datos real:

  1. Este archivo agrega chatbot/ a sys.path (igual que hace chatbot/main.py
     al hacer `from auth import router as auth_router`: asume que chatbot/
     está en el path, no que es un paquete) y fija AUTH_SECRET_KEY *antes*
     de que nada importe auth.py — si falta esa variable, auth.py hace
     `raise SystemExit(1)` al importarse (ver chatbot/auth.py). Un valor fijo
     de test evita depender de si hay o no un .env real con secretos de
     producción.
  2. El fixture `api` (más abajo) fija la variable de entorno
     CHATBOT_DB_PATH — que tanto auth.py como conversations.py leen para
     resolver su DB_PATH, ver el comentario junto a esa línea en ambos
     módulos — a un archivo SQLite nuevo y temporal (vía `tmp_path`, uno
     distinto por test), y fuerza un `importlib.reload()` de ambos módulos
     para que `_init_db()` se re-ejecute contra esa ruta temporal en vez de
     la de producción.

IMPORTANTE para quien agregue tests nuevos: nunca hagas
`import auth` / `import conversations` a nivel de módulo en un archivo
test_*.py. Eso los importaría por primera vez (con su DB_PATH de
producción) antes de que el fixture `api` llegue a fijar CHATBOT_DB_PATH.
Usá siempre el fixture `api` (o `user_a` / `user_b`, que dependen de él).
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CHATBOT_DIR = Path(__file__).resolve().parent.parent
if str(CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(CHATBOT_DIR))

# Debe fijarse antes del primer `import auth` de todo el proceso de test.
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-only-for-pytest")


@dataclass
class ApiTestContext:
    client: TestClient
    db_path: Path
    auth: object
    conversations: object


@dataclass
class RegisteredUser:
    email: str
    password: str
    token: str
    id: int


@pytest.fixture()
def api(tmp_path, monkeypatch) -> ApiTestContext:
    """App de test aislada, con SOLO los routers de auth/conversations
    (no chatbot/main.py completo: ese módulo además requiere GEMINI_API_KEY
    sólo para poder importarse, y PINECONE_API_KEY en tiempo de request real
    para consultar el índice vectorial (Pinecone, ver chatbot/vector_store.py)
    — nada de esto tiene que ver con lo que se está probando acá), corriendo
    contra una base SQLite temporal nueva en cada test.
    """
    db_path = tmp_path / "test_users.db"
    monkeypatch.setenv("CHATBOT_DB_PATH", str(db_path))

    import auth
    import conversations

    # Re-ejecuta _init_db() de cada módulo contra la ruta temporal recién
    # fijada arriba (ver docstring del archivo).
    importlib.reload(auth)
    importlib.reload(conversations)

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(conversations.router)

    with TestClient(app) as client:
        yield ApiTestContext(client=client, db_path=db_path, auth=auth, conversations=conversations)


def _signup(api_context: ApiTestContext, email: str, password: str = "Password123") -> RegisteredUser:
    response = api_context.client.post("/api/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return RegisteredUser(email=email, password=password, token=body["token"], id=body["user"]["id"])


@pytest.fixture()
def user_a(api: ApiTestContext) -> RegisteredUser:
    """Primer usuario de test ya registrado, sobre la misma base temporal
    que el fixture `api` de este mismo test."""
    return _signup(api, "user.a@example.com")


@pytest.fixture()
def user_b(api: ApiTestContext) -> RegisteredUser:
    """Segundo usuario de test, para los casos de aislamiento entre
    usuarios (conversaciones ajenas, tokens cruzados, etc.)."""
    return _signup(api, "user.b@example.com")


def raw_db_connection(api_context: ApiTestContext) -> sqlite3.Connection:
    """Conexión directa a la base temporal del test, para asserts a nivel de
    fila que la API HTTP no expone (p. ej. confirmar el cascade delete)."""
    return sqlite3.connect(api_context.db_path)
