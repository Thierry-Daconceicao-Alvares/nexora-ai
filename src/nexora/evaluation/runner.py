"""Runs the labelled set through the whole application and measures the ten
acceptance criteria of the product specification.

Everything goes through the HTTP API (in memory), with a simulated clock set
to each request's submission time, on a fresh SQLite database:

1. every request is submitted, then submitted again with the same key;
2. a series of forbidden actions is attempted;
3. every accepted request is decided as a careful reviewer would (the first
   expected recommendation), then by the approver when it reaches her;
4. with fault injection, the set is submitted again to a provider that
   answers outside the schema or fails, on a second fresh database.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import yaml
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.config import ROOT, Settings
from nexora.evaluation import baselines
from nexora.llm.base import LLMError, LLMProvider, LLMResult

DATASET = ROOT / "data" / "evaluation" / "requests.jsonl"
HOLDOUT = ROOT / "data" / "evaluation" / "holdout.jsonl"
PASSAGES = ROOT / "data" / "evaluation" / "acceptable_passages.yaml"
TOKENS = {
    "sophie": "demo-sophie",
    "marc": "demo-marc",
    "karim": "demo-karim",
    "claire": "demo-claire",
    "intake": "demo-intake",
    "admin": "demo-admin",
}
REASONS = {
    "approve": "Checked against the policy: complete and within the rules.",
    "reject": "Not acceptable under the purchasing policy, see the findings.",
    "request_info": "Please complete the request: see the findings listed.",
    "escalate": "Needs the decision of the Head of Procurement.",
}


def load(path: Path = DATASET) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[user]}"}


class FaultyProvider:
    """Wraps a provider and injects faults by request: every 10th answer is
    malformed twice (the analysis becomes unavailable), the next one is
    malformed once (the retry succeeds), the next one times out."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name, self.model = inner.name, inner.model
        self.calls = 0
        self.request = -1
        self.attempt = 0

    def start(self, number: int) -> None:
        self.request, self.attempt = number, 0

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        self.calls += 1
        self.attempt += 1
        kind = self.request % 10
        if kind == 0:
            return LLMResult(text='{"summary": "cut', model=self.model)
        if kind == 1 and self.attempt == 1:
            return LLMResult(text="I cannot answer in JSON.", model=self.model)
        if kind == 2:
            raise LLMError("Simulated timeout.")
        return self.inner.generate(system, user, schema)


@dataclass
class Run:
    rows: list[dict[str, Any]] = field(default_factory=list)
    security: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    chaos: list[dict[str, Any]] = field(default_factory=list)
    stored_requests: int = 0
    provider: str = ""
    model: str = ""


def _app(provider: LLMProvider, clock: dict[str, datetime], workdir: Path, name: str):
    settings = Settings(
        database_url=f"sqlite:///{workdir / f'{name}.db'}",
        llm_provider="scripted",
        gemini_api_key=None,
        mistral_api_key=None,
        # The evaluation submits a few hundred requests in a few seconds.
        rate_limit_per_minute=100_000,
    )
    return TestClient(create_app(settings, clock=lambda: clock["now"], provider=provider))


def _findings(body: dict[str, Any]) -> dict[str, str]:
    return {
        c["rule_id"]: c["severity"]
        for c in body.get("checks", [])
        if c["stage"] != "validation" and c["outcome"] != "pass"
    }


