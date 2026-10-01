"""Regression tests against the golden dataset.

Two test modes:
1. No LLM (default): validate that reference SQL from golden.yaml still
   validates against the current schema and executes without error.
   Run with: uv run pytest tests/regression/

2. Real LLM (marked llm): run each golden question through the live agent
   and verify the response matches expected shape.
   Run with: uv run pytest tests/regression/ -m llm
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from sql_ai_agent.db.executor import execute
from sql_ai_agent.safety.validator import validate

GOLDEN_FILE = Path(__file__).parent / "golden.yaml"


def load_golden() -> list[dict[str, Any]]:
    with open(GOLDEN_FILE) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


GOLDEN = load_golden()


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_reference_sql_validates(case: dict[str, Any], schema: Any) -> None:
    """Reference SQL from golden.yaml must pass the AST validator unchanged."""
    sql = case["reference_sql"].strip()
    validated = validate(sql, schema=schema, max_rows=1000)
    assert validated.sql  # Non-empty SQL was returned


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_reference_sql_executes(case: dict[str, Any], engine: Any, schema: Any) -> None:
    """Reference SQL must execute without error against the test database.

    Row-count assertions are skipped because the test DB is a small sample.
    Column shape is checked when the query returns at least one row.
    """
    sql = case["reference_sql"].strip()
    validated = validate(sql, schema=schema, max_rows=1000)
    result = execute(engine, validated, timeout_s=30.0)

    # Only check column names when the query actually returns rows
    if case.get("expected_columns") and result.row_count > 0:
        assert result.columns == case["expected_columns"], (
            f"Columns mismatch: got {result.columns}, "
            f"expected {case['expected_columns']}"
        )


@pytest.mark.llm
@pytest.mark.parametrize(
    "case",
    [c for c in GOLDEN if c.get("answerable", True)],
    ids=[c["id"] for c in GOLDEN if c.get("answerable", True)],
)
def test_agent_golden_answer(case: dict[str, Any], agent: Any) -> None:
    """Agent must produce a valid, row-returning result for each golden question.

    Requires a real LLM: uv run pytest tests/regression/ -m llm
    """
    result = agent.ask(case["question"])

    assert result.sql, "Agent must return non-empty SQL"
    assert result.row_count >= case.get("expected_min_rows", 0), (
        f"Expected >= {case.get('expected_min_rows', 0)} rows, got {result.row_count}"
    )

    if case.get("expected_columns"):
        for col in case["expected_columns"]:
            assert col in result.columns, (
                f"Expected column '{col}' not in {result.columns}"
            )
