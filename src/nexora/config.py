"""Settings, read from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXORA_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{ROOT / 'nexora.db'}"
    rules_path: Path = ROOT / "config" / "rules.yaml"
    users_path: Path = ROOT / "config" / "demo_users.yaml"
    synthetic_dir: Path = ROOT / "data" / "synthetic"
    # Requests submitted per actor and minute before a 429 (basic protection).
    rate_limit_per_minute: int = 60

    # AI analysis. "auto" uses Gemini when a key is set, otherwise the scripted
    # stand-in (no model, no network), so the project runs without an account.
    knowledge_base_dir: Path = ROOT / "data" / "knowledge_base"
    llm_provider: Literal["auto", "gemini", "scripted"] = "auto"
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("NEXORA_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 30.0
    # HTTP attempts per model call (timeouts, rate limits and server errors).
    llm_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
