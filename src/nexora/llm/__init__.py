"""Language model providers behind one interface (see base.py)."""

from __future__ import annotations

from nexora.config import Settings
from nexora.llm.base import LLMError, LLMProvider, LLMResult
from nexora.llm.scripted import ScriptedProvider

__all__ = ["LLMError", "LLMProvider", "LLMResult", "ScriptedProvider", "build_provider"]


def _secret(value) -> str:  # noqa: ANN001
    return value.get_secret_value() if value else ""


def build_provider(settings: Settings) -> LLMProvider:
    mistral_key = _secret(settings.mistral_api_key)
    gemini_key = _secret(settings.gemini_api_key)
    choice = settings.llm_provider
    if choice == "auto":
        choice = "mistral" if mistral_key else "gemini" if gemini_key else "scripted"
    if choice == "scripted":
        return ScriptedProvider()
    if choice == "mistral":
        if not mistral_key:
            raise ValueError("NEXORA_LLM_PROVIDER=mistral needs MISTRAL_API_KEY.")
        from nexora.llm.mistral import MistralProvider

        return MistralProvider(
            mistral_key, settings.mistral_model, settings.llm_timeout_s, settings.llm_max_attempts
        )
    if not gemini_key:
        raise ValueError("NEXORA_LLM_PROVIDER=gemini needs GEMINI_API_KEY.")
    from nexora.llm.gemini import GeminiProvider, make_client

    client = make_client(gemini_key, settings.llm_timeout_s, settings.llm_max_attempts)
    return GeminiProvider(client, settings.gemini_model)
