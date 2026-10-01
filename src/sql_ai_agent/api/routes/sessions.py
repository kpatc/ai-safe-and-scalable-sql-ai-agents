from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from sql_ai_agent.agent.memory import InMemorySessionStore
from sql_ai_agent.api.dependencies import get_session_store

router = APIRouter(prefix="/v1", tags=["sessions"])


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    store: InMemorySessionStore = Depends(get_session_store),
) -> Response:
    store.clear(session_id)
    return Response(status_code=204)
