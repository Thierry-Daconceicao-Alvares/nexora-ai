"""Mistral provider: one chat completion with a strict JSON schema.

Called over HTTPS with httpx (no SDK): POST /v1/chat/completions with
`response_format = {"type": "json_schema", ...}`. Timeouts, rate limits (429)
and server errors are retried with exponential backoff, a bounded number of
times; every remaining failure becomes an LLMError, so the request is still
checked and routed with the analysis marked unavailable. Provider messages are
logged on the server, never returned to API callers.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

import httpx

from nexora.llm.base import LLMError, LLMResult

logger = logging.getLogger(__name__)

API_URL = "https://api.mistral.ai/v1/chat/completions"
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_sleep = time.sleep  # replaced in the tests


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strict mode wants every object closed: no property outside the schema."""
    schema = copy.deepcopy(schema)

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(schema)
    return schema


class MistralProvider:
    name = "mistral"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._max_attempts = max(1, max_attempts)
        self._client = client or httpx.Client(timeout=timeout_s)
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "purchase_request_analysis",
                    "schema": strict_schema(schema),
                    "strict": True,
                },
            },
        }
        start = time.perf_counter()
        response = self._post(body)
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMError("Mistral returned an answer in an unexpected format.") from error
        if not text:
            raise LLMError("Mistral returned an empty answer.")
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=data.get("model") or self.model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=round(latency_ms, 1),
        )

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        for attempt in range(1, self._max_attempts + 1):
            last = attempt == self._max_attempts
            try:
                response = self._client.post(API_URL, json=body, headers=self._headers)
            except httpx.TimeoutException as error:
                logger.warning("Mistral call timed out (attempt %d)", attempt)
                if last:
                    raise LLMError("Mistral did not answer in time.") from error
            except httpx.TransportError as error:
                logger.warning("Mistral call failed: %s", error.__class__.__name__)
                if last:
                    raise LLMError(f"Mistral call failed ({error.__class__.__name__}).") from error
            else:
                if response.status_code == 200:
                    return response
                logger.warning(
                    "Mistral returned HTTP %s: %s", response.status_code, response.text[:300]
                )
                if response.status_code == 401:
                    raise LLMError("Mistral rejected the API key. Check MISTRAL_API_KEY.")
                if response.status_code == 403:
                    raise LLMError(
                        "Mistral refused the call (HTTP 403): the model may not be "
                        "included in the plan of this key."
                    )
                if response.status_code not in RETRYABLE_STATUS_CODES or last:
                    raise LLMError(f"Mistral returned HTTP {response.status_code}.")
                wait = response.headers.get("retry-after")
                if wait and wait.replace(".", "", 1).isdigit():
                    _sleep(min(float(wait), 20.0))
                    continue
            _sleep(min(2.0 * 2 ** (attempt - 1), 20.0))
        raise LLMError("Mistral call failed.")  # pragma: no cover - loop always returns
