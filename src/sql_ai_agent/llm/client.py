from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from sql_ai_agent.config import Settings
from sql_ai_agent.domain.errors import LLMUnavailable


def build_chat_model(settings: Settings) -> Runnable[Any, Any]:
    if not settings.llm_api_key:
        raise LLMUnavailable("LLM_API_KEY non configurée.")

    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "temperature": settings.llm_temperature,
        "timeout": settings.llm_timeout,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url

    primary: BaseChatModel = ChatOpenAI(**kwargs)

    if (
        settings.llm_fallback_model
        and settings.llm_fallback_model != settings.llm_model
    ):
        fallback_kwargs = {**kwargs, "model": settings.llm_fallback_model}
        fallback: BaseChatModel = ChatOpenAI(**fallback_kwargs)
        return primary.with_fallbacks([fallback])

    return primary
