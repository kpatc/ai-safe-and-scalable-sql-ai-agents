from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from langchain_core.runnables import Runnable
from starlette.middleware.base import BaseHTTPMiddleware

from sql_ai_agent.agent.context import build_context
from sql_ai_agent.agent.memory import InMemorySessionStore
from sql_ai_agent.agent.skills import load_skills
from sql_ai_agent.agent.sql_agent import SqlAgent
from sql_ai_agent.api.errors import (
    agent_error_handler,
    llm_unavailable_handler,
    query_timeout_handler,
    repair_exhausted_handler,
    unanswerable_handler,
    validation_rejected_handler,
)
from sql_ai_agent.api.routes.health import router as health_router
from sql_ai_agent.api.routes.metrics import router as metrics_router
from sql_ai_agent.api.routes.query import router as query_router
from sql_ai_agent.api.routes.sessions import router as sessions_router
from sql_ai_agent.config import get_settings
from sql_ai_agent.db.engine import create_readonly_engine
from sql_ai_agent.db.schema import load_schema
from sql_ai_agent.domain.errors import (
    AgentError,
    LLMUnavailable,
    QueryTimeout,
    RepairExhausted,
    UnanswerableQuestion,
    ValidationRejected,
)
from sql_ai_agent.guardrails.rails import load_rails
from sql_ai_agent.llm.client import build_chat_model
from sql_ai_agent.observability import events as ev
from sql_ai_agent.observability.logger import log_event
from sql_ai_agent.observability.logging import configure_logging
from sql_ai_agent.observability.metrics import MetricsStore

logger = logging.getLogger(__name__)


class _RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        import inspect as _inspect

        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = rid
        # call_next is a Callable but typed as object for BaseHTTPMiddleware compat
        if callable(call_next):
            if _inspect.iscoroutinefunction(call_next):
                response: Response = await call_next(request)
            else:
                response = call_next(request)
        else:
            raise TypeError("call_next must be callable")
        response.headers["X-Request-ID"] = rid
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    log_fmt = settings.log_format
    configure_logging(fmt=log_fmt)

    engine = create_readonly_engine(settings.database_url)
    schema = load_schema(engine, include=settings.allowed_tables)
    log_event(
        logger,
        logging.INFO,
        ev.AUDIT_SCHEMA_LOADED,
        dialect=schema.dialect,
        table_count=len(schema.tables),
        column_count=sum(len(t.columns) for t in schema.tables),
    )
    skills = load_skills(settings.skills_dir)
    context = build_context(
        schema=schema,
        engine=engine,
        skills=skills,
        max_values=settings.distinct_values_max,
        max_tokens=settings.context_max_tokens,
    )

    session_store = InMemorySessionStore(
        ttl_seconds=settings.session_ttl_seconds,
        max_turns=settings.session_max_turns,
        max_sessions=settings.session_max_count,
    )

    chat_model: Runnable[Any, Any] | None
    try:
        chat_model = build_chat_model(settings)
    except LLMUnavailable:
        logger.warning("LLM API key not configured — agent will be unavailable")
        chat_model = None

    if chat_model is None:
        raise LLMUnavailable("LLM_API_KEY non configurée — l'agent est indisponible.")

    rails = load_rails(settings)
    if rails is not None:
        log_event(
            logger,
            logging.INFO,
            ev.AUDIT_GUARDRAILS_LOADED,
            guardrails_dir=str(settings.guardrails_dir),
        )

    metrics_store = MetricsStore()

    agent = SqlAgent(
        chat_model=chat_model,
        engine=engine,
        schema=schema,
        settings=settings,
        context=context,
        session_store=session_store,
        rails=rails,
        metrics=metrics_store,
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_store = session_store
    app.state.agent = agent
    app.state.metrics = metrics_store

    log_event(
        logger,
        logging.INFO,
        ev.AUDIT_APP_STARTED,
        model=settings.llm_model,
        environment=settings.environment,
        dialect=schema.dialect,
        table_count=len(schema.tables),
        guardrails_enabled=rails is not None,
    )

    yield

    engine.dispose()
    log_event(logger, logging.INFO, ev.AUDIT_APP_STOPPED)


def create_app() -> FastAPI:
    app = FastAPI(
        title="SQL AI Agent",
        description="Read-only natural-language SQL interface over a boutique database.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(_RequestIdMiddleware)

    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(sessions_router)
    app.include_router(metrics_router)

    for exc_cls, handler in [
        (ValidationRejected, validation_rejected_handler),
        (RepairExhausted, repair_exhausted_handler),
        (QueryTimeout, query_timeout_handler),
        (LLMUnavailable, llm_unavailable_handler),
        (UnanswerableQuestion, unanswerable_handler),
        (AgentError, agent_error_handler),
    ]:
        app.add_exception_handler(exc_cls, handler)

    return app


app = create_app()
