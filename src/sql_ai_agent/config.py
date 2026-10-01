from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource


class _FlexibleDotEnvSource(DotEnvSettingsSource):
    """DotEnv source that accepts comma-separated strings for list fields."""

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except Exception:
            if isinstance(value, str) and "," in value:
                return [v.strip() for v in value.split(",") if v.strip()]
            raise


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SQL AI Agent"
    environment: str = "development"

    database_url: str = "sqlite:///file:data/boutique.db?mode=ro&uri=true"
    max_rows: int = 1000
    query_timeout_seconds: float = 30.0

    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_fallback_model: str | None = None
    llm_temperature: float = 0.0
    llm_timeout: int = 60
    llm_max_retries: int = 2

    max_repairs: int = 2

    skills_dir: Path = Path("skills")
    prompts_dir: Path = Path("src/sql_ai_agent/llm/prompts")

    distinct_values_max: int = 25
    context_max_tokens: int = 4000

    session_ttl_seconds: int = 1800
    session_max_turns: int = 5
    session_max_count: int = 1000

    log_format: str = "json"

    guardrails_dir: Path | None = None

    allowed_tables: list[str] = Field(
        default_factory=lambda: [
            "clients",
            "commandes",
            "lignes_commande",
            "produits",
            "categories",
            "avis",
        ]
    )

    @field_validator("allowed_tables", mode="before")
    @classmethod
    def _parse_allowed_tables(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [t.strip() for t in v.split(",") if t.strip()]
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        flex_dotenv = _FlexibleDotEnvSource(
            settings_cls,
            env_file=cls.model_config.get("env_file"),
            env_file_encoding=cls.model_config.get("env_file_encoding"),
        )
        return (init_settings, env_settings, flex_dotenv, file_secret_settings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
