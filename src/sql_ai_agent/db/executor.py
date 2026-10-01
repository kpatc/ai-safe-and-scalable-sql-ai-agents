from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

from sql_ai_agent.domain.errors import QueryExecutionError, QueryTimeout
from sql_ai_agent.safety.validator import ValidatedQuery


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool
    duration_ms: float


def execute(engine: Engine, query: ValidatedQuery, timeout_s: float) -> ExecutionResult:
    start = time.monotonic()
    deadline = start + timeout_s
    interrupted: list[bool] = [False]

    def _progress_handler() -> int:
        if time.monotonic() > deadline:
            interrupted[0] = True
            return 1
        return 0

    with engine.connect() as conn:
        # Access the raw DBAPI connection to install the progress handler
        pool_conn = conn.connection
        raw_dbapi: Any = getattr(pool_conn, "driver_connection", pool_conn)
        raw_dbapi.set_progress_handler(_progress_handler, 100)
        try:
            result = conn.execute(text(query.sql))
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
        except OperationalError as exc:
            if interrupted[0]:
                raise QueryTimeout(timeout_s) from exc
            orig = getattr(exc, "orig", exc)
            raise QueryExecutionError(str(orig)) from exc
        except DBAPIError as exc:
            orig = getattr(exc, "orig", exc)
            raise QueryExecutionError(str(orig)) from exc
        finally:
            raw_dbapi.set_progress_handler(None, 0)

    duration_ms = (time.monotonic() - start) * 1000
    return ExecutionResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=False,
        duration_ms=duration_ms,
    )
