from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

# stdlib LogRecord attributes that should NOT be forwarded as custom fields
_STDLIB_KEYS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Forward every custom field injected via extra={...}
        for key, value in record.__dict__.items():
            if key not in _STDLIB_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _HumanFormatter(logging.Formatter):
    _FMT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(event)s %(message)s"
    _DEFAULTS = {"request_id": "-", "event": ""}

    def format(self, record: logging.LogRecord) -> str:
        for key, default in self._DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, default)
        return super().format(record)


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "json",
) -> None:
    handler = logging.StreamHandler()
    if fmt == "human":
        handler.setFormatter(_HumanFormatter(_HumanFormatter._FMT))
    else:
        handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
