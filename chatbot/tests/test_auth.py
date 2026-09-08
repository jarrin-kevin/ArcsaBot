"""
test_auth.py
Suite de tests automatizados para chatbot/auth.py:

    POST /api/auth/signup
    POST /api/auth/login
    GET  /api/auth/me
    POST /api/auth/logout

Corre contra una base SQLite temporal por test (fixture `api` en
conftest.py) — nunca toca chatbot/data/users.db real.
"""

from __future__ import annotations

import pytest

from conftest import ApiTestContext, RegisteredUser


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# signup
# ---------------------------------------------------------------------------


def test_signup_success_returns_user_and_token(api: ApiTestContext):
    response = api.client.post(
        "/api/auth/signup", json={"email": "nueva@example.com", "password": "secreto123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "nueva@example.com"
    assert isinstance(body["user"]["id"], int)
    assert body["token"]
    # La respuesta no debe filtrar el hash de la contraseña.
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_signup_duplicate_email_returns_409(api: ApiTestContext):
    first = api.client.post(
        "/api/auth/signup", json={"email": "dup@example.com", "password": "secreto123"}
    )
    assert first.status_code == 200

    response = api.client.post(
        "/api/auth/signup", json={"email": "dup@example.com", "password": "otraClave99"}
    )

    assert response.status_code == 409
    assert "error" in response.json()


def test_signup_duplicate_email_is_case_insensitive(api: ApiTestContext):
    """auth.py normaliza el email con .strip().lower() antes de guardarlo/
    buscarlo; un signup con mayúsculas distintas debe seguir contando como
    duplicado."""
    api.client.post("/api/auth/signup", json={"email": "MAYUS@example.com", "password": "secreto123"})

    response = api.client.post(
        "/api/auth/signup", json={"email": "mayus@example.com", "password": "otraClave99"}
    )

    assert response.status_code == 409


def test_signup_password_too_short_returns_400(api: ApiTestContext):
    response = api.client.post(
        "/api/auth/signup", json={"email": "corta@example.com", "password": "abc12"}
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_signup_email_too_long_returns_400(api: ApiTestContext):
    huge_email = "a" * 250 + "@example.com"  # > MAX_EMAIL_LENGTH (254)

    response = api.client.post(
        "/api/auth/signup", json={"email": huge_email, "password": "secreto123"}
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_concurrent_signups_same_email_one_wins_rest_get_409_not_500(api: ApiTestContext):
    """Regresión de un bug real encontrado con fuzzing: _find_user_by_email()
    y _create_user() en auth.py no son atómicos entre sí, así que dos signups
    concurrentes para el mismo email pueden pasar ambos el chequeo previo
    antes de que cualquiera inserte. El UNIQUE de la tabla evita el
    duplicado, pero antes del fix el perdedor de la carrera recibía un 500
    crudo (sqlite3.IntegrityError sin capturar) en vez de un 409 consistente.
    Dispara exactamente RATE_LIMIT_MAX_ATTEMPTS requests concurrentes para no
    chocar con el rate limiter del propio endpoint."""
    import threading

    email = "carrera@example.com"
    max_concurrent = api.auth.RATE_LIMIT_MAX_ATTEMPTS
    results: list[int] = []
    lock = threading.Lock()

    def _signup_attempt():
        response = api.client.post(
            "/api/auth/signup", json={"email": email, "password": "secreto123"}
        )
        with lock:
            results.append(response.status_code)

    threads = [threading.Thread(target=_signup_attempt) for _ in range(max_concurrent)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 1, f"Esperaba exactamente un 200 (ganador), obtuve: {results}"
    assert results.count(409) == max_concurrent - 1, f"Esperaba el resto en 409, obtuve: {results}"
    assert 500 not in results


def test_signup_malformed_email_returns_400(api: ApiTestContext):
    response = api.client.post(
        "/api/auth/signup", json={"email": "no-es-un-email", "password": "secreto123"}
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_signup_password_longer_than_72_bytes_should_be_rejected_gracefully(api: ApiTestContext):
    long_password = "a" * 100  # 100 bytes ASCII, supera el límite de 72 de bcrypt

    response = api.client.post(
        "/api/auth/signup",
        json={"email": "password-larga@example.com", "password": long_password},
    )

    assert response.status_code == 400
    assert "error" in response.json()


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_success(api: ApiTestContext):
    api.client.post("/api/auth/signup", json={"email": "login@example.com", "password": "secreto123"})

    response = api.client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "secreto123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "login@example.com"
    assert body["token"]


def test_login_wrong_password_returns_401(api: ApiTestContext):
    api.client.post(
        "/api/auth/signup", json={"email": "wrongpw@example.com", "password": "secreto123"}
    )

    response = api.client.post(
        "/api/auth/login", json={"email": "wrongpw@example.com", "password": "otraClave"}
    )

    assert response.status_code == 401
    assert "error" in response.json()


def test_login_nonexistent_email_returns_401(api: ApiTestContext):
    response = api.client.post(
        "/api/auth/login", json={"email": "no-existe@example.com", "password": "cualquiera1"}
    )

    assert response.status_code == 401
    assert "error" in response.json()


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


def test_me_with_valid_token_returns_current_user(api: ApiTestContext):
    signup_response = api.client.post(
        "/api/auth/signup", json={"email": "me@example.com", "password": "secreto123"}
    )
    token = signup_response.json()["token"]

    response = api.client.get("/api/auth/me", headers=_auth_headers(token))

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "me@example.com"


def test_me_without_authorization_header_returns_401(api: ApiTestContext):
    response = api.client.get("/api/auth/me")

    assert response.status_code == 401


def test_me_with_garbage_token_returns_401(api: ApiTestContext):
    response = api.client.get(
        "/api/auth/me", headers=_auth_headers("esto-no-es-un-token-valido")
    )

    assert response.status_code == 401


def test_me_with_another_users_token_returns_that_same_user_not_crossed(
    api: ApiTestContext, user_a: RegisteredUser, user_b: RegisteredUser
):
    """Confirma que /me nunca cruza usuarios: el token de A siempre debe
    resolver al usuario A, y el de B siempre al B, nunca al revés."""
    response_a = api.client.get("/api/auth/me", headers=_auth_headers(user_a.token))
    response_b = api.client.get("/api/auth/me", headers=_auth_headers(user_b.token))

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    user_a_body = response_a.json()["user"]
    user_b_body = response_b.json()["user"]

    assert user_a_body["email"] == user_a.email
    assert user_a_body["id"] == user_a.id
    assert user_b_body["email"] == user_b.email
    assert user_b_body["id"] == user_b.id
    assert user_a_body["id"] != user_b_body["id"]


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------


def test_logout_returns_ok(api: ApiTestContext):
    response = api.client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
