from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest

from nexora.domain.models import Outcome, Severity
from nexora.domain.rules_config import RulesConfig
from nexora.domain.schemas import PurchaseRequestIn
from nexora.services import rules as r
from tests.conftest import NOW, valid_payload


@dataclass
class FakeFacts:
    suppliers: dict[str, r.SupplierFact] = field(
        default_factory=lambda: {
            "SUP-0002": r.SupplierFact("SUP-0002", "Beta Bearings", "active", ("spare_parts",)),
            "SUP-0009": r.SupplierFact("SUP-0009", "Iris Lab", "pending", ("lab_equipment",)),
            "SUP-0012": r.SupplierFact("SUP-0012", "Lumen", "blocked", ("electrical_services",)),
        }
    )
    prices: dict[str, Decimal] = field(default_factory=lambda: {"MRO-BRG-6205": Decimal("8.40")})
    history: list[r.RecentRequest] = field(default_factory=list)

    def supplier(self, supplier_id):
        return self.suppliers.get(supplier_id)

    def reference_price_eur(self, item_code):
        return self.prices.get(item_code)

    def recent_requests(self, requester_id, since):
        return [h for h in self.history if h.created_at >= since]


def make_input(**changes) -> r.RuleInput:
    request = PurchaseRequestIn.model_validate(valid_payload(**changes))
    return r.RuleInput(
        request=request,
        requester_id="u-sophie",
        amount_eur=request.amount,
        unit_price_eur=request.unit_price,
        submitted_at=NOW,
    )


def one_quote(n: int = 1, *extra: str) -> list[dict]:
    docs = [{"kind": "quote", "file_name": f"q{i}.pdf"} for i in range(n)]
    return docs + [{"kind": kind, "file_name": f"{kind}.pdf"} for kind in extra]


def recent(ref: str, amount: str, days_ago: int = 3, **changes) -> r.RecentRequest:
    values = {
        "id": ref,
        "external_ref": ref,
        "supplier_id": "SUP-0002",
        "item_category": "spare_parts",
        "description": "Deep groove ball bearings 6205-2RS for conveyor line 3",
        "amount_eur": Decimal(amount),
        "created_at": NOW - timedelta(days=days_ago),
    }
    values.update(changes)
    return r.RecentRequest(**values)


def test_valid_request_raises_no_flag(rules):
    results = r.evaluate(make_input(), rules, FakeFacts())
    assert [x.outcome for x in results] == [Outcome.PASS] * len(r.RULES)
    assert r.highest_severity(results) is Severity.INFO


@pytest.mark.parametrize(
    ("amount", "approvers"),
    [
        ("9999.99", ["Budget owner"]),
        ("10000", ["Budget owner", "Plant Controller"]),
        ("50000", ["Site Director", "Category Manager"]),
        ("249999.99", ["Site Director", "Category Manager"]),
        ("250000", ["CPO", "CFO"]),
        ("1000000", ["CEO", "CPO", "CFO"]),
        ("5000000", ["Board", "CEO", "CPO", "CFO"]),
    ],
)
def test_approval_bands_follow_the_delegation_of_authority(rules, amount, approvers):
    result = r.approval_band(make_input(quantity="1", unit_price=amount), rules, FakeFacts())
    assert result.evidence["approvers"] == approvers
    assert result.policy_ref == "NX-PUR-002 §2"


@pytest.mark.parametrize(
    ("supplier", "severity"),
    [("SUP-9999", Severity.HIGH), ("SUP-0012", Severity.CRITICAL), ("SUP-0009", Severity.MEDIUM)],
)
def test_supplier_not_active(rules, supplier, severity):
    result = r.supplier_status(make_input(supplier_id=supplier), rules, FakeFacts())
    assert (result.outcome, result.severity) == (Outcome.FLAG, severity)


def test_supplier_active_but_other_category(rules):
    result = r.supplier_status(make_input(item_category="ppe"), rules, FakeFacts())
    assert (result.outcome, result.severity) == (Outcome.FLAG, Severity.LOW)


@pytest.mark.parametrize(
    ("price", "attachments", "outcome", "missing"),
    [
        ("4999.99", one_quote(1), Outcome.PASS, None),
        ("5000", one_quote(1), Outcome.FLAG, ["2 more quote(s)"]),
        ("5000", one_quote(3), Outcome.PASS, None),
        ("5000", one_quote(1, "single_source_justification"), Outcome.PASS, None),
        ("60000", one_quote(3), Outcome.FLAG, ["bid_comparison"]),
        ("60000", one_quote(3, "bid_comparison"), Outcome.PASS, None),
        ("300000", one_quote(3, "bid_comparison"), Outcome.FLAG, ["award_decision"]),
    ],
)
def test_sourcing_evidence(rules, price, attachments, outcome, missing):
    data = make_input(quantity="1", unit_price=price, item_code=None, attachments=attachments)
    result = r.sourcing_evidence(data, rules, FakeFacts())
    assert result.outcome is outcome
    assert result.evidence.get("missing") == missing


