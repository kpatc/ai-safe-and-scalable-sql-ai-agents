from __future__ import annotations

# ---------------------------------------------------------------------------
# Event slugs — one constant per event type emitted in the system
# ---------------------------------------------------------------------------

# Query lifecycle
QUERY_RECEIVED = "query.received"
QUERY_GUARDRAILS_PASSED = "query.guardrails_passed"
QUERY_GUARDRAILS_BLOCKED = "query.guardrails_blocked"
QUERY_UNANSWERABLE = "query.unanswerable"
QUERY_COMPLETED = "query.completed"
QUERY_FAILED = "query.failed"

# Agent decisions
AGENT_ATTEMPT_STARTED = "agent.attempt_started"
AGENT_LLM_CALLED = "agent.llm_called"
AGENT_SQL_EXTRACTED = "agent.sql_extracted"
AGENT_VALIDATION_PASSED = "agent.validation_passed"
AGENT_VALIDATION_FAILED = "agent.validation_failed"
AGENT_EXECUTION_PASSED = "agent.execution_passed"
AGENT_REPAIR_TRIGGERED = "agent.repair_triggered"

# Errors
ERROR_VALIDATION_REJECTED = "error.validation_rejected"
ERROR_EXECUTION_FAILED = "error.execution_failed"
ERROR_TIMEOUT = "error.timeout"
ERROR_LLM_UNAVAILABLE = "error.llm_unavailable"
ERROR_REPAIR_EXHAUSTED = "error.repair_exhausted"
ERROR_UNEXPECTED = "error.unexpected"

# Performance
PERF_LLM_LATENCY = "perf.llm_latency"
PERF_VALIDATION_LATENCY = "perf.validation_latency"
PERF_EXECUTION_LATENCY = "perf.execution_latency"
PERF_REQUEST_SUMMARY = "perf.request_summary"
PERF_SESSION_SIZE = "perf.session_size"

# Audit & schema
AUDIT_QUERY_REQUEST = "audit.query_request"
AUDIT_QUERY_RESPONSE = "audit.query_response"
AUDIT_SCHEMA_LOADED = "audit.schema_loaded"
AUDIT_GUARDRAILS_LOADED = "audit.guardrails_loaded"
AUDIT_SESSION_DELETED = "audit.session_deleted"
AUDIT_APP_STARTED = "audit.app_started"
AUDIT_APP_STOPPED = "audit.app_stopped"

# ---------------------------------------------------------------------------
# LLM pricing: (input_usd_per_1k_tokens, output_usd_per_1k_tokens)
# ---------------------------------------------------------------------------
_MODEL_COST_USD_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.010, 0.030),
    "gpt-4": (0.030, 0.060),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-opus-4-7": (0.015, 0.075),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-haiku-4-5": (0.00025, 0.00125),
}


def get_model_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost. Returns 0.0 for unknown models."""
    base = model.split(":")[0].lower()
    for key, (in_rate, out_rate) in _MODEL_COST_USD_PER_1K.items():
        if key in base:
            return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1000.0
    return 0.0


# ---------------------------------------------------------------------------
# Validation rule slug map (ValidationRejected.reason prefix → slug)
# ---------------------------------------------------------------------------
_RULE_SLUG_MAP: list[tuple[str, str]] = [
    ("SQL invalide", "parse_error"),
    ("vide", "empty_statement"),
    ("seule instruction", "single_stmt"),
    ("SELECT", "select_only"),
    ("Instruction interdite", "no_write_nodes"),
    ("Table inconnue", "allowed_tables"),
    ("système", "system_table"),
    ("Fonction interdite", "forbidden_function"),
    ("LIMIT", "limit_enforcement"),
    ("guardrails", "guardrails_blocked"),
]


def infer_rule_slug(reason: str) -> str:
    for fragment, slug in _RULE_SLUG_MAP:
        if fragment.lower() in reason.lower():
            return slug
    return "unknown"
