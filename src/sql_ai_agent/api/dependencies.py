from __future__ import annotations

from fastapi import Request

from sql_ai_agent.agent.sql_agent import SqlAgent
from sql_ai_agent.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_engine(request: Request) -> object:
    return request.app.state.engine


def get_agent(request: Request) -> SqlAgent:
    return request.app.state.agent  # type: ignore[no-any-return]


def get_session_store(request: Request) -> object:
    return request.app.state.session_store