def _submit(client: TestClient, record: dict[str, Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    response = client.post(
        "/requests",
        json=record["payload"],
        headers={**auth(record["user"]), "Idempotency-Key": f"eval:{record['id']}"},
    )
    return response, (time.perf_counter() - start) * 1000


def evaluate(
    provider: LLMProvider,
    records: list[dict[str, Any]],
    pause_s: float = 0.0,
    chaos: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> Run:
    run = Run(provider=provider.name, model=provider.model)
    workdir = Path(tempfile.mkdtemp(prefix="nexora-eval-"))
    clock = {"now": datetime.fromisoformat(records[0]["submitted_at"])}
    client = _app(provider, clock, workdir, "main")
    ordered = sorted(records, key=lambda r: r["submitted_at"])

    # 1. Submission, and the same submission again.
    for number, record in enumerate(ordered, start=1):
        clock["now"] = datetime.fromisoformat(record["submitted_at"])
        response, latency = _submit(client, record)
        body = response.json()
        row: dict[str, Any] = {
            "id": record["id"],
            "scenario": record["scenario"],
            "user": record["user"],
            "is_capex": bool(record["payload"].get("is_capex")),
            "catalogue_item": bool(record["payload"].get("item_code")),
            "expected": record["expected"],
            "status_code": response.status_code,
            "latency_ms": round(latency, 1),
            "baseline_declared": baselines.declared(record["payload"]),
            "baseline_keywords": baselines.keywords(record["payload"]),
        }
        if response.status_code == 201:
            analysis = body.get("analysis") or {}
            output = analysis.get("output") or {}
            row |= {
                "request_id": body["id"],
                "version": body["version"],
                "status": body["status"],
                "flags": _findings(body),
                "route": body["route"],
                "analysis_status": analysis.get("status"),
                "verification": analysis.get("verification"),
                "issues": [i["code"] for i in analysis.get("issues", [])],
                "spend_category": output.get("spend_category"),
                "recommendation": (output.get("recommendation") or {}).get("action"),
                "finding_citations": {
                    f["rule_id"]: f["citations"] for f in output.get("findings", [])
                },
                "recommendation_citations": (output.get("recommendation") or {}).get(
                    "citations", []
                ),
                "model": analysis.get("model"),
                "model_latency_ms": analysis.get("latency_ms"),
                "tokens": (analysis.get("input_tokens") or 0)
                + (analysis.get("output_tokens") or 0),
                "cost_usd": analysis.get("estimated_cost_usd"),
                "attempts": analysis.get("attempts"),
                "error": analysis.get("error"),
                "summary": output.get("summary"),
                "rationale": (output.get("recommendation") or {}).get("rationale"),
            }
            replay = client.post(
                "/requests",
                json=record["payload"],
                headers={**auth(record["user"]), "Idempotency-Key": f"eval:{record['id']}"},
            )
            row["replay_status"] = replay.status_code
            row["replay_same_id"] = replay.json().get("id") == body["id"]
        else:
            detail = body.get("detail", {})
            row["error_fields"] = sorted({e.get("field") or "" for e in detail.get("errors", [])})
        run.rows.append(row)
        progress(
            f"{number}/{len(ordered)} {record['id']} {record['scenario']} "
            f"{response.status_code} {row.get('route', '')} {row.get('recommendation', '')}"
        )
        if pause_s:
            time.sleep(pause_s)

    karim = client.get("/requests", params={"limit": 200}, headers=auth("karim")).json()
    run.stored_requests = len(karim)

    # 2. Forbidden actions.
    run.security = _security(client, run.rows, clock)

    # 3. Decisions, and their audit trail.
    run.decisions = _decide(client, run.rows, clock)

    # 4. Fault injection.
    if chaos:
        # Faults are injected around the scripted stand-in: what is measured is
        # the fallback of the application, not the model, and no quota is spent.
        from nexora.llm.scripted import ScriptedProvider

        faulty = FaultyProvider(ScriptedProvider())
        chaos_client = _app(faulty, clock, workdir, "chaos")
        routes = {r["id"]: r.get("route") for r in run.rows}
        for number, record in enumerate(ordered):
            if not record["expected"]["valid"]:
                continue
            faulty.start(number)
            clock["now"] = datetime.fromisoformat(record["submitted_at"])
            response, _ = _submit(chaos_client, record)
            body = response.json()
            analysis = body.get("analysis") or {}
            run.chaos.append(
                {
                    "id": record["id"],
                    "fault": {0: "malformed twice", 1: "malformed once", 2: "timeout"}.get(
                        number % 10, "none"
                    ),
                    "status_code": response.status_code,
                    "status": body.get("status"),
                    "analysis_status": analysis.get("status"),
                    "attempts": analysis.get("attempts"),
                    "route_unchanged": body.get("route") == routes.get(record["id"]),
                }
            )
    return run


def _security(client: TestClient, rows: list[dict[str, Any]], clock: dict) -> list[dict]:
    """Attempts that must all be refused, on requests waiting for review."""
    waiting = [r for r in rows if r.get("status") == "awaiting_review"]
    reviewer_queue = [r for r in waiting]
    attempts: list[dict[str, Any]] = []

    def attempt(name: str, response: Any, expected: int) -> None:
        attempts.append(
            {
                "attempt": name,
                "expected": expected,
                "status": response.status_code,
                "blocked": response.status_code == expected,
            }
        )

    for row in reviewer_queue[:5]:
        url = f"/requests/{row['request_id']}/decisions"
        body = {"action": "approve", "reason": REASONS["approve"], "version": row["version"]}
        owner = row["user"]
        other = "marc" if owner == "sophie" else "sophie"
        attempt(
            "requester approves own request", client.post(url, json=body, headers=auth(owner)), 403
        )
        attempt("another requester approves", client.post(url, json=body, headers=auth(other)), 404)
        attempt(
            "approver decides before the reviewer",
            client.post(url, json=body, headers=auth("claire")),
            403,
        )
        attempt("administrator decides", client.post(url, json=body, headers=auth("admin")), 403)
        attempt(
            "integration service decides", client.post(url, json=body, headers=auth("intake")), 404
        )
        attempt(
            "decision without a reason",
            client.post(url, json={**body, "reason": ""}, headers=auth("karim")),
            422,
        )
        attempt(
            "decision on an outdated version",
            client.post(url, json={**body, "version": row["version"] + 1}, headers=auth("karim")),
            409,
        )
        attempt(
            "unknown action (order)",
            client.post(url, json={**body, "action": "order"}, headers=auth("karim")),
            422,
        )
        attempt(
            "another requester reads the request",
            client.get(f"/requests/{row['request_id']}", headers=auth(other)),
            404,
        )
        attempt("no token", client.post(url, json=body), 401)
    for _ in range(2):
        attempt(
            "requester reads the event feed", client.get("/events", headers=auth("sophie")), 403
        )
        attempt(
            "reviewer reads the integration outbox",
            client.get("/integration/outbox", headers=auth("karim")),
            403,
        )
    return attempts


def _decide(client: TestClient, rows: list[dict[str, Any]], clock: dict) -> list[dict]:
    results = []
    for row in rows:
        if row.get("status") != "awaiting_review":
            continue
        clock["now"] = clock["now"] + timedelta(hours=1)
        expected = row["expected"]["recommendation"] or ["approve"]
        steps = [("karim", expected[0])]
        if row["route"] == "approver" and expected[0] == "approve":
            steps.append(("claire", "approve"))
        if expected[0] == "escalate":
            steps.append(("claire", "reject"))
        for user, action in steps:
            response = client.post(
                f"/requests/{row['request_id']}/decisions",
                json={"action": action, "reason": REASONS[action], "version": row["version"]},
                headers=auth(user),
            )
            results.append(_audit_check(client, row, user, action, response))
    return results


def _audit_check(client: TestClient, row: dict, user: str, action: str, response) -> dict:
    result = {"id": row["id"], "user": user, "action": action, "status": response.status_code}
    if response.status_code != 201:
        result["complete"] = False
        return result
    decision = response.json()["decision"]
    detail = client.get(f"/requests/{row['request_id']}", headers=auth("admin")).json()
    events = [
        e
        for e in detail["audit"]
        if e["type"] == "decision.recorded"
        and e["payload"].get("action") == action
        and e["actor_id"] == decision["actor_id"]
    ]
    payload = events[-1]["payload"] if events else {}
    evidence = payload.get("evidence") or {}
    result["checks"] = {
        "who": bool(events and events[-1]["actor_id"]),
        "when": bool(events and events[-1]["created_at"]),
        "what": payload.get("action") == action,
        "why": len(payload.get("reason", "")) >= 10,
        "version": payload.get("version") == row["version"],
        "evidence": "flags" in evidence and "analysis" in evidence,
        "stored": any(d["id"] == decision["id"] for d in detail["decisions"]),
    }
    result["complete"] = all(result["checks"].values())
    return result


# ------------------------------------------------------------------ metrics


def _acceptable() -> dict[str, Any]:
    return yaml.safe_load(PASSAGES.read_text(encoding="utf-8"))


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def metrics(run: Run) -> dict[str, Any]:
    rows = run.rows
    valid = [r for r in rows if r["expected"]["valid"]]
    invalid = [r for r in rows if not r["expected"]["valid"]]
    accepted = [r for r in rows if r["status_code"] == 201]
    labels = _acceptable()

    # 1. Malformed requests.
    rejected_ok = [
        r
        for r in invalid
        if r["status_code"] == 422
        and set(r["expected"]["errors"]) <= set(r.get("error_fields", []))
    ]
    falsely_rejected = [r["id"] for r in valid if r["status_code"] != 201]

    # 2. Rules and routing. The screen for instructions is measured with the
    # security criterion; the route of a request whose injection the screen
    # missed is then not the expected one, which is counted there too.
    def rule_flags(flags: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in flags.items() if k != "instruction_like_text"}

    rules_ok = [
        r
        for r in accepted
        if rule_flags(r["flags"]) == rule_flags(r["expected"]["flags"])
        and (r["route"] == r["expected"]["route"] or r["scenario"] == "prompt_injection_unseen")
    ]
    rule_failures = [
        {
            "id": r["id"],
            "scenario": r["scenario"],
            "expected": r["expected"]["flags"],
            "got": r["flags"],
            "expected_route": r["expected"]["route"],
            "route": r["route"],
        }
        for r in accepted
        if r not in rules_ok
    ]

    # 3. Idempotency.
    replays_ok = [r for r in accepted if r.get("replay_status") == 200 and r.get("replay_same_id")]

    # 4. Valid end state, normally and with faults.
    end_ok = [
        r
        for r in accepted
        if r["status"] == "awaiting_review" and r["analysis_status"] in ("completed", "unavailable")
    ]
    chaos_ok = [
        c
        for c in run.chaos
        if c["status_code"] == 201
        and c["status"] == "awaiting_review"
        and c["route_unchanged"]
        and c["analysis_status"]
        == ("unavailable" if c["fault"] in ("malformed twice", "timeout") else "completed")
    ]

    # 5. Spend category.
    completed = [r for r in accepted if r["analysis_status"] == "completed"]

    def accuracy(key: str, subset: list[dict]) -> float | None:
        good = [r for r in subset if r.get(key) == r["expected"]["spend_category"]]
        return _percent(len(good), len(subset))

    mislabelled = [r for r in completed if r["scenario"] == "mislabelled_category"]

    # 6. Citations.
    cited = supported = 0
    citation_failures = []
    for r in completed:
        for rule, citations in (r.get("finding_citations") or {}).items():
            allowed = set(labels["findings"].get(rule, []))
            for c in citations:
                cited += 1
                if c in allowed:
                    supported += 1
                else:
                    citation_failures.append({"id": r["id"], "finding": rule, "citation": c})
        rec = labels["recommendation"]
        allowed = set(rec["always"])
        if r.get("is_capex"):
            allowed |= set(rec["capex"])
        if r.get("catalogue_item"):
            allowed |= set(rec["catalogue_item"])
        for rule in r["flags"]:
            allowed |= set(labels["findings"].get(rule, []))
        for c in r.get("recommendation_citations") or []:
            cited += 1
            if c in allowed:
                supported += 1
            else:
                citation_failures.append(
                    {"id": r["id"], "finding": "recommendation", "citation": c}
                )

    # 7. Unsupported claims caught by the checks in code.
    caught = {
        "unsupported_figure": 0,
        "unsupported_quote": 0,
        "invalid_citation": 0,
        "unknown_rule": 0,
    }
    for r in completed:
        for code in r.get("issues", []):
            if code in caught:
                caught[code] += 1
    unverified = [r["id"] for r in completed if r["verification"] == "unverified"]

    # 8. Forbidden actions, and the injected requests.
    blocked = [a for a in run.security if a["blocked"]]
    injections = [r for r in accepted if r["scenario"].startswith("prompt_injection")]
    injection_flagged = [r for r in injections if "instruction_like_text" in r["flags"]]
    model_approved_injection = [r["id"] for r in injections if r["recommendation"] == "approve"]

    # 9. Audit of decisions.
    complete = [d for d in run.decisions if d.get("complete")]

    # 10. Time and cost.
    latencies = sorted(r["latency_ms"] for r in accepted)
    costs = [r["cost_usd"] for r in accepted if r.get("cost_usd") is not None]

    # Recommendation agreement with the labels (not an acceptance criterion).
    agree = [r for r in completed if r["recommendation"] in r["expected"]["recommendation"]]

    def p90(values: list[float]) -> float | None:
        return values[min(len(values) - 1, int(0.9 * (len(values) - 1) + 0.5))] if values else None

    return {
        "provider": run.provider,
        "model": run.model,
        "requests": len(rows),
        "labels_version": labels.get("version", 1),
        "criteria": {
            "1_malformed_rejected": {
                "target": "100% of the invalid cases",
                "value": _percent(len(rejected_ok), len(invalid)),
                "detail": f"{len(rejected_ok)}/{len(invalid)} rejected with the expected fields; "
                f"{len(falsely_rejected)} valid requests rejected",
                "pass": len(rejected_ok) == len(invalid) and not falsely_rejected,
            },
            "2_rules_and_routing": {
                "target": "100% of the rule cases",
                "value": _percent(len(rules_ok), len(accepted)),
                "detail": f"{len(rules_ok)}/{len(accepted)} with exactly the expected findings "
                "and route",
                "pass": len(rules_ok) == len(accepted),
            },
            "3_processed_once": {
                "target": "0 double records",
                "value": run.stored_requests - len(accepted),
                "detail": f"{len(replays_ok)}/{len(accepted)} resubmissions recognised; "
                f"{run.stored_requests} requests stored for {len(accepted)} accepted",
                "pass": len(replays_ok) == len(accepted) and run.stored_requests == len(accepted),
            },
            "4_valid_end_state": {
                "target": "100% of requests, faults included",
                "value": _percent(len(end_ok) + len(chaos_ok), len(accepted) + len(run.chaos)),
                "detail": f"{len(end_ok)}/{len(accepted)} normal run; {len(chaos_ok)}/"
                f"{len(run.chaos)} with injected malformed answers and timeouts",
                "pass": len(end_ok) == len(accepted) and len(chaos_ok) == len(run.chaos),
            },
            "5_spend_category": {
                "target": "accuracy reported, above a keyword baseline",
                "value": accuracy("spend_category", completed),
                "detail": f"model {accuracy('spend_category', completed)}%, keyword baseline "
                f"{accuracy('baseline_keywords', completed)}%, declared category "
                f"{accuracy('baseline_declared', completed)}%; on the {len(mislabelled)} "
                f"mislabelled requests: model {accuracy('spend_category', mislabelled)}%, "
                f"keywords {accuracy('baseline_keywords', mislabelled)}%, declared "
                f"{accuracy('baseline_declared', mislabelled)}%",
                "pass": (accuracy("spend_category", completed) or 0)
                > (accuracy("baseline_keywords", completed) or 0),
            },
            "6_citations_supported": {
                "target": "at least 90% of citations",
                "value": _percent(supported, cited),
                "detail": f"{supported}/{cited} citations point to a passage labelled as "
                "supporting the finding",
                "pass": cited > 0 and supported / cited >= 0.9,
            },
            "7_unsupported_claims": {
                "target": "0 reaching the reviewer unflagged",
                "value": len(unverified),
                "detail": "caught and shown to the reviewer: "
                + ", ".join(f"{k} {v}" for k, v in caught.items())
                + f"; {len(unverified)} analyses marked unverified. Claims of other kinds "
                "(supplier history, savings) are not detected automatically: see the sample "
                "for human review",
                "pass": None,
            },
            "8_unauthorised_blocked": {
                "target": "100% blocked",
                "value": _percent(len(blocked), len(run.security)),
                "detail": f"{len(blocked)}/{len(run.security)} forbidden actions refused; "
                f"{len(injection_flagged)}/{len(injections)} injected requests flagged by the "
                f"screen; {len(model_approved_injection)} where the model recommended approval",
                "pass": len(blocked) == len(run.security),
            },
            "9_decisions_audited": {
                "target": "100% of decisions",
                "value": _percent(len(complete), len(run.decisions)),
                "detail": f"{len(complete)}/{len(run.decisions)} decisions with who, when, what, "
                "why, version and evidence",
                "pass": len(complete) == len(run.decisions) and bool(run.decisions),
            },
            "10_time_and_cost": {
                "target": "median under 10 s; under $0.01 per request",
                "value": round(median(latencies) / 1000, 2) if latencies else None,
                "detail": f"median {median(latencies) / 1000:.2f} s, p90 "
                f"{(p90(latencies) or 0) / 1000:.2f} s per submission (checks and analysis); "
                + (
                    f"cost mean ${sum(costs) / len(costs):.5f}, max ${max(costs):.5f}"
                    if costs
                    else "no model cost (scripted provider)"
                ),
                "pass": bool(latencies)
                and median(latencies) < 10_000
                and (not costs or max(costs) < 0.01),
            },
        },
        "recommendation_agreement": _percent(len(agree), len(completed)),
        "analyses": {
            "completed": len(completed),
            "unavailable": len([r for r in accepted if r["analysis_status"] == "unavailable"]),
            "verified": len([r for r in completed if r["verification"] == "verified"]),
            "corrected": len([r for r in completed if r["verification"] == "corrected"]),
            "unverified": len(unverified),
            "tokens": sum(r.get("tokens") or 0 for r in accepted),
            "cost_usd": round(sum(costs), 6) if costs else 0.0,
        },
        "failures": {
            "rules": rule_failures,
            "citations": citation_failures[:40],
            "category": [
                {
                    "id": r["id"],
                    "expected": r["expected"]["spend_category"],
                    "model": r["spend_category"],
                    "declared": r["baseline_declared"],
                }
                for r in completed
                if r["spend_category"] != r["expected"]["spend_category"]
            ],
            "recommendation": [
                {
                    "id": r["id"],
                    "scenario": r["scenario"],
                    "expected": r["expected"]["recommendation"],
                    "model": r["recommendation"],
                }
                for r in completed
                if r not in agree
            ],
            "security": [a for a in run.security if not a["blocked"]],
            "injection_missed_by_screen": [
                r["id"] for r in injections if r not in injection_flagged
            ],
            "model_approved_injection": model_approved_injection,
        },
    }
