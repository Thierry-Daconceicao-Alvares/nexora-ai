"""Writes the results of an evaluation run: results.jsonl (one line per
request), metrics.json, and report.md for people."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from nexora.evaluation.runner import Run

NAMES = {
    "1_malformed_rejected": "1. Malformed requests rejected with a structured error",
    "2_rules_and_routing": "2. Business rules and routing give the expected result",
    "3_processed_once": "3. Repeated submissions processed once",
    "4_valid_end_state": "4. Valid end state, even when the model fails",
    "5_spend_category": "5. Spend category correct",
    "6_citations_supported": "6. Citations point to a supporting passage",
    "7_unsupported_claims": "7. Unsupported claims",
    "8_unauthorised_blocked": "8. Unauthorised actions blocked",
    "9_decisions_audited": "9. Every decision audited",
    "10_time_and_cost": "10. Time and cost per request",
}


def _mark(value: bool | None) -> str:
    return {True: "pass", False: "**fail**", None: "see detail"}[value]


def write(run: Run, figures: dict[str, Any], out: Path, meta: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in run.rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "meta": meta,
                **figures,
                "security": run.security,
                "decisions": run.decisions,
                "chaos": run.chaos,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    lines = [
        f"# Evaluation: {meta['provider']} ({meta['model']})",
        "",
        f"Run on {meta['date']}, commit `{meta['commit']}`, prompt `{meta['prompt_version']}`, "
        f"rule set `{meta['rule_set']}`, {figures['requests']} labelled requests "
        f"([data/evaluation](../../../data/evaluation)). Synthetic data: these figures describe "
        "the system on this test set, not on real requests. Fault injection (criterion 4) "
        "wraps the scripted stand-in, so that it measures the application's fallback "
        "without spending model quota.",
        "",
        "| Criterion | Target | Result | Detail |",
        "|---|---|---|---|",
    ]
    for key, item in figures["criteria"].items():
        lines.append(
            f"| {NAMES[key]} | {item['target']} | {_mark(item['pass'])} | {item['detail']} |"
        )
    a = figures["analyses"]
    lines += [
        "",
        f"Analyses: {a['completed']} completed ({a['verified']} verified, {a['corrected']} "
        f"corrected, {a['unverified']} unverified), {a['unavailable']} unavailable; "
        f"{a['tokens']:,} tokens, estimated ${a['cost_usd']:.4f}. The suggested decision "
        f"matches the labelled acceptable decisions for {figures['recommendation_agreement']}% "
        "of the analysed requests (not an acceptance criterion: only a person decides).",
        "",
        "## By scenario",
        "",
        "| Scenario | Requests | Findings and route as expected | Suggested decision acceptable "
        "| Category correct |",
        "|---|---|---|---|---|",
    ]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in run.rows:
        groups[row["scenario"]].append(row)
    rule_failed = {f["id"] for f in figures["failures"]["rules"]}
    for scenario, rows in groups.items():
        accepted = [r for r in rows if r["status_code"] == 201]
        if not accepted:
            lines.append(
                f"| {scenario} | {len(rows)} | rejected as expected: "
                f"{sum(r['status_code'] == 422 for r in rows)}/{len(rows)} | - | - |"
            )
            continue
        done = [r for r in accepted if r.get("analysis_status") == "completed"]
        lines.append(
            f"| {scenario} | {len(rows)} | {sum(r['id'] not in rule_failed for r in accepted)}"
            f"/{len(accepted)} | "
            f"{sum(r['recommendation'] in r['expected']['recommendation'] for r in done)}"
            f"/{len(done)} | "
            f"{sum(r['spend_category'] == r['expected']['spend_category'] for r in done)}"
            f"/{len(done)} |"
        )

    failures = figures["failures"]
    lines += ["", "## What did not go as labelled", ""]
    if failures["rules"]:
        lines.append("**Rules and routing**")
        lines += [
            f"- {f['id']} ({f['scenario']}): expected {f['expected']} route "
            f"{f['expected_route']}, got {f['got']} route {f['route']}"
            for f in failures["rules"]
        ]
        lines.append("")
    if failures["injection_missed_by_screen"]:
        lines.append(
            f"**Injections the screen did not flag**: "
            f"{', '.join(failures['injection_missed_by_screen'])}. The model saw them "
            "as data; the route stayed the one of the rules."
        )
        lines.append("")
    if failures["model_approved_injection"]:
        lines.append(
            f"**Model suggested approval on an injected request**: "
            f"{', '.join(failures['model_approved_injection'])}"
        )
        lines.append("")
    if failures["citations"]:
        counts = Counter((c["finding"], c["citation"]) for c in failures["citations"])
        lines.append("**Citations not labelled as supporting** (finding, passage, count)")
        lines += [
            f"- {finding}: {citation} ({n})" for (finding, citation), n in counts.most_common(15)
        ]
        lines.append("")
    if failures["category"]:
        lines.append("**Spend category** (expected / model / declared by the requester)")
        lines += [
            f"- {c['id']}: {c['expected']} / {c['model']} / {c['declared']}"
            for c in failures["category"][:25]
        ]
        lines.append("")
    if failures["recommendation"]:
        counts = Counter((f["scenario"], f["model"]) for f in failures["recommendation"])
        lines.append("**Suggested decisions outside the labels** (scenario, suggestion, count)")
        lines += [f"- {s}: {m} ({n})" for (s, m), n in counts.most_common(15)]
        lines.append("")
    if failures["security"]:
        lines.append("**Forbidden actions not refused as expected**")
        lines += [
            f"- {a['attempt']}: HTTP {a['status']} (expected {a['expected']})"
            for a in failures["security"]
        ]
        lines.append("")

    sample = [r for r in run.rows if r.get("analysis_status") == "completed"][::12][:12]
    lines += [
        "## Sample for human review",
        "",
        "Criterion 7 also asks for a reviewed sample: claims such as a supplier history or a "
        "saving cannot be detected in code. These analyses are listed for a person to read; "
        "this report does not say they were reviewed.",
        "",
    ]
    for r in sample:
        lines += [
            f"- **{r['id']}** ({r['scenario']}), suggested {r['recommendation']}: "
            f"{r['summary']} _{r['rationale']}_"
        ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
