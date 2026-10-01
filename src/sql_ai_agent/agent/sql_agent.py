from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from sql_ai_agent.agent.memory import InMemorySessionStore, SessionStore
from sql_ai_agent.config import Settings
from sql_ai_agent.db.executor import ExecutionResult, execute
from sql_ai_agent.db.schema import DatabaseSchema
from sql_ai_agent.domain.errors import (
    QueryExecutionError,
    QueryTimeout,
    RepairExhausted,
    UnanswerableQuestion,
    ValidationRejected,
)
from sql_ai_agent.domain.models import AgentTrace, AttemptLog, QueryResult, Turn
from sql_ai_agent.llm.parsing import extract_sql, is_unanswerable
from sql_ai_agent.observability import events as ev
from sql_ai_agent.observability.context import RequestContext, set_request_context
from sql_ai_agent.observability.logger import (
    compute_cost,
    get_rule_slug,
    hash_text,
    log_event,
)
from sql_ai_agent.observability.metrics import MetricsStore
from sql_ai_agent.safety.validator import ValidatedQuery, validate

if TYPE_CHECKING:
    from nemoguardrails import LLMRails

logger = logging.getLogger(__name__)


@dataclass
class SqlAgent:
    chat_model: Runnable[Any, Any]
    engine: Any  # SQLAlchemy Engine
    schema: DatabaseSchema
    settings: Settings
    context: str
    session_store: SessionStore = field(default_factory=InMemorySessionStore)
    rails: LLMRails | None = None
    metrics: MetricsStore | None = None

    def _load_generate_prompt(self) -> str:
        prompt_path = self.settings.prompts_dir / "generate.md"
        return prompt_path.read_text(encoding="utf-8")

    def _load_repair_prompt(self) -> str:
        prompt_path = self.settings.prompts_dir / "repair.md"
        return prompt_path.read_text(encoding="utf-8")

    def _sql_hash(self, sql: str) -> str:
        return hashlib.sha256(sql.encode()).hexdigest()[:12]

    def _invoke(self, messages: list[Any]) -> tuple[str, int, int]:
        response = self.chat_model.invoke(messages)
        content: str = getattr(response, "content", str(response))
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens: int = getattr(usage, "input_tokens", 0) if usage else 0
        completion_tokens: int = getattr(usage, "output_tokens", 0) if usage else 0
        return content, prompt_tokens, completion_tokens

    def ask(
        self,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> QueryResult:
        import uuid

        request_id = request_id or str(uuid.uuid4())
        question_hash = hash_text(question)

        # Establish request context for all downstream log_event calls
        ctx = RequestContext(
            request_id=request_id,
            session_id=session_id,
            question_hash=question_hash,
            model=self.settings.llm_model,
            environment=self.settings.environment,
        )
        set_request_context(ctx)

        # Load session history
        history: list[Turn] = []
        if session_id:
            history = self.session_store.get(session_id)

        log_event(
            logger,
            logging.INFO,
            ev.QUERY_RECEIVED,
            history_turns=len(history),
        )

        # Guardrails input check
        if self.rails is not None:
            from sql_ai_agent.domain.errors import ValidationRejected as _VR
            from sql_ai_agent.guardrails.rails import check_input

            try:
                check_input(self.rails, question)
            except _VR:
                if self.metrics:
                    self.metrics.record_guardrails_blocked()
                raise

        log_event(logger, logging.INFO, ev.QUERY_GUARDRAILS_PASSED)

        trace = AgentTrace(request_id=request_id)
        start_total = time.monotonic()

        # Build history messages
        history_msgs: list[Any] = []
        for turn in history:
            history_msgs.append(HumanMessage(content=turn.question))
            history_msgs.append(AIMessage(content=turn.sql))

        generate_template = self._load_generate_prompt()
        system_text = generate_template.format(
            dialect=self.schema.dialect,
            context=self.context,
            question=question,
        )
        messages: list[Any] = (
            [SystemMessage(content=system_text)]
            + history_msgs
            + [HumanMessage(content=question)]
        )

        sql = ""
        last_error = ""
        attempt_idx = 0

        # Accumulators for perf.request_summary
        llm_ms_total: float = 0.0
        val_ms_total: float = 0.0
        exec_ms_total: float = 0.0
        total_prompt_tokens: int = 0
        total_completion_tokens: int = 0
        outcome = "unknown"

        while attempt_idx <= self.settings.max_repairs:
            is_repair = attempt_idx > 0

            log_event(
                logger,
                logging.DEBUG,
                ev.AGENT_ATTEMPT_STARTED,
                attempt=attempt_idx + 1,
                is_repair=is_repair,
            )

            # --- LLM call ---
            if is_repair:
                repair_template = self._load_repair_prompt()
                repair_text = repair_template.format(
                    dialect=self.schema.dialect,
                    context=self.context,
                    question=question,
                    failed_sql=sql,
                    error=last_error,
                )
                current_messages: list[Any] = [SystemMessage(content=repair_text)]

                log_event(
                    logger,
                    logging.INFO,
                    ev.AGENT_REPAIR_TRIGGERED,
                    attempt=attempt_idx + 1,
                    trigger=last_error[:120],
                    remaining_attempts=self.settings.max_repairs - attempt_idx,
                )
                if self.metrics:
                    self.metrics.record_repair_attempt()
            else:
                current_messages = messages

            t_llm = time.monotonic()
            content, prompt_tok, compl_tok = self._invoke(current_messages)
            llm_ms = (time.monotonic() - t_llm) * 1000

            llm_ms_total += llm_ms
            total_prompt_tokens += prompt_tok
            total_completion_tokens += compl_tok
            cost = compute_cost(self.settings.llm_model, prompt_tok, compl_tok)

            log_event(
                logger,
                logging.DEBUG,
                ev.AGENT_LLM_CALLED,
                attempt=attempt_idx + 1,
                is_repair=is_repair,
                duration_ms=round(llm_ms, 2),
                prompt_tokens=prompt_tok,
                completion_tokens=compl_tok,
                estimated_cost_usd=cost,
            )
            log_event(
                logger,
                logging.INFO,
                ev.PERF_LLM_LATENCY,
                attempt=attempt_idx + 1,
                duration_ms=round(llm_ms, 2),
                prompt_tokens=prompt_tok,
                completion_tokens=compl_tok,
                estimated_cost_usd=cost,
            )

            # --- UNANSWERABLE check ---
            unanswerable, reason = is_unanswerable(content)
            if unanswerable:
                log_event(
                    logger,
                    logging.INFO,
                    ev.QUERY_UNANSWERABLE,
                    reason=reason,
                )
                if self.metrics:
                    total_ms_so_far = (time.monotonic() - start_total) * 1000
                    total_cost_so_far = compute_cost(
                        self.settings.llm_model,
                        total_prompt_tokens,
                        total_completion_tokens,
                    )
                    self.metrics.record_request_completed(
                        outcome="unanswerable",
                        latency_ms=total_ms_so_far,
                        llm_ms=llm_ms_total,
                        val_ms=val_ms_total,
                        exec_ms=exec_ms_total,
                        prompt_tokens=total_prompt_tokens,
                        completion_tokens=total_completion_tokens,
                        cost_usd=total_cost_so_far,
                        attempts=attempt_idx + 1,
                        model=self.settings.llm_model,
                    )
                raise UnanswerableQuestion(reason)

            sql = extract_sql(content)
            sql_hash = self._sql_hash(sql)

            log_event(
                logger,
                logging.DEBUG,
                ev.AGENT_SQL_EXTRACTED,
                attempt=attempt_idx + 1,
                sql_hash=sql_hash,
            )

            attempt_log = AttemptLog(
                attempt=attempt_idx + 1,
                sql_hash=sql_hash,
                valid=False,
                error_type=None,
                duration_ms=0.0,
                prompt_tokens=prompt_tok,
                completion_tokens=compl_tok,
            )

            # --- Validation ---
            t_val = time.monotonic()
            try:
                validated: ValidatedQuery = validate(
                    sql,
                    schema=self.schema,
                    max_rows=self.settings.max_rows,
                    dialect=self.schema.dialect,
                )
            except ValidationRejected as exc:
                val_ms = (time.monotonic() - t_val) * 1000
                val_ms_total += val_ms
                last_error = exc.reason
                rule = get_rule_slug(exc.reason)

                log_event(
                    logger,
                    logging.WARNING,
                    ev.AGENT_VALIDATION_FAILED,
                    attempt=attempt_idx + 1,
                    sql_hash=sql_hash,
                    rule_violated=rule,
                    validation_duration_ms=round(val_ms, 2),
                )
                log_event(
                    logger,
                    logging.WARNING,
                    ev.ERROR_VALIDATION_REJECTED,
                    attempt=attempt_idx + 1,
                    rule_violated=rule,
                    error_message_hash=hash_text(exc.reason),
                    duration_ms=round(val_ms, 2),
                )
                log_event(
                    logger,
                    logging.DEBUG,
                    ev.PERF_VALIDATION_LATENCY,
                    attempt=attempt_idx + 1,
                    duration_ms=round(val_ms, 2),
                    passed=False,
                )
                if self.metrics:
                    self.metrics.record_validation_failure(rule)
                trace.attempts.append(
                    AttemptLog(
                        **{
                            **attempt_log.__dict__,
                            "error_type": "ValidationRejected",
                            "duration_ms": val_ms,
                        }
                    )
                )
                attempt_idx += 1
                continue

            val_ms = (time.monotonic() - t_val) * 1000
            val_ms_total += val_ms

            log_event(
                logger,
                logging.INFO,
                ev.AGENT_VALIDATION_PASSED,
                attempt=attempt_idx + 1,
                sql_hash=sql_hash,
                limit_applied=validated.limit_applied,
                tables_referenced=sorted(validated.tables),
                validation_duration_ms=round(val_ms, 2),
            )
            log_event(
                logger,
                logging.DEBUG,
                ev.PERF_VALIDATION_LATENCY,
                attempt=attempt_idx + 1,
                duration_ms=round(val_ms, 2),
                passed=True,
            )

            # --- Execution ---
            t_exec = time.monotonic()
            try:
                exec_result: ExecutionResult = execute(
                    self.engine,
                    validated,
                    timeout_s=self.settings.query_timeout_seconds,
                )
            except QueryTimeout as exc:
                exec_ms = (time.monotonic() - t_exec) * 1000
                exec_ms_total += exec_ms
                last_error = str(exc)

                log_event(
                    logger,
                    logging.WARNING,
                    ev.ERROR_TIMEOUT,
                    attempt=attempt_idx + 1,
                    sql_hash=sql_hash,
                    timeout_s=self.settings.query_timeout_seconds,
                    duration_ms=round(exec_ms, 2),
                )
                log_event(
                    logger,
                    logging.DEBUG,
                    ev.PERF_EXECUTION_LATENCY,
                    attempt=attempt_idx + 1,
                    duration_ms=round(exec_ms, 2),
                    row_count=0,
                    truncated=False,
                    passed=False,
                )
                trace.attempts.append(
                    AttemptLog(
                        **{
                            **attempt_log.__dict__,
                            "valid": True,
                            "error_type": "QueryTimeout",
                            "duration_ms": exec_ms,
                        }
                    )
                )
                if attempt_idx >= 1:
                    raise
                attempt_idx += 1
                continue

            except QueryExecutionError as exc:
                exec_ms = (time.monotonic() - t_exec) * 1000
                exec_ms_total += exec_ms
                last_error = exc.message

                log_event(
                    logger,
                    logging.WARNING,
                    ev.ERROR_EXECUTION_FAILED,
                    attempt=attempt_idx + 1,
                    sql_hash=sql_hash,
                    error_message_hash=hash_text(exc.message),
                    duration_ms=round(exec_ms, 2),
                )
                log_event(
                    logger,
                    logging.DEBUG,
                    ev.PERF_EXECUTION_LATENCY,
                    attempt=attempt_idx + 1,
                    duration_ms=round(exec_ms, 2),
                    row_count=0,
                    truncated=False,
                    passed=False,
                )
                trace.attempts.append(
                    AttemptLog(
                        **{
                            **attempt_log.__dict__,
                            "valid": True,
                            "error_type": "QueryExecutionError",
                            "duration_ms": exec_ms,
                        }
                    )
                )
                attempt_idx += 1
                continue

            exec_ms = (time.monotonic() - t_exec) * 1000
            exec_ms_total += exec_ms

            log_event(
                logger,
                logging.INFO,
                ev.AGENT_EXECUTION_PASSED,
                attempt=attempt_idx + 1,
                sql_hash=sql_hash,
                row_count=exec_result.row_count,
                truncated=exec_result.truncated,
                execution_duration_ms=round(exec_ms, 2),
            )
            log_event(
                logger,
                logging.DEBUG,
                ev.PERF_EXECUTION_LATENCY,
                attempt=attempt_idx + 1,
                duration_ms=round(exec_ms, 2),
                row_count=exec_result.row_count,
                truncated=exec_result.truncated,
                passed=True,
            )

            # --- Success ---
            total_ms = (time.monotonic() - start_total) * 1000
            trace.attempts.append(
                AttemptLog(
                    **{**attempt_log.__dict__, "valid": True, "duration_ms": exec_ms}
                )
            )
            trace.outcome = "success"
            trace.total_duration_ms = total_ms
            trace.row_count = exec_result.row_count

            total_cost = compute_cost(
                self.settings.llm_model,
                total_prompt_tokens,
                total_completion_tokens,
            )
            outcome = "success"

            log_event(
                logger,
                logging.INFO,
                ev.QUERY_COMPLETED,
                attempts=len(trace.attempts),
                total_duration_ms=round(total_ms, 2),
                row_count=exec_result.row_count,
                columns=exec_result.columns,
                truncated=exec_result.truncated,
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                estimated_cost_usd=total_cost,
                outcome=outcome,
            )
            log_event(
                logger,
                logging.INFO,
                ev.PERF_REQUEST_SUMMARY,
                total_duration_ms=round(total_ms, 2),
                llm_duration_ms_total=round(llm_ms_total, 2),
                validation_duration_ms_total=round(val_ms_total, 2),
                execution_duration_ms_total=round(exec_ms_total, 2),
                overhead_duration_ms=round(
                    total_ms - llm_ms_total - val_ms_total - exec_ms_total, 2
                ),
                attempts=len(trace.attempts),
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                estimated_cost_usd=total_cost,
                outcome=outcome,
            )

            if self.metrics:
                self.metrics.record_request_completed(
                    outcome="success",
                    latency_ms=total_ms,
                    llm_ms=llm_ms_total,
                    val_ms=val_ms_total,
                    exec_ms=exec_ms_total,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    cost_usd=total_cost,
                    attempts=len(trace.attempts),
                    model=self.settings.llm_model,
                )

            result = QueryResult(
                session_id=session_id,
                sql=validated.sql,
                columns=exec_result.columns,
                rows=exec_result.rows,
                row_count=exec_result.row_count,
                truncated=exec_result.truncated,
                attempts=len(trace.attempts),
                latency_ms=total_ms,
            )

            if session_id:
                self.session_store.append(
                    session_id,
                    Turn(
                        question=question,
                        sql=validated.sql,
                        columns=exec_result.columns,
                        row_count=exec_result.row_count,
                    ),
                )
                log_event(
                    logger,
                    logging.DEBUG,
                    ev.PERF_SESSION_SIZE,
                    turns_stored=len(self.session_store.get(session_id)),
                )

            return result

        # --- Repair exhausted ---
        total_ms = (time.monotonic() - start_total) * 1000
        outcome = "repair_exhausted"

        log_event(
            logger,
            logging.ERROR,
            ev.QUERY_FAILED,
            attempts=len(trace.attempts),
            total_duration_ms=round(total_ms, 2),
            error_type="RepairExhausted",
            last_error_hash=hash_text(last_error),
            outcome=outcome,
        )
        log_event(
            logger,
            logging.ERROR,
            ev.ERROR_REPAIR_EXHAUSTED,
            attempts=len(trace.attempts),
            last_error_hash=hash_text(last_error),
        )
        log_event(
            logger,
            logging.INFO,
            ev.PERF_REQUEST_SUMMARY,
            total_duration_ms=round(total_ms, 2),
            llm_duration_ms_total=round(llm_ms_total, 2),
            validation_duration_ms_total=round(val_ms_total, 2),
            execution_duration_ms_total=round(exec_ms_total, 2),
            overhead_duration_ms=round(
                total_ms - llm_ms_total - val_ms_total - exec_ms_total, 2
            ),
            attempts=len(trace.attempts),
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            estimated_cost_usd=compute_cost(
                self.settings.llm_model, total_prompt_tokens, total_completion_tokens
            ),
            outcome=outcome,
        )

        if self.metrics:
            exhausted_cost = compute_cost(
                self.settings.llm_model, total_prompt_tokens, total_completion_tokens
            )
            self.metrics.record_repair_exhausted()
            self.metrics.record_request_completed(
                outcome="repair_exhausted",
                latency_ms=total_ms,
                llm_ms=llm_ms_total,
                val_ms=val_ms_total,
                exec_ms=exec_ms_total,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                cost_usd=exhausted_cost,
                attempts=len(trace.attempts),
                model=self.settings.llm_model,
            )

        raise RepairExhausted(last_sql=sql, last_error=last_error)
