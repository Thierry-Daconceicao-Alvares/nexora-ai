"""Gemini provider: one structured-output call with a timeout and bounded retries.

The SDK retries timeouts and server errors itself (exponential backoff). Every
remaining failure becomes an LLMError, so the caller records the analysis as
unavailable instead of failing the request. Provider messages are logged on the
server, never returned to API callers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from nexora.llm.base import LLMError, LLMResult

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504]


def make_client(api_key: str, timeout_s: float, max_attempts: int) -> genai.Client:
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout_s * 1000),
            retry_options=types.HttpRetryOptions(
                attempts=max_attempts,
                initial_delay=2.0,
                max_delay=20.0,
                exp_base=2.0,
                jitter=1.0,
                http_status_codes=RETRYABLE_STATUS_CODES,
            ),
        ),
    )


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self.model = model

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        start = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=user, config=config
            )
        except genai_errors.APIError as error:
            logger.warning("Gemini call failed: HTTP %s %s", error.code, error.message)
            raise LLMError(f"Gemini returned HTTP {error.code}.") from error
        except Exception as error:  # network errors and timeouts of the HTTP client
            logger.warning("Gemini call failed: %s", error.__class__.__name__)
            raise LLMError(f"Gemini call failed ({error.__class__.__name__}).") from error
        latency_ms = (time.perf_counter() - start) * 1000

        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned an empty answer (blocked or cut off).")
        usage = getattr(response, "usage_metadata", None)
        return LLMResult(
            text=text,
            model=getattr(response, "model_version", None) or self.model,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(
                (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if usage
                else 0
            ),
            latency_ms=round(latency_ms, 1),
        )
