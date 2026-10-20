"""Language model providers behind one interface (see base.py)."""

from __future__ import annotations

from nexora.config import Settings
from nexora.llm.base import LLMError, LLMProvider, LLMResult
from nexora.llm.scripted import ScriptedProvider

__all__ = ["LLMError", "LLMProvider", "LLMResult", "ScriptedProvider", "build_provider"]


def build_provider(settings: Settings) -> LLMProvider:
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    choice = settings.llm_provider
    if choice == "auto":
        choice = "gemini" if key else "scripted"
    if choice == "scripted":
        return ScriptedProvider()
    if not key:
        raise ValueError("NEXORA_LLM_PROVIDER=gemini needs GEMINI_API_KEY.")
    from nexora.llm.gemini import GeminiProvider, make_client

    client = make_client(key, settings.llm_timeout_s, settings.llm_max_attempts)
    return GeminiProvider(client, settings.gemini_model)
