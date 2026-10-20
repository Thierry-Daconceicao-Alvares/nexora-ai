"""Settings, read from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
