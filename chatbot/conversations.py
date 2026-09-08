"""
conversations.py
Persistencia real del historial de conversaciones del chatbot ARCSA (FastAPI).

Reemplaza el historial 100% client-side que tenía antes
frontend/src/services/transport/ChatStore.js (sessionStorage del navegador,
sin backend real, ver los TODOs "[TEMPORAL - FRONTEND F5]" que este módulo
resuelve). Expone un APIRouter con los endpoints:

  - GET    /api/conversations                 (lista las del usuario actual)
  - POST   /api/conversations                 (crea una conversación nueva)
  - GET    /api/conversations/{id}            (conversación + sus mensajes)
  - POST   /api/conversations/{id}/messages   (agrega un mensaje)
  - DELETE /api/conversations/{id}            (borra la conversación)

que chatbot/main.py incluye en la app principal, igual que auth_router.

Diseño (deliberadamente simple, proporcional al tamaño del proyecto — no es
un sistema enterprise, mismo espíritu que chatbot/auth.py):
  - Mismo archivo SQLite que auth.py: chatbot/data/users.db, con sqlite3 de
    la stdlib (sin ORM). Se agregan 2 tablas nuevas (conversations, messages)
    al lado de la tabla users ya existente.
  - Cada conversación pertenece a un user_id (FK -> users.id). Los mensajes
    pertenecen a una conversation_id (FK -> conversations.id), con
    ON DELETE CASCADE en ambos niveles: borrar una conversación borra sus
    mensajes; si algún día se borrara un usuario, se llevaría sus
    conversaciones (y con ellas sus mensajes) automáticamente. SQLite no
    aplica FKs por defecto: hace falta `PRAGMA foreign_keys = ON` en cada
    conexión (ver _get_connection()).
  - Autenticación: mismo esquema que el resto de la API — todos los
    endpoints requieren `Authorization: Bearer <token>` y reutilizan
    get_user_from_token() de chatbot/auth.py tal cual (no se duplica la
    validación de tokens). 401 si falta o es inválido.
  - Aislamiento entre usuarios: toda consulta de una conversación puntual
    (GET/POST mensajes/DELETE) filtra siempre por `user_id = ?` además de
    `id = ?`. Si el id existe pero es de otro usuario, se responde 404 (no
    403): no se revela si el recurso existe pero pertenece a otra persona.
  - `sources` (fuentes RAG citadas) y `metadata` (p. ej. isLowConfidence,
    officialUrl, reasoning) de cada mensaje se guardan serializados como JSON
    en columnas TEXT — no hace falta un esquema relacional más fino para el
    tamaño de este proyecto, y así el shape va y viene sin transformación
    especial entre frontend y backend (frontend/src/services/transport/
    uiMessages.js ya trabaja con "parts" tipados en ese mismo espíritu).
  - Sólo se persisten mensajes reales (no placeholders "sending"/"error" del
    frontend): ChatStore.js decide cuándo llamar a POST .../messages, ver
    ese archivo para el detalle de cuándo persiste el mensaje de usuario vs.
    el de asistente.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Header
from fastapi import Path as FastApiPath
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import get_user_from_token

# Cargar variables de entorno desde un archivo .env si existe (mismo patrón
# defensivo que chatbot/auth.py y chatbot/main.py).
load_dotenv()

logger = logging.getLogger("chatbot.conversations")

CHATBOT_DIR = Path(__file__).resolve().parent
# Configurable vía CHATBOT_DB_PATH (mismo mecanismo que chatbot/auth.py, ver
# su comentario; ambos módulos comparten el mismo archivo SQLite en
# producción y deben apuntar a la misma ruta temporal durante los tests).
DB_PATH = Path(os.getenv("CHATBOT_DB_PATH", str(CHATBOT_DIR / "data" / "users.db")))

DEFAULT_TITLE = "Nueva conversación"

# SQLite INTEGER es de 64 bits con signo; un id fuera de ese rango (p. ej.
# .../api/conversations/999999999999999999999) hacía que sqlite3 tirara
# OverflowError sin capturar (encontrado con fuzzing) porque FastAPI/Pydantic
# no le ponen techo a `int` por sí solos. Estos límites lo cortan en la capa
# de FastAPI (422 prolijo) antes de llegar a la query.
SQLITE_MAX_INT = 2**63 - 1


# ---------------------------------------------------------------------------
# Base de datos (mismo archivo SQLite que chatbot/auth.py, 2 tablas nuevas)
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # SQLite no aplica foreign keys por defecto; hace falta activarlo por
    # conexión para que ON DELETE CASCADE (ver _init_db) realmente funcione.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            )
            """
        )


