from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from sql_ai_agent.agent.context import build_context
from sql_ai_agent.agent.memory import InMemorySessionStore
from sql_ai_agent.agent.sql_agent import SqlAgent
from sql_ai_agent.config import Settings
from sql_ai_agent.domain.errors import RepairExhausted, UnanswerableQuestion


def _make_agent(
    engine: Any, schema: Any, settings: Settings, *responses: str
) -> SqlAgent:
    sql_blocks = [f"```sql\n{r}\n```" for r in responses]
    fake = FakeListChatModel(responses=list(sql_blocks))
    ctx = build_context(schema=schema, engine=engine, skills="")
    return SqlAgent(
        chat_model=fake,
        engine=engine,
        schema=schema,
        settings=settings,
        context=ctx,
        session_store=InMemorySessionStore(),
    )


def test_direct_success(engine: Any, schema: Any, test_settings: Settings) -> None:
    agent = _make_agent(
        engine, schema, test_settings, "SELECT * FROM produits LIMIT 10"
    )
    result = agent.ask("Liste les produits")
    assert result.row_count == 2
    assert result.attempts == 1


def test_repair_on_invalid_sql(
    engine: Any, schema: Any, test_settings: Settings
) -> None:
    # First response: invalid SQL; second: valid SQL
    agent = _make_agent(
        engine,
        schema,
        test_settings,
        "SELECT * FROM table_inexistante LIMIT 5",
        "SELECT * FROM produits LIMIT 10",
    )
    result = agent.ask("Liste les produits")
    assert result.attempts == 2
    assert result.row_count == 2


def test_repair_exhausted(engine: Any, schema: Any, test_settings: Settings) -> None:
    agent = _make_agent(
        engine,
        schema,
        test_settings,
        "SELECT * FROM table_inexistante",
        "SELECT * FROM autre_table_inexistante",
        "SELECT * FROM encore_une_autre",
    )
    with pytest.raises(RepairExhausted):
        agent.ask("Question impossible")


def test_unanswerable(engine: Any, schema: Any, test_settings: Settings) -> None:
    ctx = build_context(schema=schema, engine=engine, skills="")
    fake = FakeListChatModel(
        responses=["UNANSWERABLE: La base ne contient pas ce champ."]
    )
    agent = SqlAgent(
        chat_model=fake,
        engine=engine,
        schema=schema,
        settings=test_settings,
        context=ctx,
        session_store=InMemorySessionStore(),
    )
    with pytest.raises(UnanswerableQuestion):
        agent.ask("Question hors périmètre")


def test_dangerous_sql_repaired(
    engine: Any, schema: Any, test_settings: Settings
) -> None:
    # LLM first returns dangerous SQL, then valid SQL
    agent = _make_agent(
        engine,
        schema,
        test_settings,
        "DROP TABLE clients",
        "SELECT * FROM clients LIMIT 5",
    )
    result = agent.ask("Supprime les clients")
    # Should succeed after repair
    assert result.sql.upper().startswith("SELECT")


def test_session_memory_populated(
    engine: Any, schema: Any, test_settings: Settings
) -> None:
    store = InMemorySessionStore()
    ctx = build_context(schema=schema, engine=engine, skills="")
    fake = FakeListChatModel(
        responses=[
            "```sql\nSELECT * FROM produits LIMIT 5\n```",
            "```sql\nSELECT * FROM clients LIMIT 5\n```",
        ]
    )
    agent = SqlAgent(
        chat_model=fake,
        engine=engine,
        schema=schema,
        settings=test_settings,
        context=ctx,
        session_store=store,
    )
    agent.ask("Question 1", session_id="test-session")
    turns = store.get("test-session")
    assert len(turns) == 1
    assert turns[0].question == "Question 1"
