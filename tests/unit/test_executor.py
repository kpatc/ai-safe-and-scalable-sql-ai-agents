from __future__ import annotations

import pytest

from sql_ai_agent.db.executor import ExecutionResult, execute
from sql_ai_agent.domain.errors import QueryTimeout
from sql_ai_agent.safety.validator import ValidatedQuery


def _make_validated(sql: str) -> ValidatedQuery:
    return ValidatedQuery(sql=sql, tables=frozenset(), limit_applied=False)


def test_execute_returns_result(engine: object) -> None:
    q = _make_validated(
        "SELECT produit_id, nom, prix_unitaire FROM produits ORDER BY prix_unitaire DESC"
    )
    result = execute(engine, q, timeout_s=5.0)  # type: ignore[arg-type]
    assert isinstance(result, ExecutionResult)
    assert result.row_count == 2
    assert result.columns == ["produit_id", "nom", "prix_unitaire"]
    assert result.duration_ms >= 0


def test_execute_timeout() -> None:
    """A recursive CTE counting to a large number should timeout."""
    import os
    import tempfile

    from sql_ai_agent.db.engine import create_readonly_engine

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        import sqlite3 as _sl

        _sl.connect(db_path).close()
        ro = create_readonly_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")
        slow_sql = (
            "WITH RECURSIVE cnt(x) AS "
            "(SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < 999999999) "
            "SELECT MAX(x) FROM cnt"
        )
        q = _make_validated(slow_sql)
        with pytest.raises(QueryTimeout):
            execute(ro, q, timeout_s=0.5)
    finally:
        os.unlink(db_path)
