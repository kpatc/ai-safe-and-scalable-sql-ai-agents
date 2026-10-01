"""Online quality scorer — called after each agent request.

Computes lightweight quality signals that can be logged to an observability
backend (Langfuse, Datadog, etc.) without blocking the response path.

Usage:
    score = score_result(question, result, reference_sql=None)
    # score is a dict ready to POST to Langfuse /api/public/scores
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from sql_ai_agent.domain.models import QueryResult


def _is_valid_select(sql: str) -> bool:
    """Check if SQL looks like a SELECT statement."""
    return bool(re.match(r"^\s*(?:WITH|SELECT)\b", sql.strip(), re.IGNORECASE))


def _sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.strip().encode()).hexdigest()[:12]


def score_result(
    question: str,
    result: QueryResult,
    reference_sql: str | None = None,
) -> dict[str, Any]:
    """Compute quality scores for a completed agent response.

    Returns a dict of named scores, each with a numeric value in [0, 1].
    Compatible with Langfuse score format.
    """
    scores: dict[str, float] = {}

    # Score 1: SQL is a valid SELECT (structural check)
    scores["valid_sql"] = 1.0 if _is_valid_select(result.sql) else 0.0

    # Score 2: Query produced at least one row (non-empty result)
    scores["has_results"] = 1.0 if result.row_count > 0 else 0.0

    # Score 3: First-attempt success (no repairs needed)
    scores["first_attempt_success"] = 1.0 if result.attempts == 1 else 0.0

    # Score 4: Fast response (latency < 5s gets full score, linear decay to 30s)
    latency_s = result.latency_ms / 1000.0
    scores["latency_score"] = max(0.0, min(1.0, 1.0 - (latency_s - 5.0) / 25.0))

    # Score 5: Result not truncated (truncation may indicate overly broad query)
    scores["result_not_truncated"] = 0.0 if result.truncated else 1.0

    # Score 6: If reference SQL provided, check hash match (exact SQL match)
    if reference_sql is not None:
        ref_hash = _sql_hash(reference_sql)
        agent_hash = _sql_hash(result.sql)
        scores["sql_exact_match"] = 1.0 if ref_hash == agent_hash else 0.0

    # Composite score: weighted average of key signals
    composite = (
        scores["valid_sql"] * 0.35
        + scores["has_results"] * 0.25
        + scores["first_attempt_success"] * 0.20
        + scores["result_not_truncated"] * 0.10
        + scores["latency_score"] * 0.10
    )
    scores["composite"] = round(composite, 4)

    return {
        "question_hash": _sql_hash(question),
        "sql_hash": _sql_hash(result.sql),
        "scores": scores,
        "metadata": {
            "row_count": result.row_count,
            "attempts": result.attempts,
            "latency_ms": result.latency_ms,
            "truncated": result.truncated,
            "columns": result.columns[:10],
        },
    }


async def log_score_async(
    score_data: dict[str, Any],
    trace_id: str,
    langfuse_url: str | None = None,
    langfuse_public_key: str | None = None,
    langfuse_secret_key: str | None = None,
) -> None:
    """Async fire-and-forget: POST scores to Langfuse (if configured).

    Safe to call without awaiting — errors are silently swallowed so they
    never affect the user-facing response.
    """
    if not langfuse_url or not langfuse_public_key or not langfuse_secret_key:
        return

    import httpx

    try:
        payload = [
            {
                "name": name,
                "value": value,
                "traceId": trace_id,
                "dataType": "NUMERIC",
            }
            for name, value in score_data["scores"].items()
        ]
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{langfuse_url}/api/public/scores",
                json=payload,
                auth=(langfuse_public_key, langfuse_secret_key),
                timeout=5.0,
            )
    except Exception:
        pass  # Never let observability break the main path


def log_score(
    score_data: dict[str, Any],
    trace_id: str,
    langfuse_url: str | None = None,
    langfuse_public_key: str | None = None,
    langfuse_secret_key: str | None = None,
) -> None:
    """Synchronous wrapper around log_score_async — schedules the coroutine."""
    coro = log_score_async(
        score_data, trace_id, langfuse_url, langfuse_public_key, langfuse_secret_key
    )
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        asyncio.run(coro)
