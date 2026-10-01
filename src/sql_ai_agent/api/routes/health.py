from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from sql_ai_agent.api.dependencies import get_engine, get_settings
from sql_ai_agent.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(
    engine: object = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    from sqlalchemy.engine import Engine

    assert isinstance(engine, Engine)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    if not settings.llm_api_key:
        return {"status": "degraded", "reason": "LLM_API_KEY not configured"}
    return {"status": "ready"}