_init_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_owned_conversation(conn: sqlite3.Connection, conversation_id: int, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()


def _conversation_summary_to_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "title": row["title"], "updatedAt": row["updated_at"]}


def _message_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "sources": json.loads(row["sources"]) if row["sources"] else None,
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
        "createdAt": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Autenticación (mismo patrón que chatbot/auth.py: Bearer token en el header
# Authorization, resuelto vía get_user_from_token()).
# ---------------------------------------------------------------------------


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer ") :].strip() or None


def _authenticate(authorization: str | None) -> sqlite3.Row | None:
    token = _extract_bearer_token(authorization)
    if token is None:
        return None
    return get_user_from_token(token)


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"error": "Sesión inválida o expirada."})


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "Conversación no encontrada."})


# ---------------------------------------------------------------------------
# API HTTP (FastAPI router)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str | None = None


class CreateMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)
    sources: list[dict] | None = None
    metadata: dict | None = None


@router.get("")
def list_conversations(authorization: str | None = Header(default=None)):
    user = _authenticate(authorization)
    if user is None:
        return _unauthorized()

    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()

    return {"conversations": [_conversation_summary_to_dict(row) for row in rows]}


@router.post("")
def create_conversation(
    payload: CreateConversationRequest, authorization: str | None = Header(default=None)
):
    user = _authenticate(authorization)
    if user is None:
        return _unauthorized()

    title = (payload.title or "").strip() or DEFAULT_TITLE
    now = _now()
    with _get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user["id"], title, now, now),
        )
        conversation_id = cursor.lastrowid

    return {"id": conversation_id, "title": title, "createdAt": now, "updatedAt": now}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: int = FastApiPath(..., ge=1, le=SQLITE_MAX_INT),
    authorization: str | None = Header(default=None),
):
    user = _authenticate(authorization)
    if user is None:
        return _unauthorized()

    with _get_connection() as conn:
        conversation = _find_owned_conversation(conn, conversation_id, user["id"])
        if conversation is None:
            return _not_found()

        message_rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "createdAt": conversation["created_at"],
        "updatedAt": conversation["updated_at"],
        "messages": [_message_to_dict(row) for row in message_rows],
    }


@router.post("/{conversation_id}/messages")
def add_message(
    payload: CreateMessageRequest,
    conversation_id: int = FastApiPath(..., ge=1, le=SQLITE_MAX_INT),
    authorization: str | None = Header(default=None),
):
    user = _authenticate(authorization)
    if user is None:
        return _unauthorized()

    now = _now()
    with _get_connection() as conn:
        conversation = _find_owned_conversation(conn, conversation_id, user["id"])
        if conversation is None:
            return _not_found()

        sources_json = json.dumps(payload.sources) if payload.sources is not None else None
        metadata_json = json.dumps(payload.metadata) if payload.metadata is not None else None

        cursor = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, sources, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, payload.role, payload.content, sources_json, metadata_json, now),
        )
        message_id = cursor.lastrowid

        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))

    return {
        "id": message_id,
        "role": payload.role,
        "content": payload.content,
        "sources": payload.sources,
        "metadata": payload.metadata,
        "createdAt": now,
    }


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int = FastApiPath(..., ge=1, le=SQLITE_MAX_INT),
    authorization: str | None = Header(default=None),
):
    user = _authenticate(authorization)
    if user is None:
        return _unauthorized()

    with _get_connection() as conn:
        conversation = _find_owned_conversation(conn, conversation_id, user["id"])
        if conversation is None:
            return _not_found()

        # ON DELETE CASCADE (ver _init_db) borra también sus mensajes.
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    return {"ok": True}
