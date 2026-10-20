"""What the analysis service needs from a language model provider.

The business code only sees this interface: a provider receives a system
prompt, a user prompt and the JSON schema of the expected answer, and returns
text plus usage figures. It holds no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    """The provider could not produce an answer (timeout, quota, server error,
    rejected key). The analysis is then recorded as unavailable."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # thinking tokens included: they are billed as output
    latency_ms: float = 0.0
    # Set by a provider that delegates (replay of recorded answers): who answered.
    provider: str | None = None


class LLMProvider(Protocol):
    name: str  # "gemini", "scripted"
    model: str

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult: ...
