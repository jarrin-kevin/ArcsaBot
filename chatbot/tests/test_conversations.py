"""
test_conversations.py
Suite de tests automatizados para chatbot/conversations.py:

    GET    /api/conversations
    POST   /api/conversations
    GET    /api/conversations/{id}
    POST   /api/conversations/{id}/messages
    DELETE /api/conversations/{id}

Corre contra una base SQLite temporal por test (fixture `api` en
conftest.py, compartido con test_auth.py) — nunca toca
chatbot/data/users.db real. Los fixtures `user_a` / `user_b` dan dos
usuarios reales ya registrados sobre esa misma base temporal, usados en los
tests de aislamiento entre usuarios.
"""

from __future__ import annotations

from conftest import ApiTestContext, RegisteredUser, raw_db_connection


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_conversation(api: ApiTestContext, token: str, title: str | None = None) -> int:
    payload = {"title": title} if title is not None else {}
    response = api.client.post("/api/conversations", json=payload, headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# crear conversación
# ---------------------------------------------------------------------------


def test_create_conversation_without_token_returns_401(api: ApiTestContext):
    response = api.client.post("/api/conversations", json={})

    assert response.status_code == 401


def test_create_conversation_with_auth_returns_conversation(
    api: ApiTestContext, user_a: RegisteredUser
):
    response = api.client.post(
        "/api/conversations",
        json={"title": "Trámite de permiso"},
        headers=_auth_headers(user_a.token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Trámite de permiso"
    assert isinstance(body["id"], int)
    assert body["createdAt"] == body["updatedAt"]


def test_create_conversation_without_title_uses_default(api: ApiTestContext, user_a: RegisteredUser):
    response = api.client.post("/api/conversations", json={}, headers=_auth_headers(user_a.token))

    assert response.status_code == 200
    assert response.json()["title"] == "Nueva conversación"


# ---------------------------------------------------------------------------
# listar conversaciones (aislamiento entre usuarios)
# ---------------------------------------------------------------------------


def test_list_conversations_without_token_returns_401(api: ApiTestContext):
    response = api.client.get("/api/conversations")

    assert response.status_code == 401


def test_list_conversations_only_returns_own(
    api: ApiTestContext, user_a: RegisteredUser, user_b: RegisteredUser
):
    _create_conversation(api, user_a.token, "A1")
    _create_conversation(api, user_a.token, "A2")
    _create_conversation(api, user_b.token, "B1")

    response_a = api.client.get("/api/conversations", headers=_auth_headers(user_a.token))
    response_b = api.client.get("/api/conversations", headers=_auth_headers(user_b.token))

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    titles_a = {c["title"] for c in response_a.json()["conversations"]}
    titles_b = {c["title"] for c in response_b.json()["conversations"]}

    assert titles_a == {"A1", "A2"}
    assert titles_b == {"B1"}


# ---------------------------------------------------------------------------
# agregar mensajes
# ---------------------------------------------------------------------------


def test_add_message_with_sources_and_metadata(api: ApiTestContext, user_a: RegisteredUser):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={
            "role": "assistant",
            "content": "La tasa es de $50.",
            "sources": [{"id": "src-1", "documentTitle": "Resolución X"}],
            "metadata": {"isLowConfidence": False},
        },
        headers=_auth_headers(user_a.token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "assistant"
    assert body["content"] == "La tasa es de $50."
    assert body["sources"] == [{"id": "src-1", "documentTitle": "Resolución X"}]
    assert body["metadata"] == {"isLowConfidence": False}


def test_add_message_without_sources_and_metadata(api: ApiTestContext, user_a: RegisteredUser):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "¿Cuál es el plazo?"},
        headers=_auth_headers(user_a.token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] is None
    assert body["metadata"] is None


def test_add_message_to_other_users_conversation_returns_404(
    api: ApiTestContext, user_a: RegisteredUser, user_b: RegisteredUser
):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "intento ajeno"},
        headers=_auth_headers(user_b.token),
    )

    assert response.status_code == 404


def test_add_message_without_token_returns_401(api: ApiTestContext, user_a: RegisteredUser):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "sin token"},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# obtener conversación + mensajes en orden
# ---------------------------------------------------------------------------


