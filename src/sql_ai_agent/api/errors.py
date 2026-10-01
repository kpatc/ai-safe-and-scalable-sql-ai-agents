from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from sql_ai_agent.domain.errors import (
    AgentError,
    LLMUnavailable,
    QueryTimeout,
    RepairExhausted,
    UnanswerableQuestion,
    ValidationRejected,
)
from sql_ai_agent.observability import events as ev
from sql_ai_agent.observability.logger import log_event

logger = logging.getLogger(__name__)


def _error_body(code: str, message: str) -> dict[str, str]:
    return {"error": code, "message": message}


async def validation_rejected_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ValidationRejected)
    log_event(
        logger,
        logging.WARNING,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=422,
        outcome="validation_rejected",
        error_type="ValidationRejected",
    )
    return JSONResponse(
        status_code=422,
        content=_error_body("validation_rejected", exc.reason),
    )


async def repair_exhausted_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RepairExhausted)
    log_event(
        logger,
        logging.ERROR,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=422,
        outcome="repair_exhausted",
        error_type="RepairExhausted",
    )
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "repair_exhausted",
            f"Impossible de générer une requête valide : {exc.last_error}",
        ),
    )


async def query_timeout_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, QueryTimeout)
    log_event(
        logger,
        logging.WARNING,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=504,
        outcome="timeout",
        error_type="QueryTimeout",
    )
    return JSONResponse(
        status_code=504,
        content=_error_body("query_timeout", str(exc)),
    )


async def llm_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LLMUnavailable)
    log_event(
        logger,
        logging.ERROR,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=503,
        outcome="llm_unavailable",
        error_type="LLMUnavailable",
    )
    return JSONResponse(
        status_code=503,
        content=_error_body("llm_unavailable", exc.message),
    )


async def unanswerable_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, UnanswerableQuestion)
    log_event(
        logger,
        logging.INFO,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=200,
        outcome="unanswerable",
        error_type="UnanswerableQuestion",
    )
    return JSONResponse(
        status_code=200,
        content={"unanswerable": True, "reason": exc.reason},
    )


async def agent_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AgentError)
    log_event(
        logger,
        logging.ERROR,
        ev.AUDIT_QUERY_RESPONSE,
        status_code=500,
        outcome="agent_error",
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=_error_body("agent_error", "Erreur interne de l'agent."),
    )
