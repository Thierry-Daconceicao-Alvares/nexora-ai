"""Recorded answers for the public demo: recorded once, replayed by request
reference, anything else analysed by the fallback provider."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nexora import demo
from nexora.api.app import create_app
from nexora.llm import ScriptedProvider
from nexora.llm.base import LLMResult
from nexora.llm.replay import RecordingProvider, ReplayProvider, request_ref
from tests.conftest import auth

PROMPT = '<untrusted_request>\n{"external_ref": "PR-2026-04101"}\n</untrusted_request>'


class Model:
    name, model = "mistral", "ministral-14b-latest"

    def generate(self, system, user, schema):
        return LLMResult('{"answer": 1}', self.model, 100, 20, 1500.0)


def test_the_request_reference_is_read_from_the_prompt():
    assert request_ref(PROMPT) == "PR-2026-04101"
    assert request_ref("no request here") is None


def test_recorded_answers_are_replayed_and_labelled(tmp_path):
    recorder = RecordingProvider(Model())
    recorder.generate("s", PROMPT, {})
    path = tmp_path / "recorded.jsonl"
    recorder.save(path)
    assert json.loads(path.read_text())["model"] == "ministral-14b-latest"

    replay = ReplayProvider.from_file(path, fallback=ScriptedProvider())
    answer = replay.generate("s", PROMPT, {})
    assert (answer.text, answer.provider, answer.model) == (
        '{"answer": 1}',
        "recorded",
        "ministral-14b-latest",
    )
    other = replay.generate("s", PROMPT.replace("04101", "09999"), {})
    assert other.provider == "scripted"


def test_the_demo_data_is_seeded_once_with_replayed_analyses(tmp_path, settings):
    recordings = {
        "PR-2026-04101": {
            "external_ref": "PR-2026-04101",
            "provider": "mistral",
            "model": "ministral-14b-latest",
            "input_tokens": 1,
            "output_tokens": 1,
            "latency_ms": 1.0,
            "text": json.dumps(
                {
                    "summary": "Maintenance requests ball bearings.",
                    "spend_category": "spare_parts",
                    "findings": [],
                    "missing_information": [],
                    "recommendation": {
                        "action": "approve",
                        "rationale": "No finding.",
                        "citations": ["NX-PUR-002 §2"],
                    },
                    "insufficient_evidence": False,
                    "instruction_like_text_seen": False,
                }
            ),
        }
    }
    provider = ReplayProvider(recordings, fallback=ScriptedProvider())
    clock = {"now": demo.ANCHOR}
    client = TestClient(create_app(settings, clock=lambda: clock["now"], provider=provider))
    assert demo.seed(client, clock, log=lambda _: None) == len(demo.SCENARIOS)
    assert demo.seed(client, clock, log=lambda _: None) == 0  # never twice
    rows = client.get("/requests", params={"limit": 50}, headers=auth("karim")).json()
    first = next(r for r in rows if r["external_ref"] == "PR-2026-04101")
    analysis = client.get(f"/requests/{first['id']}", headers=auth("karim")).json()["analysis"]
    assert (analysis["provider"], analysis["model"]) == ("recorded", "ministral-14b-latest")
    assert analysis["verification"] == "verified"
    other = next(r for r in rows if r["external_ref"] == "PR-2026-04102")
    detail = client.get(f"/requests/{other['id']}", headers=auth("karim")).json()
    assert detail["analysis"]["provider"] == "scripted"
