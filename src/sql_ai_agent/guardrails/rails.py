from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nemoguardrails import LLMRails

from sql_ai_agent.config import Settings
from sql_ai_agent.domain.errors import ValidationRejected
from sql_ai_agent.observability import events as ev
from sql_ai_agent.observability.logger import hash_text, log_event

logger = logging.getLogger(__name__)

_PASS_SENTINEL = "GUARDRAILS_PASS"


def load_rails(settings: Settings) -> LLMRails | None:
    """Load NeMo Guardrails from config directory. Returns None if unavailable."""
    guardrails_dir = settings.guardrails_dir
    if guardrails_dir is None or not guardrails_dir.exists():
        return None

    try:
        import nest_asyncio
        from langchain_openai import ChatOpenAI
        from nemoguardrails import LLMRails, RailsConfig

        nest_asyncio.apply()

        config = RailsConfig.from_path(str(guardrails_dir))

        if not settings.llm_api_key:
            logger.warning("No LLM API key — guardrails run in pattern-only mode")
            return LLMRails(config)

        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "api_key": settings.llm_api_key,
            "temperature": 0.0,
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url

        llm = ChatOpenAI(**kwargs)
        return LLMRails(config, llm=llm)
    except Exception:
        logger.exception("Failed to load guardrails — proceeding without rails")
        return None


async def _check_input_async(rails: LLMRails, question: str) -> str | None:
    """Return blocking reason if blocked, None if allowed."""
    response = await rails.generate_async(
        messages=[{"role": "user", "content": question}]
    )
    content: str = (
        response.get("content", "") if isinstance(response, dict) else str(response)
    )
    if _PASS_SENTINEL in content:
        return None
    return content.strip() or None


def check_input(rails: LLMRails, question: str) -> None:
    """Raise ValidationRejected if the question is blocked by guardrails."""
    import nest_asyncio

    nest_asyncio.apply()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    reason = loop.run_until_complete(_check_input_async(rails, question))
    if reason is not None:
        log_event(
            logger,
            logging.WARNING,
            ev.QUERY_GUARDRAILS_BLOCKED,
            block_reason_hash=hash_text(reason),
        )
        raise ValidationRejected(
            reason="Question bloquée par les guardrails de sécurité."
        )
