from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    session_id: str | None = None


class QueryResult(BaseModel):
    session_id: str | None = None
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[tuple[Any, ...]] = Field(default_factory=list)
    row_count: int
    truncated: bool = False
    attempts: int = 1
    latency_ms: float = 0.0


class UnanswerableResult(BaseModel):
    session_id: str | None = None
    unanswerable: bool = True
    reason: str


class Turn(BaseModel):
    question: str
    sql: str
    columns: list[str]
    row_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AttemptLog(BaseModel):
    attempt: int
    sql_hash: str
    valid: bool
    error_type: str | None = None
    duration_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AgentTrace(BaseModel):
    request_id: str
    attempts: list[AttemptLog] = Field(default_factory=list)
    outcome: str = "success"
    total_duration_ms: float = 0.0
    row_count: int = 0
