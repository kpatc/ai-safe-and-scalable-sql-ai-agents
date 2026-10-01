from __future__ import annotations

import pytest

from sql_ai_agent.db.schema import ColumnInfo, DatabaseSchema, TableInfo
from sql_ai_agent.domain.errors import ValidationRejected
from sql_ai_agent.safety.validator import ValidatedQuery, validate

MAX_ROWS = 100
DIALECT = "sqlite"


def _schema(*table_names: str) -> DatabaseSchema:
    tables = [
        TableInfo(
            name=name,
            columns=[
                ColumnInfo(name="id", type="INTEGER", nullable=False, primary_key=True)
            ],
            foreign_keys=[],
            row_count=0,
        )
        for name in table_names
    ]
    return DatabaseSchema(tables=tables, dialect=DIALECT)


SCHEMA = _schema(
    "clients", "commandes", "produits", "categories", "lignes_commande", "avis"
)


# ---------------------------------------------------------------------------
# Accepted queries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT * FROM clients",
        "SELECT c.id FROM clients c JOIN commandes co ON c.id = co.id",
        "WITH x AS (SELECT id FROM clients) SELECT * FROM x",
        "SELECT * FROM clients UNION SELECT * FROM clients",
        "SELECT * FROM clients WHERE id = (SELECT id FROM commandes LIMIT 1)",
        "SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM clients",
        "SELECT strftime('%Y', '2024-01-01')",
        "SELECT c.id AS client FROM clients c",
        "SELECT * FROM clients;",
    ],
)
def test_accepted(sql: str) -> None:
    result = validate(sql, schema=SCHEMA, max_rows=MAX_ROWS, dialect=DIALECT)
    assert isinstance(result, ValidatedQuery)


# ---------------------------------------------------------------------------
# Rejected queries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO clients VALUES (1)",
        "UPDATE clients SET id = 1",
        "DELETE FROM clients",
        "DROP TABLE clients",
        "CREATE TABLE foo (id INTEGER)",
        "ALTER TABLE clients ADD COLUMN x TEXT",
        "PRAGMA query_only",
        "ATTACH DATABASE ':memory:' AS tmp",
        "SELECT * FROM clients; SELECT * FROM commandes",
        "SELECT 1; DROP TABLE clients",
        "WITH x AS (DELETE FROM clients RETURNING id) SELECT * FROM x",
        "VACUUM",
        "DETACH DATABASE main",
        "SELECT * FROM unknown_table",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('x')",
        "",
        "-- just a comment",
        "NOT VALID SQL $$$$",
    ],
)
def test_rejected(sql: str) -> None:
    with pytest.raises(ValidationRejected):
        validate(sql, schema=SCHEMA, max_rows=MAX_ROWS, dialect=DIALECT)


# ---------------------------------------------------------------------------
# Limit enforcement
# ---------------------------------------------------------------------------


def test_limit_added_when_absent() -> None:
    result = validate(
        "SELECT * FROM clients", schema=SCHEMA, max_rows=50, dialect=DIALECT
    )
    assert result.limit_applied is True
    assert "LIMIT 50" in result.sql.upper() or "limit 50" in result.sql


def test_limit_reduced_when_too_high() -> None:
    result = validate(
        "SELECT * FROM clients LIMIT 9999", schema=SCHEMA, max_rows=50, dialect=DIALECT
    )
    assert result.limit_applied is True
    assert "9999" not in result.sql


def test_limit_preserved_when_lower() -> None:
    result = validate(
        "SELECT * FROM clients LIMIT 10", schema=SCHEMA, max_rows=50, dialect=DIALECT
    )
    assert result.limit_applied is False
    assert "10" in result.sql


# ---------------------------------------------------------------------------
# CTE names excluded from table check
# ---------------------------------------------------------------------------


def test_cte_alias_not_checked_as_table() -> None:
    sql = "WITH recent AS (SELECT id FROM commandes) SELECT * FROM recent"
    result = validate(sql, schema=SCHEMA, max_rows=MAX_ROWS, dialect=DIALECT)
    assert isinstance(result, ValidatedQuery)


# ---------------------------------------------------------------------------
# Readonly engine security
# ---------------------------------------------------------------------------


def test_readonly_engine_rejects_insert(engine: object) -> None:
    from sqlalchemy import text
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import OperationalError

    assert isinstance(engine, Engine)
    with pytest.raises(OperationalError):
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO produits VALUES (99, 'X', 1, 1, 1, 1, 1, '2023-01-01')"
                )
            )
            conn.commit()
