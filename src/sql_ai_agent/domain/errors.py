from __future__ import annotations


class AgentError(Exception):
    """Base for all agent errors."""


class ValidationRejected(AgentError):
    """SQL violates a safety rule. Maps to HTTP 422."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class QueryExecutionError(AgentError):
    """SQL execution error. Triggers automatic repair."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class QueryTimeout(AgentError):
    """Query exceeded the configured timeout. Maps to HTTP 504."""

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        super().__init__(f"Délai dépassé ({timeout_s}s)")


class LLMUnavailable(AgentError):
    """LLM provider unreachable after fallback. Maps to HTTP 503."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class RepairExhausted(AgentError):
    """Max repair attempts reached. Maps to HTTP 422."""

    def __init__(self, last_sql: str, last_error: str) -> None:
        self.last_sql = last_sql
        self.last_error = last_error
        super().__init__(f"Réparation épuisée : {last_error}")


class UnanswerableQuestion(AgentError):
    """LLM indicates the database cannot answer the question. Maps to HTTP 200."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
