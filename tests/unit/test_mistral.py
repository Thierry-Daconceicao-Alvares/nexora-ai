"""The Mistral provider against a mock HTTP transport (no network), and the
choice of provider from the settings."""

from __future__ import annotations

import json

import httpx
import pytest

from nexora.config import Settings
from nexora.llm import ScriptedProvider, build_provider
from nexora.llm import mistral as mistral_module
from nexora.llm.base import LLMError
from nexora.llm.mistral import API_URL, MistralProvider, strict_schema
from nexora.services.analysis import response_schema

OK = {
    "model": "mistral-small-2603",
    "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
    "usage": {"prompt_tokens": 1500, "completion_tokens": 350, "total_tokens": 1850},
}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    waits = []
    monkeypatch.setattr(mistral_module, "_sleep", waits.append)
    return waits


def provider_answering(*replies):
    """Replies are (status, body) pairs or exceptions, returned in turn."""
    sent = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MistralProvider("test-key", "mistral-small-latest", client=client), sent


def test_a_strict_json_schema_completion():
    provider, sent = provider_answering((200, OK))
    result = provider.generate("system text", "user text", {"type": "object", "properties": {}})
    request = sent[0]
    body = json.loads(request.content)
    assert str(request.url) == API_URL
    assert request.headers["Authorization"] == "Bearer test-key"
    assert body["model"] == "mistral-small-latest"
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert result.text == '{"ok": true}'
    assert result.model == "mistral-small-2603"
    assert (result.input_tokens, result.output_tokens) == (1500, 350)


def test_the_analysis_schema_is_closed_for_strict_mode():
    schema = strict_schema(response_schema())
    assert schema["additionalProperties"] is False
    recommendation = schema["properties"]["recommendation"]
    assert recommendation["additionalProperties"] is False
    assert schema["properties"]["findings"]["items"]["additionalProperties"] is False
    assert "additionalProperties" not in response_schema()  # the original is untouched


def test_rate_limits_and_server_errors_are_retried(no_waiting):
    provider, sent = provider_answering((429, {}), (503, {}), (200, OK))
    assert provider.generate("s", "u", {}).text == '{"ok": true}'
    assert len(sent) == 3
    assert no_waiting == [2.0, 4.0]


def test_retries_are_bounded():
    provider, sent = provider_answering((503, {}), (503, {}), (503, {}))
    with pytest.raises(LLMError, match="HTTP 503"):
        provider.generate("s", "u", {})
    assert len(sent) == 3


def test_timeouts_are_retried_then_reported():
    timeout = httpx.ReadTimeout("slow")
    provider, sent = provider_answering(timeout, timeout, timeout)
    with pytest.raises(LLMError, match="did not answer in time"):
        provider.generate("s", "u", {})
    assert len(sent) == 3


def test_a_rejected_key_is_not_retried():
    provider, sent = provider_answering((401, {"message": "Unauthorized"}))
    with pytest.raises(LLMError, match="MISTRAL_API_KEY"):
        provider.generate("s", "u", {})
    assert len(sent) == 1


def test_a_model_outside_the_plan_is_reported_as_such():
    provider, sent = provider_answering((403, {"type": "tier_not_allowed"}))
    with pytest.raises(LLMError, match="not be included in the plan"):
        provider.generate("s", "u", {})
    assert len(sent) == 1


def test_an_unexpected_body_is_an_error():
    provider, _ = provider_answering((200, {"choices": []}))
    with pytest.raises(LLMError, match="unexpected format"):
        provider.generate("s", "u", {})


# ------------------------------------------------------------ provider choice


def settings(**keys) -> Settings:
    values = {"llm_provider": "auto", "gemini_api_key": None, "mistral_api_key": None}
    return Settings(**{**values, **keys})


def test_without_a_key_the_scripted_provider_is_used():
    assert isinstance(build_provider(settings()), ScriptedProvider)


def test_mistral_comes_first_when_its_key_is_set():
    provider = build_provider(settings(mistral_api_key="m-key", gemini_api_key="g-key"))
    assert (provider.name, provider.model) == ("mistral", "mistral-small-latest")


def test_gemini_is_used_when_only_its_key_is_set():
    provider = build_provider(settings(gemini_api_key="g-key"))
    assert (provider.name, provider.model) == ("gemini", "gemini-3.5-flash-lite")


@pytest.mark.parametrize(("choice", "key"), [("mistral", "MISTRAL"), ("gemini", "GEMINI")])
def test_a_provider_cannot_be_forced_without_its_key(choice, key):
    with pytest.raises(ValueError, match=f"{key}_API_KEY"):
        build_provider(settings(llm_provider=choice))


def test_mistral_cost_estimate():
    from nexora.llm.costs import estimate_cost_usd

    assert estimate_cost_usd("mistral-small-2603", 1_000_000, 1_000_000) == 0.75
