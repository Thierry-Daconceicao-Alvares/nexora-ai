"""Recorded model answers, for the public demo.

The public demo must not spend a model quota or expose a key, yet it should
show what a real model answers. The answers of a real model for the demo
requests are recorded once (scripts/seed_demo.py --record) and replayed:
ReplayProvider returns the recorded answer for a known request and asks its
fallback provider (the scripted stand-in, or a real model when a key is set)
for any other one. Every replayed answer goes through the same checks in code
as a live one, and is labelled with the provider "recorded".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from nexora.config import ROOT
from nexora.llm.base import LLMProvider, LLMResult

RECORDINGS = ROOT / "data" / "demo" / "recorded_analyses.jsonl"
_REQUEST = re.compile(r"<untrusted_request>\n(.*?)\n</untrusted_request>", re.DOTALL)


def request_ref(prompt: str) -> str | None:
    match = _REQUEST.search(prompt)
    if not match:
        return None
    try:
        return json.loads(match.group(1)).get("external_ref")
    except ValueError:
        return None


class RecordingProvider:
    """Passes every call to `inner` and keeps its answers by request reference."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name, self.model = inner.name, inner.model
        self.recorded: dict[str, dict[str, Any]] = {}

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        result = self.inner.generate(system, user, schema)
        ref = request_ref(user)
        if ref:
            self.recorded[ref] = {
                "external_ref": ref,
                "provider": self.inner.name,
                "model": result.model,
                "text": result.text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for ref in sorted(self.recorded):
                handle.write(json.dumps(self.recorded[ref], ensure_ascii=False) + "\n")


class ReplayProvider:
    name = "recorded"

    def __init__(self, recordings: dict[str, dict[str, Any]], fallback: LLMProvider) -> None:
        self.recordings = recordings
        self.fallback = fallback
        self.model = fallback.model

    @classmethod
    def from_file(cls, path: Path, fallback: LLMProvider) -> ReplayProvider:
        recordings: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    recordings[item["external_ref"]] = item
        return cls(recordings, fallback)

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        item = self.recordings.get(request_ref(user) or "")
        if item is None:
            result = self.fallback.generate(system, user, schema)
            return LLMResult(
                text=result.text,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                provider=self.fallback.name,
            )
        return LLMResult(
            text=item["text"],
            model=item["model"],
            input_tokens=item["input_tokens"],
            output_tokens=item["output_tokens"],
            latency_ms=item["latency_ms"],
            provider="recorded",
        )
