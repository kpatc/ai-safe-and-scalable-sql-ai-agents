from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


def _pct(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


@dataclass
class MetricsStore:
    """Thread-safe in-memory metrics store — reset on restart."""

    # ── internals ──────────────────────────────────────────────────────────
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    started_at: float = field(default_factory=time.time, init=False)

    # ── request counters ───────────────────────────────────────────────────
    total_requests: int = field(default=0, init=False)
    successful_requests: int = field(default=0, init=False)
    failed_requests: int = field(default=0, init=False)
    unanswerable_requests: int = field(default=0, init=False)
    guardrails_blocked: int = field(default=0, init=False)

    # ── latency samples (keep last 1 000) ─────────────────────────────────
    _latency_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), init=False, repr=False
    )
    _llm_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), init=False, repr=False
    )
    _val_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), init=False, repr=False
    )
    _exec_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), init=False, repr=False
    )

    # ── tokens / cost ──────────────────────────────────────────────────────
    total_prompt_tokens: int = field(default=0, init=False)
    total_completion_tokens: int = field(default=0, init=False)
    total_cost_usd: float = field(default=0.0, init=False)

    # ── validation ─────────────────────────────────────────────────────────
    validation_failures: int = field(default=0, init=False)
    _val_by_rule: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    # ── repair / recovery ──────────────────────────────────────────────────
    repair_attempts: int = field(default=0, init=False)
    repair_exhausted: int = field(default=0, init=False)
    _attempts_per_req: deque[int] = field(
        default_factory=lambda: deque(maxlen=1000), init=False, repr=False
    )

    # ── model usage ────────────────────────────────────────────────────────
    _model_calls: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    # ── error types ────────────────────────────────────────────────────────
    _errors_by_type: dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )

    # ── time series (minute buckets, last 60 min) ─────────────────────────
    _rpm: deque[tuple[int, int]] = field(
        default_factory=lambda: deque(maxlen=60), init=False, repr=False
    )

    # ── public mutation API ────────────────────────────────────────────────

    def record_request_completed(
        self,
        *,
        outcome: str,
        latency_ms: float,
        llm_ms: float,
        val_ms: float,
        exec_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        attempts: int,
        model: str = "",
    ) -> None:
        with self._lock:
            self.total_requests += 1
            if outcome == "success":
                self.successful_requests += 1
            elif outcome == "unanswerable":
                self.unanswerable_requests += 1
            else:
                self.failed_requests += 1

            self._latency_ms.append(latency_ms)
            self._llm_ms.append(llm_ms)
            self._val_ms.append(val_ms)
            self._exec_ms.append(exec_ms)

            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_cost_usd += cost_usd

            self._attempts_per_req.append(attempts)

            if model:
                self._model_calls[model] = self._model_calls.get(model, 0) + 1

            # minute bucket
            minute = int(time.time() // 60)
            if self._rpm and self._rpm[-1][0] == minute:
                _m, _c = self._rpm.pop()
                self._rpm.append((_m, _c + 1))
            else:
                self._rpm.append((minute, 1))

    def record_validation_failure(self, rule: str) -> None:
        with self._lock:
            self.validation_failures += 1
            self._val_by_rule[rule] = self._val_by_rule.get(rule, 0) + 1

    def record_repair_attempt(self) -> None:
        with self._lock:
            self.repair_attempts += 1

    def record_repair_exhausted(self) -> None:
        with self._lock:
            self.repair_exhausted += 1

    def record_guardrails_blocked(self) -> None:
        with self._lock:
            self.guardrails_blocked += 1

    def record_error(self, error_type: str) -> None:
        with self._lock:
            self._errors_by_type[error_type] = (
                self._errors_by_type.get(error_type, 0) + 1
            )

    # ── snapshot ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lat = list(self._latency_ms)
            llm = list(self._llm_ms)
            val = list(self._val_ms)
            exc = list(self._exec_ms)
            att = list(self._attempts_per_req)
            rpm = list(self._rpm)
            vfr = dict(self._val_by_rule)
            err = dict(self._errors_by_type)
            mdl = dict(self._model_calls)

            total = self.total_requests
            success = self.successful_requests
            failed = self.failed_requests
            unans = self.unanswerable_requests
            gblk = self.guardrails_blocked
            pt = self.total_prompt_tokens
            ct = self.total_completion_tokens
            cost = self.total_cost_usd
            val_f = self.validation_failures
            rep_a = self.repair_attempts
            rep_e = self.repair_exhausted
            started = self.started_at

        uptime = time.time() - started
        total_safe = total or 1  # avoid /0

        # throughput: requests per minute over last window
        now_min = int(time.time() // 60)
        rpm_series = [{"minute": now_min - (now_min - m), "count": c} for m, c in rpm]

        return {
            "uptime_seconds": round(uptime),
            "requests": {
                "total": total,
                "successful": success,
                "failed": failed,
                "unanswerable": unans,
                "guardrails_blocked": gblk,
                "success_rate_pct": round(success / total_safe * 100, 1),
                "error_rate_pct": round(failed / total_safe * 100, 1),
                "unanswerable_rate_pct": round(unans / total_safe * 100, 1),
            },
            "latency": {
                "p50_ms": round(_pct(lat, 50), 1),
                "p95_ms": round(_pct(lat, 95), 1),
                "p99_ms": round(_pct(lat, 99), 1),
                "avg_ms": round(statistics.mean(lat), 1) if lat else 0.0,
            },
            "llm": {
                "response_p50_ms": round(_pct(llm, 50), 1),
                "response_p95_ms": round(_pct(llm, 95), 1),
                "avg_ms": round(statistics.mean(llm), 1) if llm else 0.0,
            },
            "execution": {
                "p50_ms": round(_pct(exc, 50), 1),
                "p95_ms": round(_pct(exc, 95), 1),
            },
            "validation": {
                "p50_ms": round(_pct(val, 50), 1),
                "failures": val_f,
                "failure_rate_pct": round(val_f / total_safe * 100, 1),
                "by_rule": vfr,
            },
            "tokens": {
                "prompt": pt,
                "completion": ct,
                "total": pt + ct,
                "avg_per_request": round((pt + ct) / total_safe),
            },
            "cost": {
                "total_usd": round(cost, 6),
                "avg_per_request_usd": round(cost / total_safe, 6),
            },
            "repair": {
                "attempts": rep_a,
                "exhausted": rep_e,
                "recovered": max(0, rep_a - rep_e),
                "avg_attempts_per_request": round(statistics.mean(att), 2)
                if att
                else 1.0,
                "multi_attempt_rate_pct": round(
                    sum(1 for a in att if a > 1) / len(att) * 100, 1
                )
                if att
                else 0.0,
                "recovery_rate_pct": round(max(0, rep_a - rep_e) / rep_a * 100, 1)
                if rep_a > 0
                else 0.0,
            },
            "model_distribution": mdl,
            "errors_by_type": err,
            "throughput_per_minute": rpm_series,
        }
