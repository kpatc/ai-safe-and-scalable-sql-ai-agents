from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from sql_ai_agent.agent.sql_agent import SqlAgent
from sql_ai_agent.api.dependencies import get_agent
from sql_ai_agent.domain.models import QueryRequest
from sql_ai_agent.observability import events as ev
from sql_ai_agent.observability.logger import hash_text, log_event

router = APIRouter(prefix="/v1", tags=["query"])
logger = logging.getLogger(__name__)


@router.post("/query")
async def run_query(
    body: QueryRequest,
    http_request: Request,
    agent: SqlAgent = Depends(get_agent),
) -> dict[str, object]:
    sid = body.session_id or str(uuid.uuid4())
    question_hash = hash_text(body.question)
    client_host = http_request.client.host if http_request.client else "unknown"
    request_id: str = getattr(http_request.state, "request_id", str(uuid.uuid4()))

    log_event(
        logger,
        logging.INFO,
        ev.AUDIT_QUERY_REQUEST,
        request_id=request_id,
        question_hash=question_hash,
        session_id=sid,
        client_ip_hash=hash_text(client_host),
    )

    result = await run_in_threadpool(
        agent.ask, body.question, sid, request_id=request_id
    )

    log_event(
        logger,
        logging.INFO,
        ev.AUDIT_QUERY_RESPONSE,
        request_id=request_id,
        question_hash=question_hash,
        session_id=sid,
        status_code=200,
        outcome="success",
        row_count=result.row_count,
        attempts=result.attempts,
        latency_ms=round(result.latency_ms, 2),
    )

    return {
        "session_id": sid,
        "sql": result.sql,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "attempts": result.attempts,
        "latency_ms": result.latency_ms,
    }
