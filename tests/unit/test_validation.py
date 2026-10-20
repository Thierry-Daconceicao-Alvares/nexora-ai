from __future__ import annotations

from datetime import date

from nexora.domain.models import Outcome
from nexora.services.validation import validate
from tests.conftest import valid_payload

CATEGORIES = {"spare_parts", "ppe", "it_hardware"}
TODAY = date(2026, 10, 20)


def errors(report) -> dict[str, str]:
    return {c.field or c.rule_id: c.rule_id for c in report.checks if c.outcome is Outcome.FAIL}


def test_valid_request_passes(rules):
    report = validate(valid_payload(), rules, CATEGORIES, TODAY)
    assert report.valid
    assert [c.rule_id for c in report.checks] == ["validation.complete"]


def test_every_problem_is_reported_at_once(rules):
    payload = valid_payload(
        external_ref="123",
        currency="JPY",
        department="Marketing",
        quantity="0",
        delivery_date="2026-10-01",
    )
    del payload["justification"]
    found = errors(validate(payload, rules, CATEGORIES, TODAY))
    assert found == {
        "external_ref": "schema.string_pattern_mismatch",
        "quantity": "schema.greater_than",
        "justification": "schema.missing",
        "currency": "currency.unsupported",
        "department": "department.unknown",
    }


def test_past_delivery_date_is_rejected(rules):
    report = validate(valid_payload(delivery_date="2026-10-19"), rules, CATEGORIES, TODAY)
    assert errors(report) == {"delivery_date": "delivery_date.past"}
    assert report.request is None


def test_unknown_category_and_extra_field(rules):
    payload = valid_payload(item_category="jewellery", discount="50%")
    assert errors(validate(payload, rules, CATEGORIES, TODAY)) == {
        "discount": "schema.extra_forbidden",
        "item_category": "category.unknown",
    }


def test_negative_price_and_too_many_decimals(rules):
    assert errors(validate(valid_payload(unit_price="-3"), rules, CATEGORIES, TODAY)) == {
        "unit_price": "schema.greater_than"
    }
    assert errors(validate(valid_payload(unit_price="8.405"), rules, CATEGORIES, TODAY)) == {
        "unit_price": "schema.decimal_max_places"
    }


def test_text_where_a_number_is_expected(rules):
    report = validate(valid_payload(quantity="twenty"), rules, CATEGORIES, TODAY)
    assert errors(report) == {"quantity": "schema.decimal_parsing"}


def test_currency_case_is_normalised(rules):
    report = validate(valid_payload(currency="eur"), rules, CATEGORIES, TODAY)
    assert report.valid
    assert report.request.currency == "EUR"


def test_unknown_attachment_kind(rules):
    payload = valid_payload(attachments=[{"kind": "invoice", "file_name": "x.pdf"}])
    assert errors(validate(payload, rules, CATEGORIES, TODAY)) == {
        "attachments.0.kind": "schema.enum"
    }
