from __future__ import annotations

from sql_ai_agent.llm.parsing import extract_sql, is_unanswerable


def test_extract_sql_from_code_block() -> None:
    text = "Here you go:\n```sql\nSELECT * FROM produits;\n```"
    assert extract_sql(text) == "SELECT * FROM produits"


def test_extract_sql_from_plain_text() -> None:
    text = "Answer: SELECT id FROM clients"
    assert extract_sql(text) == "SELECT id FROM clients"


def test_is_unanswerable_detected() -> None:
    ok, reason = is_unanswerable(
        "UNANSWERABLE: La base ne contient pas de données GPS."
    )
    assert ok is True
    assert "GPS" in reason


def test_is_unanswerable_false_for_sql() -> None:
    ok, _ = is_unanswerable("SELECT 1")
    assert ok is False