def test_missing_sourcing_evidence_is_high_from_50000(rules):
    data = make_input(quantity="1", unit_price="60000", item_code=None)
    assert r.sourcing_evidence(data, rules, FakeFacts()).severity is Severity.HIGH


def test_capex_needs_an_approved_request(rules):
    flagged = r.capex_approval(make_input(is_capex=True), rules, FakeFacts())
    assert (flagged.outcome, flagged.severity) == (Outcome.FLAG, Severity.HIGH)
    attached = make_input(is_capex=True, attachments=one_quote(1, "capex_approval"))
    assert r.capex_approval(attached, rules, FakeFacts()).outcome is Outcome.PASS


@pytest.mark.parametrize(
    ("price", "outcome", "severity", "deviation"),
    [
        ("9.24", Outcome.PASS, Severity.INFO, 10.0),
        ("10.08", Outcome.FLAG, Severity.MEDIUM, 20.0),
        ("11.76", Outcome.FLAG, Severity.HIGH, 40.0),
        ("5.04", Outcome.FLAG, Severity.HIGH, -40.0),
    ],
)
def test_price_deviation_from_the_reference(rules, price, outcome, severity, deviation):
    result = r.price_deviation(make_input(unit_price=price), rules, FakeFacts())
    assert (result.outcome, result.severity) == (outcome, severity)
    assert result.evidence["deviation_pct"] == deviation


def test_no_reference_price_means_no_comparison(rules):
    result = r.price_deviation(make_input(item_code=None), rules, FakeFacts())
    assert result.outcome is Outcome.PASS
    assert "not compared" in result.message


def test_duplicate_request_is_flagged(rules):
    facts = FakeFacts(history=[recent("PR-2026-00099", "170.00")])
    result = r.duplicate_request(make_input(), rules, facts)
    assert (result.outcome, result.severity) == (Outcome.FLAG, Severity.HIGH)
    assert result.evidence["other_request"] == "PR-2026-00099"


@pytest.mark.parametrize(
    "other",
    [
        recent("PR-2026-00099", "168.00", supplier_id="SUP-0001"),
        recent("PR-2026-00099", "400.00"),
        recent("PR-2026-00099", "168.00", days_ago=45),
        recent("PR-2026-00099", "168.00", description="Safety helmets for the new operators"),
    ],
)
def test_not_a_duplicate(rules, other):
    result = r.duplicate_request(make_input(), rules, FakeFacts(history=[other]))
    assert result.outcome is Outcome.PASS


def test_split_purchase_across_the_5000_threshold(rules):
    facts = FakeFacts(history=[recent("PR-2026-00050", "4000.00", description="Bearings lot A")])
    data = make_input(quantity="1", unit_price="4000", item_code=None, description="Bearings lot B")
    result = r.split_purchase(data, rules, facts)
    assert (result.outcome, result.severity) == (Outcome.FLAG, Severity.HIGH)
    assert result.evidence["threshold_eur"] == 5000.0
    assert result.evidence["related_requests"] == ["PR-2026-00050"]


def test_no_split_when_one_request_is_already_above(rules):
    facts = FakeFacts(history=[recent("PR-2026-00050", "6000.00", description="Bearings lot A")])
    data = make_input(quantity="1", unit_price="3000", item_code=None, description="Bearings lot B")
    assert r.split_purchase(data, rules, facts).outcome is Outcome.PASS


def test_routing_to_the_approver(rules):
    small = make_input()
    assert not r.needs_approver(small, r.evaluate(small, rules, FakeFacts()), rules)
    large = make_input(quantity="1", unit_price="50000", item_code=None)
    assert r.needs_approver(large, r.evaluate(large, rules, FakeFacts()), rules)
    risky = make_input(supplier_id="SUP-0012")
    assert r.needs_approver(risky, r.evaluate(risky, rules, FakeFacts()), rules)


def test_rule_set_lists_every_threshold(rules: RulesConfig):
    assert rules.thresholds_eur() == [5000, 10000, 50000, 250000, 1000000, 5000000]


def test_misordered_bands_are_refused(rules: RulesConfig):
    data = rules.model_dump()
    data["approval_bands"]["bands"].reverse()
    with pytest.raises(ValueError):
        RulesConfig.model_validate(data)


def test_currency_conversion(rules):
    assert r.to_eur(Decimal("100"), "USD", rules) == Decimal("92.00")
    assert r.to_eur(Decimal("100"), "GBP", rules) == Decimal("117.00")


def test_rule_results_are_reproducible(rules):
    first = r.evaluate(make_input(unit_price="11.76"), rules, FakeFacts())
    second = r.evaluate(make_input(unit_price="11.76"), rules, FakeFacts())
    assert first == second
    assert all(isinstance(x.evidence, dict) for x in first)
