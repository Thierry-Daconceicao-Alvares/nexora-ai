"""The Gemini provider against a stub client: request shape, usage figures and
error translation. No network call is made."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from nexora.llm.base import LLMError
from nexora.llm.gemini import GeminiProvider


class StubModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        if self.error:
            raise self.error
        return self.response


def provider_with(**kwargs) -> tuple[GeminiProvider, StubModels]:
    models = StubModels(**kwargs)
    return GeminiProvider(SimpleNamespace(models=models), "gemini-3.5-flash-lite"), models


def response(text='{"ok": true}', **usage):
    metadata = SimpleNamespace(
        prompt_token_count=usage.get("prompt", 1200),
        candidates_token_count=usage.get("output", 300),
        thoughts_token_count=usage.get("thinking", 100),
    )
    return SimpleNamespace(
        text=text, usage_metadata=metadata, model_version="gemini-3.5-flash-lite-001"
    )


def test_a_structured_call_with_the_schema_and_the_system_prompt():
    provider, models = provider_with(response=response())
    result = provider.generate("system text", "user text", {"type": "object"})
    model, contents, config = models.calls[0]
    assert (model, contents) == ("gemini-3.5-flash-lite", "user text")
    assert config.system_instruction == "system text"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert result.text == '{"ok": true}'
    assert result.model == "gemini-3.5-flash-lite-001"
    assert (result.input_tokens, result.output_tokens) == (1200, 400)  # thinking billed


def test_api_errors_become_llm_errors():
    error = genai_errors.APIError(503, {"error": {"message": "overloaded", "code": 503}})
    provider, _ = provider_with(error=error)
    with pytest.raises(LLMError, match="HTTP 503"):
        provider.generate("s", "u", {})


def test_network_errors_become_llm_errors():
    provider, _ = provider_with(error=TimeoutError())
    with pytest.raises(LLMError, match="TimeoutError"):
        provider.generate("s", "u", {})


def test_an_empty_answer_is_an_error():
    provider, _ = provider_with(response=response(text=""))
    with pytest.raises(LLMError, match="empty"):
        provider.generate("s", "u", {})
