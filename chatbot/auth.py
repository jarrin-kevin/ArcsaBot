"""
auth.py
Autenticación real del chatbot ARCSA (FastAPI).

Reemplaza el mock 100% client-side que tenía antes
frontend/src/context/AuthContext.jsx (setTimeout + localStorage, sin request
al backend). Expone un APIRouter con los endpoints:

  - POST /api/auth/signup
  - POST /api/auth/login
  - GET  /api/auth/me
  - POST /api/auth/logout

que chatbot/main.py incluye en la app principal (comparte ahí mismo el CORS
ya configurado, no se duplica nada acá).

Diseño (deliberadamente simple, proporcional al tamaño del proyecto — no es
un sistema enterprise):
  - Usuarios: SQLite local en chatbot/data/users.db, con sqlite3 de la
    stdlib (sin ORM), siguiendo la misma convención de archivo local bajo
    chatbot/data/ que ya usa chatbot/data/vector_docstore.json.
  - Contraseñas: hasheadas con bcrypt (salt aleatorio por hash, nunca texto
    plano ni un hash sin salt).
  - Sesión: token firmado con itsdangerous.URLSafeTimedSerializer (HMAC-SHA256
    por debajo) que codifica sólo el user id; la expiración (7 días) se
    valida al leer el token, no queda embebida en su contenido.

NOTA sobre 'logout': no existe una lista de revocación de tokens (ver arriba),
así que POST /api/auth/logout es un no-op del lado servidor: sólo confirma
200 para que el frontend pueda limpiar su propio localStorage. Si más
adelante hiciera falta poder invalidar una sesión antes de que expire sola,
habría que agregar una tabla de tokens revocados.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from dotenv import load_dotenv
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

# Cargar variables de entorno desde un archivo .env si existe (mismo patrón
# defensivo que chatbot/main.py y chatbot/vector_store.py: cada módulo que
# necesita variables de entorno llama a load_dotenv() por su cuenta).
load_dotenv()

logger = logging.getLogger("chatbot.auth")

CHATBOT_DIR = Path(__file__).resolve().parent
# Configurable vía CHATBOT_DB_PATH (usado por la suite de tests en
# chatbot/tests/ para apuntar a una base SQLite temporal por test y así
# nunca tocar chatbot/data/users.db real); sin esa variable de entorno el
# comportamiento en producción es idéntico al de antes.
DB_PATH = Path(os.getenv("CHATBOT_DB_PATH", str(CHATBOT_DIR / "data" / "users.db")))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 6
# bcrypt.hashpw() rechaza con ValueError cualquier password de más de 72 bytes
# UTF-8 (límite propio del algoritmo) — sin este chequeo, una password larga
# pero razonable (p. ej. una passphrase) rompía /signup con un 500 sin manejar.
MAX_PASSWORD_BYTES = 72
# RFC 5321 fija 254 caracteres como el máximo práctico de una dirección de
# email completa; sin este límite, `_validate_credentials()` aceptaba
# emails de miles de caracteres sin ningún tope (encontrado con fuzzing).
MAX_EMAIL_LENGTH = 254
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 días

# ---------------------------------------------------------------------------
# Configuración de la firma de tokens de sesión
# ---------------------------------------------------------------------------

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY")
if not AUTH_SECRET_KEY:
    logger.error("La variable de entorno AUTH_SECRET_KEY no está configurada.")
    logger.error("Por favor, agrégala a tu archivo .env antes de continuar.")
    raise SystemExit(1)

# "salt" acá es el parámetro de dominio de itsdangerous (mezclado en la firma
# para separar este uso de cualquier otro que reutilice la misma
# AUTH_SECRET_KEY), no tiene relación con el salt de bcrypt de más abajo.
_serializer = URLSafeTimedSerializer(AUTH_SECRET_KEY, salt="arcsa-chatbot-auth")


# ---------------------------------------------------------------------------
# Base de datos de usuarios (SQLite local, sin ORM — ver docstring del módulo)
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


_init_db()


def _find_user_by_email(email: str) -> sqlite3.Row | None:
    with _get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def _find_user_by_id(user_id: int) -> sqlite3.Row | None:
    with _get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _create_user(email: str, password: str) -> sqlite3.Row | None:
    """Crea el usuario, o devuelve None si el email ya existe.

    El chequeo previo de _find_user_by_email() en signup() no es atómico con
    este INSERT: dos signups concurrentes para el mismo email pueden pasar
    ambos ese chequeo antes de que cualquiera inserte. El UNIQUE de la tabla
    igual evita el duplicado, pero sin capturar este error acá el request
    perdedor de la carrera reventaba con un 500 crudo en vez del mismo 409
    que ya se usa para el caso no-concurrente.
    """
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, created_at),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    return _find_user_by_id(user_id)


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _user_to_dict(user: sqlite3.Row) -> dict:
    return {"id": user["id"], "email": user["email"]}


# ---------------------------------------------------------------------------
# Tokens de sesión firmados (HMAC-SHA256 vía itsdangerous)
# ---------------------------------------------------------------------------


def _issue_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def _decode_token(token: str) -> int | None:
    """Devuelve el user_id si el token es válido y no expiró; None si no."""
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def get_user_from_token(token: str) -> sqlite3.Row | None:
    """Resuelve un token de sesión a su usuario real; None si el token es
    inválido/expiró o el usuario ya no existe. Se expone (no sólo se usa
    internamente en /me) para que, si en el futuro otro endpoint necesita
    requerir sesión, reutilice esta misma validación en vez de duplicarla."""
    user_id = _decode_token(token)
    if user_id is None:
        return None
    return _find_user_by_id(user_id)


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer ") :].strip() or None


# ---------------------------------------------------------------------------
# Rate limiting (en memoria, por IP) para /signup y /login
# ---------------------------------------------------------------------------
# Ventana fija simple, alcanza para el tamaño de este proyecto (un solo
# proceso). Si en algún momento corre con múltiples workers/instancias, esto
# habría que moverlo a un store compartido (Redis, etc.) — cada proceso
# llevaría su propio conteo y el límite real efectivo sería
# RATE_LIMIT_MAX_ATTEMPTS * cantidad_de_workers.
_rate_limit_attempts: dict[str, list[float]] = {}
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60


def _check_rate_limit(request: Request) -> JSONResponse | None:
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _rate_limit_attempts.setdefault(client_ip, [])
    attempts[:] = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        return JSONResponse(
            status_code=429,
            content={"error": "Demasiados intentos. Esperá un minuto e intentá de nuevo."},
        )
    attempts.append(now)
    return None


# Hash bcrypt precomputado de una password fija, usado únicamente para que
# login() tarde lo mismo cuando el email NO existe que cuando existe pero la
# password es incorrecta — sin esto, el cortocircuito de `user is None`
# devuelve 401 casi instantáneo mientras que un email real fuerza un
# bcrypt.checkpw() real (~100ms), permitiendo enumerar cuentas por timing.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"dummy-password-para-timing-constante", bcrypt.gensalt())


def _validate_credentials(email: str, password: str) -> str | None:
    """Devuelve un mensaje de error si el formato es inválido, o None si está bien.
    Mismas reglas mínimas que validaba el mock del frontend: email con forma
    válida y contraseña de al menos MIN_PASSWORD_LENGTH caracteres."""
    if not EMAIL_RE.match(email):
        return "El formato del correo electrónico no es válido."
    if len(email) > MAX_EMAIL_LENGTH:
        return f"El correo electrónico no puede superar los {MAX_EMAIL_LENGTH} caracteres."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"La contraseña no puede superar los {MAX_PASSWORD_BYTES} bytes."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
    return None


# ---------------------------------------------------------------------------
# API HTTP (FastAPI router)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@router.post("/signup")
def signup(payload: SignupRequest, request: Request):
    rate_limit_error = _check_rate_limit(request)
    if rate_limit_error:
        return rate_limit_error

    email = payload.email.strip().lower()
    error = _validate_credentials(email, payload.password)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    if _find_user_by_email(email) is not None:
        return JSONResponse(
            status_code=409, content={"error": "Ya existe una cuenta registrada con ese correo."}
        )

    user = _create_user(email, payload.password)
    if user is None:
        # Perdió la carrera contra otro signup concurrente para el mismo
        # email (ver docstring de _create_user) — mismo 409 que el chequeo
        # de arriba, no un 500.
        return JSONResponse(
            status_code=409, content={"error": "Ya existe una cuenta registrada con ese correo."}
        )

    token = _issue_token(user["id"])
    logger.info(f"Nuevo usuario registrado: {email!r}")
    return {"user": _user_to_dict(user), "token": token}


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    rate_limit_error = _check_rate_limit(request)
    if rate_limit_error:
        return rate_limit_error

    email = payload.email.strip().lower()
    user = _find_user_by_email(email)
    if user is None:
        # Corre un bcrypt.checkpw() real igual (contra un hash dummy) para
        # que esta rama tarde lo mismo que la de abajo — ver _DUMMY_PASSWORD_HASH.
        bcrypt.checkpw(payload.password.encode("utf-8"), _DUMMY_PASSWORD_HASH)
        return JSONResponse(status_code=401, content={"error": "Correo o contraseña incorrectos."})
    if not _verify_password(payload.password, user["password_hash"]):
        return JSONResponse(status_code=401, content={"error": "Correo o contraseña incorrectos."})

    token = _issue_token(user["id"])
    return {"user": _user_to_dict(user), "token": token}


@router.get("/me")
def me(authorization: str | None = Header(default=None)):
    token = _extract_bearer_token(authorization)
    if token is None:
        return JSONResponse(status_code=401, content={"error": "Falta el header Authorization."})

    user = get_user_from_token(token)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "Token inválido o expirado."})

    return {"user": _user_to_dict(user)}


@router.post("/logout")
def logout():
    # No hay lista de revocación de tokens (ver docstring del módulo): este
    # endpoint es un no-op del lado servidor, sólo confirma 200 para que el
    # frontend pueda limpiar su propio estado local.
    return {"ok": True}
