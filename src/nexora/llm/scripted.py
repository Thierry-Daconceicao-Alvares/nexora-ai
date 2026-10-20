"""Scripted provider: a deterministic stand-in for a language model.

It is used when no Gemini key is configured (local runs, CI, the free public
demo), so that the whole pipeline works without an account. It is NOT a
language model: it reads the rule results and passages from the prompt and
assembles the answer from templates. Analyses produced this way are labelled
with the provider "scripted" everywhere they are shown.
"""

from __future__ import annotations

import json
import re
from typing import Any

from nexora.llm.base import LLMResult

ACTION_BY_SEVERITY = {
    "info": "approve",
    "low": "request_info",
    "medium": "request_info",
    "high": "escalate",
    "critical": "reject",
}
RANK = ["info", "low", "medium", "high", "critical"]
MISSING = {
    "sourcing_evidence": "The sourcing documents listed in the finding",
    "capex_approval": "An approved CapEx request",
    "supplier_status": "Confirmation that the supplier is onboarded and active",
    "price_deviation": "A quote or explanation for the price difference",
    "duplicate_request": "Confirmation that this is not a duplicate of the earlier request",
    "split_purchase": "An explanation of why these purchases were not combined",
}


def _read_block(prompt: str, name: str) -> Any:
    match = re.search(rf"<{name}>\n(.*?)\n</{name}>", prompt, re.DOTALL)
    return json.loads(match.group(1)) if match else None


class ScriptedProvider:
    name = "scripted"
    model = "scripted-v1"

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        results = _read_block(user, "rule_results") or []
        passages = {p["id"] for p in _read_block(user, "policy_passages") or []}
        request = _read_block(user, "untrusted_request") or {}

        flagged = [r for r in results if r["outcome"] != "pass"]
        findings = [
            {
                "rule_id": r["rule_id"],
                "explanation": r["message"],
                "citations": [r["policy_ref"]] if r.get("policy_ref") in passages else [],
            }
            for r in flagged
        ]
        worst = max((r["severity"] for r in flagged), key=RANK.index, default="info")
        basis = [f["citations"][0] for f in findings if f["citations"]]
        if not basis:
            basis = [r["policy_ref"] for r in results if r["rule_id"] == "approval_band"]
        basis = [ref for ref in dict.fromkeys(basis) if ref in passages]
        action = ACTION_BY_SEVERITY[worst]
        rationale = (
            "No rule raised a finding; the request follows the approval route of its amount."
            if not flagged
            else f"The most serious finding is {worst}: "
            + "; ".join(r["rule_id"].replace("_", " ") for r in flagged)
            + "."
        )
        total = f"{request.get('amount')} {request.get('currency')}"
        if request.get("currency") != "EUR":
            total += f" (EUR {request.get('amount_eur')})"
        output = {
            "summary": (
                f"{request.get('department')} requests {request.get('description')} "
                f"from supplier {request.get('supplier_id')}, total {total}."
            ),
            "spend_category": str(request.get("item_category", "")).replace("_", " "),
            "findings": findings,
            "missing_information": [
                MISSING[r["rule_id"]] for r in flagged if r["rule_id"] in MISSING
            ],
            "recommendation": {"action": action, "rationale": rationale, "citations": basis},
            "insufficient_evidence": False,
            "instruction_like_text_seen": any(
                r["rule_id"] == "instruction_like_text" for r in flagged
            ),
        }
        return LLMResult(text=json.dumps(output), model=self.model)
