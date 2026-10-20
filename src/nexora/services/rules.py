"""Deterministic business rules, configured in config/rules.yaml.

Each rule is a plain function of the request and of facts read from the
database (supplier status, reference price, recent requests). It returns one
CheckResult that names the rule, the policy it applies and what it saw. The
same inputs always give the same results; no model is involved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Protocol

from nexora.domain.models import CheckResult, Outcome, Severity
from nexora.domain.rules_config import RulesConfig
from nexora.domain.schemas import AttachmentKind, PurchaseRequestIn


@dataclass(frozen=True)
class SupplierFact:
    supplier_id: str
    name: str
    status: str  # active, pending or blocked
    categories: tuple[str, ...]


@dataclass(frozen=True)
class RecentRequest:
    id: str
    external_ref: str
    supplier_id: str
    item_category: str
    description: str
    amount_eur: Decimal
    created_at: datetime


class RuleFacts(Protocol):
    """What the rules may read; the database implements it, tests fake it."""

    def supplier(self, supplier_id: str) -> SupplierFact | None: ...

    def reference_price_eur(self, item_code: str) -> Decimal | None: ...

    def recent_requests(self, requester_id: str, since: datetime) -> list[RecentRequest]: ...


@dataclass(frozen=True)
class RuleInput:
    request: PurchaseRequestIn
    requester_id: str
    amount_eur: Decimal
    unit_price_eur: Decimal
    submitted_at: datetime


def to_eur(amount: Decimal, currency: str, rules: RulesConfig) -> Decimal:
    rate = Decimal(str(rules.fx_rates_to_eur[currency]))
    return (amount * rate).quantize(Decimal("0.01"))


def _result(
    rule_id: str,
    outcome: Outcome,
    severity: Severity,
    message: str,
    policy_ref: str | None,
    **evidence: object,
) -> CheckResult:
    return CheckResult(
        stage="rule",
        rule_id=rule_id,
        outcome=outcome,
        severity=severity,
        message=message,
        policy_ref=policy_ref,
        evidence={k: _plain(v) for k, v in evidence.items()},
    )


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _eur(value: Decimal | float) -> str:
    return f"€{Decimal(str(value)):,.2f}"


# --------------------------------------------------------------------- rules


def approval_band(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    band = rules.approval_bands.band_for(float(data.amount_eur))
    return _result(
        "approval_band",
        Outcome.PASS,
        Severity.INFO,
        f"Total commitment {_eur(data.amount_eur)}: approval by {', '.join(band.approvers)}.",
        rules.approval_bands.policy_ref,
        amount_eur=data.amount_eur,
        band_from_eur=band.from_eur,
        approvers=band.approvers,
    )


def supplier_status(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    ref = rules.supplier_status.policy_ref
    supplier = facts.supplier(data.request.supplier_id)
    if supplier is None:
        return _result(
            "supplier_status",
            Outcome.FLAG,
            Severity.HIGH,
            f"Supplier {data.request.supplier_id} is not in the vendor master: no PO can be "
            "issued before onboarding.",
            ref,
            supplier_id=data.request.supplier_id,
        )
    if supplier.status == "blocked":
        return _result(
            "supplier_status",
            Outcome.FLAG,
            Severity.CRITICAL,
            f"Supplier {supplier.name} is blocked in the vendor master.",
            ref,
            supplier_id=supplier.supplier_id,
            status=supplier.status,
        )
    if supplier.status != "active":
        return _result(
            "supplier_status",
            Outcome.FLAG,
            Severity.MEDIUM,
            f"Supplier {supplier.name} has not completed onboarding (status {supplier.status}).",
            ref,
            supplier_id=supplier.supplier_id,
            status=supplier.status,
        )
    if data.request.item_category not in supplier.categories:
        return _result(
            "supplier_status",
            Outcome.FLAG,
            Severity.LOW,
            f"Supplier {supplier.name} is active but not listed for {data.request.item_category}.",
            ref,
            supplier_id=supplier.supplier_id,
            supplier_categories=list(supplier.categories),
        )
    return _result(
        "supplier_status",
        Outcome.PASS,
        Severity.INFO,
        f"Supplier {supplier.name} is active for this category.",
        ref,
        supplier_id=supplier.supplier_id,
    )


def sourcing_evidence(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    level = rules.sourcing.level_for(float(data.amount_eur))
    kinds = [a.kind.value for a in data.request.attachments]
    quotes = kinds.count(AttachmentKind.QUOTE.value)
    single_source = rules.sourcing.single_source_document in kinds
    missing: list[str] = []
    if quotes < level.quotes and not (single_source and quotes >= 1):
        missing.append(f"{level.quotes - quotes} more quote(s)")
    missing += [doc for doc in level.also if doc not in kinds]
    evidence = {
        "amount_eur": data.amount_eur,
        "quotes_required": level.quotes,
        "quotes_attached": quotes,
        "documents_required": level.also,
        "single_source_justification": single_source,
    }
    if missing:
        severity = Severity.HIGH if data.amount_eur >= Decimal("50000") else Severity.MEDIUM
        return _result(
            "sourcing_evidence",
            Outcome.FLAG,
            severity,
            f"Sourcing evidence missing for {_eur(data.amount_eur)}: {', '.join(missing)}.",
            rules.sourcing.policy_ref,
            missing=missing,
            **evidence,
        )
    return _result(
        "sourcing_evidence",
        Outcome.PASS,
        Severity.INFO,
        "The sourcing evidence required for this amount is attached.",
        rules.sourcing.policy_ref,
        **evidence,
    )


def capex_approval(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    kinds = {a.kind.value for a in data.request.attachments}
    if data.request.is_capex and rules.capex.document not in kinds:
        return _result(
            "capex_approval",
            Outcome.FLAG,
            Severity.HIGH,
            "Capital expenditure without an approved CapEx request.",
            rules.capex.policy_ref,
            is_capex=True,
        )
    return _result(
        "capex_approval",
        Outcome.PASS,
        Severity.INFO,
        "CapEx approval attached." if data.request.is_capex else "Not a capital expenditure.",
        rules.capex.policy_ref,
        is_capex=data.request.is_capex,
    )


def price_deviation(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    cfg = rules.price_deviation
    code = data.request.item_code
    reference = facts.reference_price_eur(code) if code else None
    if reference is None:
        return _result(
            "price_deviation",
            Outcome.PASS,
            Severity.INFO,
            "No reference price for this item: the price was not compared.",
            cfg.policy_ref,
            item_code=code,
        )
    deviation = (data.unit_price_eur - reference) / reference * 100
    evidence = {
        "item_code": code,
        "unit_price_eur": data.unit_price_eur,
        "reference_price_eur": reference,
        "deviation_pct": round(float(deviation), 1),
    }
    size = abs(deviation)
    if size >= Decimal(str(cfg.high_pct)):
        severity = Severity.HIGH
    elif size >= Decimal(str(cfg.medium_pct)):
        severity = Severity.MEDIUM
    else:
        return _result(
            "price_deviation",
            Outcome.PASS,
            Severity.INFO,
            f"Unit price within {cfg.medium_pct:g}% of the reference price.",
            cfg.policy_ref,
            **evidence,
        )
    direction = "above" if deviation > 0 else "below"
    return _result(
        "price_deviation",
        Outcome.FLAG,
        severity,
        f"Unit price {_eur(data.unit_price_eur)} is {abs(float(deviation)):.0f}% {direction} the "
        f"reference price {_eur(reference)}.",
        cfg.policy_ref,
        **evidence,
    )


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def duplicate_request(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    cfg = rules.duplicates
    since = data.submitted_at - timedelta(days=cfg.window_days)
    tolerance = Decimal(str(cfg.amount_tolerance_pct)) / 100
    for other in facts.recent_requests(data.requester_id, since):
        if other.external_ref == data.request.external_ref:
            continue
        same_terms = (
            other.supplier_id == data.request.supplier_id
            and other.item_category == data.request.item_category
            and abs(other.amount_eur - data.amount_eur) <= tolerance * max(data.amount_eur, 1)
        )
        similarity = _similar(other.description, data.request.description)
        if same_terms and similarity >= cfg.min_description_similarity:
            return _result(
                "duplicate_request",
                Outcome.FLAG,
                Severity.HIGH,
                f"Possible duplicate of {other.external_ref}: same supplier, category and "
                f"amount within {cfg.amount_tolerance_pct:g}%, similar description.",
                cfg.policy_ref,
                other_request=other.external_ref,
                other_amount_eur=other.amount_eur,
                description_similarity=round(similarity, 2),
            )
    return _result(
        "duplicate_request",
        Outcome.PASS,
        Severity.INFO,
        f"No similar request in the last {cfg.window_days} days.",
        cfg.policy_ref,
    )


def split_purchase(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> CheckResult:
    cfg = rules.splitting
    since = data.submitted_at - timedelta(days=cfg.window_days)
    related = [
        r
        for r in facts.recent_requests(data.requester_id, since)
        if r.supplier_id == data.request.supplier_id and r.external_ref != data.request.external_ref
    ]
    if related:
        total = data.amount_eur + sum((r.amount_eur for r in related), Decimal("0"))
        for threshold in rules.thresholds_eur():
            limit = Decimal(str(threshold))
            each_below = data.amount_eur < limit and all(r.amount_eur < limit for r in related)
            if each_below and total >= limit:
                return _result(
                    "split_purchase",
                    Outcome.FLAG,
                    Severity.HIGH,
                    f"Possible split purchase: {len(related) + 1} requests to the same supplier "
                    f"in {cfg.window_days} days total {_eur(total)}, above the "
                    f"{_eur(limit)} threshold, while each is below it.",
                    cfg.policy_ref,
                    threshold_eur=limit,
                    total_eur=total,
                    related_requests=[r.external_ref for r in related],
                )
    return _result(
        "split_purchase",
        Outcome.PASS,
        Severity.INFO,
        "No sign of a requirement split across requests.",
        cfg.policy_ref,
    )


RULES: tuple[Callable[[RuleInput, RulesConfig, RuleFacts], CheckResult], ...] = (
    approval_band,
    supplier_status,
    sourcing_evidence,
    capex_approval,
    price_deviation,
    duplicate_request,
    split_purchase,
)


def evaluate(data: RuleInput, rules: RulesConfig, facts: RuleFacts) -> list[CheckResult]:
    return [rule(data, rules, facts) for rule in RULES]


def highest_severity(results: list[CheckResult]) -> Severity:
    flagged = [r.severity for r in results if r.outcome is not Outcome.PASS]
    return max(flagged, key=lambda s: s.rank) if flagged else Severity.INFO


def needs_approver(data: RuleInput, results: list[CheckResult], rules: RulesConfig) -> bool:
    """True when the Head of Procurement (approver role) must review the request."""
    routing = rules.routing
    return (
        float(data.amount_eur) >= routing.approver_from_eur
        or highest_severity(results).rank >= routing.approver_from_severity.rank
    )