def test_get_conversation_returns_messages_in_order(api: ApiTestContext, user_a: RegisteredUser):
    conversation_id = _create_conversation(api, user_a.token)

    contents = ["primero", "segundo", "tercero"]
    for content in contents:
        api.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"role": "user", "content": content},
            headers=_auth_headers(user_a.token),
        )

    response = api.client.get(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_a.token)
    )

    assert response.status_code == 200
    ordered_contents = [m["content"] for m in response.json()["messages"]]
    assert ordered_contents == contents


def test_get_other_users_conversation_returns_404_not_403(
    api: ApiTestContext, user_a: RegisteredUser, user_b: RegisteredUser
):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.get(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_b.token)
    )

    # Requisito explícito: una conversación ajena debe dar 404 (no se revela
    # que existe pero es de otro usuario), nunca 403.
    assert response.status_code == 404
    assert response.status_code != 403


def test_get_nonexistent_conversation_returns_404(api: ApiTestContext, user_a: RegisteredUser):
    response = api.client.get("/api/conversations/999999", headers=_auth_headers(user_a.token))

    assert response.status_code == 404


def test_conversation_id_larger_than_sqlite_int_returns_422_not_500(
    api: ApiTestContext, user_a: RegisteredUser
):
    """Regresión de un bug real encontrado con fuzzing: SQLite INTEGER es de
    64 bits con signo, pero FastAPI/Pydantic no le ponían techo al `int` del
    path param, así que un id fuera de ese rango llegaba a sqlite3 y tiraba
    un OverflowError sin capturar (500). Los tres endpoints con
    {conversation_id} en la ruta comparten el mismo Path(..., le=SQLITE_MAX_INT)."""
    huge_id = 2**63  # uno más que SQLITE_MAX_INT

    get_response = api.client.get(f"/api/conversations/{huge_id}", headers=_auth_headers(user_a.token))
    delete_response = api.client.delete(
        f"/api/conversations/{huge_id}", headers=_auth_headers(user_a.token)
    )
    message_response = api.client.post(
        f"/api/conversations/{huge_id}/messages",
        json={"role": "user", "content": "hola"},
        headers=_auth_headers(user_a.token),
    )

    assert get_response.status_code == 422
    assert delete_response.status_code == 422
    assert message_response.status_code == 422


# ---------------------------------------------------------------------------
# borrar conversación (+ cascade de mensajes)
# ---------------------------------------------------------------------------


def test_delete_other_users_conversation_returns_404_not_403(
    api: ApiTestContext, user_a: RegisteredUser, user_b: RegisteredUser
):
    conversation_id = _create_conversation(api, user_a.token)

    response = api.client.delete(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_b.token)
    )

    assert response.status_code == 404
    assert response.status_code != 403

    # El intento fallido de user_b no debió borrar nada: la conversación de
    # user_a debe seguir intacta.
    still_there = api.client.get(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_a.token)
    )
    assert still_there.status_code == 200


def test_delete_conversation_cascades_to_messages(api: ApiTestContext, user_a: RegisteredUser):
    conversation_id = _create_conversation(api, user_a.token)
    api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "hola"},
        headers=_auth_headers(user_a.token),
    )
    api.client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "assistant", "content": "hola, ¿en qué te ayudo?"},
        headers=_auth_headers(user_a.token),
    )

    delete_response = api.client.delete(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_a.token)
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}

    get_response = api.client.get(
        f"/api/conversations/{conversation_id}", headers=_auth_headers(user_a.token)
    )
    assert get_response.status_code == 404

    # Confirmación explícita del cascade a nivel de base de datos: no deben
    # quedar mensajes huérfanos apuntando a la conversación ya borrada.
    # sqlite3.Connection como context manager sólo maneja la transacción
    # (commit/rollback), no cierra la conexión — se cierra a mano para no
    # dejar el archivo temporal abierto en Windows.
    conn = raw_db_connection(api)
    try:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 0
