from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event


def create_readonly_engine(url: str) -> Engine:
    if url.startswith("sqlite") and "mode=ro" not in url:
        raise ValueError(
            "SQLite URL must include 'mode=ro'. "
            f"Got: {url!r}. Use: sqlite:///file:path.db?mode=ro&uri=true"
        )

    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only = ON")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine
