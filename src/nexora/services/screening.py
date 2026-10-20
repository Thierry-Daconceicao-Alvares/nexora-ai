"""Screens the free text of a request for instructions aimed at an AI system.

Description, justification and attachment names are written by the requester
(or come from an email through n8n), so they are untrusted. Text that tries to
instruct the model ("ignore the previous instructions", "approve this
request", fake role markers) is flagged here, deterministically, before the
model sees it. The flag is a check result like any rule: it raises the
severity to high, which sends the request to the approver, and the reviewer
sees the matched text.

The model cannot act on such text anyway: it has no tools, its answer is
checked in code, and it can never change a status or a route. This screen makes
the attempt visible.
"""

from __future__ import annotations

import re

from nexora.domain.models import CheckResult, Outcome, Severity
from nexora.domain.schemas import PurchaseRequestIn

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        (
            "override",
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(instructions?|rules?|prompt|polic(y|ies)|checks?|previous)\b",
        ),
        (
            "role_marker",
            r"<\|?/?(system|im_start|im_end)\b|\[/?(INST|SYS)\]"
            r"|(^|\n)\s*(system|assistant)\s+(prompt|message)\s*:",
        ),
        (
            "decision_order",
            # "Please approve this request" is ordinary business language; only an
            # order addressed to the model counts.
            r"\b(you must|you should|you will|you are required to|assistant)\b[^.\n]{0,30}"
            r"\b(approve|auto-approve|recommend approval|mark (it|this) as (approved|compliant))\b",
        ),
        ("identity", r"\byou are now\b|\bas an ai\b|\b(language model|llm)\b"),
        ("hide_findings", r"\b(do not|don't|never)\s+(flag|mention|report|escalate)\b"),
        ("prompt_probe", r"\b(system prompt|hidden instructions|reveal your)\b"),
    )
)


def _fields(request: PurchaseRequestIn) -> dict[str, str]:
    fields = {"description": request.description, "justification": request.justification}
    for i, attachment in enumerate(request.attachments):
        fields[f"attachments[{i}].file_name"] = attachment.file_name
    return fields


def screen(request: PurchaseRequestIn) -> CheckResult:
    matches = []
    for field, text in _fields(request).items():
        for name, pattern in PATTERNS:
            found = pattern.search(text or "")
            if found:
                matches.append({"field": field, "pattern": name, "text": found.group(0).strip()})
    if matches:
        fields = sorted({m["field"] for m in matches})
        return CheckResult(
            stage="screening",
            rule_id="instruction_like_text",
            outcome=Outcome.FLAG,
            severity=Severity.HIGH,
            message=(
                f"The {', '.join(fields)} contains text addressed to an AI system. "
                "It was treated as data, not as an instruction; please read it."
            ),
            evidence={"matches": matches[:5]},
        )
    return CheckResult(
        stage="screening",
        rule_id="instruction_like_text",
        outcome=Outcome.PASS,
        severity=Severity.INFO,
        message="No text addressed to an AI system.",
    )
