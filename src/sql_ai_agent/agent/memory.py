from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Protocol

from sql_ai_agent.domain.models import Turn


class SessionStore(Protocol):
    def get(self, session_id: str) -> list[Turn]: ...
    def append(self, session_id: str, turn: Turn) -> None: ...
    def clear(self, session_id: str) -> None: ...


class _SessionData:
    __slots__ = ("turns", "last_access")

    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.last_access: float = time.monotonic()


class InMemorySessionStore:
    """Thread-safe in-memory session store with TTL and LRU eviction."""

    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_turns: int = 5,
        max_sessions: int = 1000,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, _SessionData] = OrderedDict()
        self._lock = threading.Lock()

    def _evict_expired(self) -> None:
        """Remove sessions whose TTL has elapsed (must be called under lock)."""
        now = time.monotonic()
        expired = [
            sid
            for sid, data in self._sessions.items()
            if now - data.last_access > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]

    def _ensure_capacity(self) -> None:
        """Evict LRU sessions when at capacity (must be called under lock)."""
        while len(self._sessions) >= self._max_sessions:
            self._sessions.popitem(last=False)

    def _touch(self, session_id: str) -> _SessionData:
        """Return existing session data, moving it to MRU position."""
        data = self._sessions.pop(session_id)
        data.last_access = time.monotonic()
        self._sessions[session_id] = data
        return data

    def get(self, session_id: str) -> list[Turn]:
        with self._lock:
            self._evict_expired()
            if session_id not in self._sessions:
                return []
            return list(self._touch(session_id).turns)

    def append(self, session_id: str, turn: Turn) -> None:
        with self._lock:
            self._evict_expired()
            if session_id not in self._sessions:
                self._ensure_capacity()
                self._sessions[session_id] = _SessionData()
            data = self._touch(session_id)
            data.turns.append(turn)
            if len(data.turns) > self._max_turns:
                data.turns = data.turns[-self._max_turns :]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
