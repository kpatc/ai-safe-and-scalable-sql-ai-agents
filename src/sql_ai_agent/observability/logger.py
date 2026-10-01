from __future__ import annotations

import hashlib
import logging
from typing import Any

from sql_ai_agent.observability.context import get_request_context
from sql_ai_agent.observability.events import get_model_cost, infer_rule_slug

__all__ = [
    "log_event",
    "hash_text",
    "compute_cost",
    "get_rule_slug",
]


def hash_text(text: str) -> str:
    """SHA-256 hex[:16] — safe to log, never reversible."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    return get_model_cost(model, prompt_tokens, completion_tokens)


def get_rule_slug(reason: str) -> str:
    return infer_rule_slug(reason)


def log_event(
    lg: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emit one structured log record.

    Automatically injects request context fields (request_id, session_id,
    question_hash, model, environment) from the ContextVar when present.
    """
    ctx = get_request_context()
    base: dict[str, Any] = {"event": event}
    if ctx is not None:
        base["request_id"] = ctx.request_id
        base["session_id"] = ctx.session_id
        base["question_hash"] = ctx.question_hash
        base["model"] = ctx.model
        base["environment"] = ctx.environment
    base.update(fields)
    lg.log(level, event, extra=base)
