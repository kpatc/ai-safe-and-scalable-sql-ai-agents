from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_health_endpoint(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_endpoint_success(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.post("/v1/query", json={"question": "Liste les produits"})
    assert response.status_code == 200
    payload = response.json()
    assert "sql" in payload
    assert "row_count" in payload
    assert payload["sql"].upper().startswith("SELECT")


def test_query_empty_question_rejected(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.post("/v1/query", json={"question": ""})
    assert response.status_code == 422


def test_delete_session(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.delete("/v1/sessions/my-session-id")
    assert response.status_code == 204


def test_request_id_header_returned(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers.get("x-request-id") == "abc-123"


def test_query_with_session_id(client: object) -> None:
    from fastapi.testclient import TestClient
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from sql_ai_agent.agent.context import build_context
    from sql_ai_agent.agent.memory import InMemorySessionStore
    from sql_ai_agent.agent.sql_agent import SqlAgent

    assert isinstance(client, TestClient)

    # Replace agent with one that returns two different responses
    engine = client.app.state.engine
    schema = client.app.state.agent.schema
    settings = client.app.state.settings
    store = InMemorySessionStore()
    fake = FakeListChatModel(
        responses=[
            "```sql\nSELECT * FROM produits LIMIT 5\n```",
            "```sql\nSELECT * FROM clients LIMIT 5\n```",
        ]
    )
    ctx = build_context(schema=schema, engine=engine, skills="")
    client.app.state.agent = SqlAgent(
        chat_model=fake,
        engine=engine,
        schema=schema,
        settings=settings,
        context=ctx,
        session_store=store,
    )
    client.app.state.session_store = store

    r1 = client.post("/v1/query", json={"question": "Q1", "session_id": "sess-1"})
    assert r1.status_code == 200

    r2 = client.post("/v1/query", json={"question": "Q2", "session_id": "sess-1"})
    assert r2.status_code == 200

    turns = store.get("sess-1")
    assert len(turns) == 2
