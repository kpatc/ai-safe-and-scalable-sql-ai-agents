from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    session_id: str | None
    question_hash: str
    model: str
    environment: str


_request_ctx: ContextVar[RequestContext | None] = ContextVar(
    "request_ctx", default=None
)


def set_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _request_ctx.set(ctx)


def get_request_context() -> RequestContext | None:
    return _request_ctx.get()


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _request_ctx.reset(token)
