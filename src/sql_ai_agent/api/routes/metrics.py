from __future__ import annotations

from fastapi import APIRouter, Request

from sql_ai_agent.observability.metrics import MetricsStore

router = APIRouter(prefix="/v1", tags=["metrics"])


@router.get("/metrics")
async def get_metrics(request: Request) -> dict[str, object]:
    store: MetricsStore = request.app.state.metrics
    return store.snapshot()


@router.delete("/metrics/reset")
async def reset_metrics(request: Request) -> dict[str, str]:
    """Reset all counters (dev/testing only)."""
    new_store = MetricsStore()
    request.app.state.metrics = new_store
    # Also update the agent reference
    request.app.state.agent.metrics = new_store
    return {"status": "reset"}
