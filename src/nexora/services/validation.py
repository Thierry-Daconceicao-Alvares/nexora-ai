"""Deterministic validation of a submitted request.

Every problem is reported in one pass, each as a CheckResult with the field it
concerns, so that the requester can fix everything at once. No model is called
here: data integrity never depends on an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from nexora.domain.models import CheckResult, Outcome, Severity
from nexora.domain.rules_config import RulesConfig
from nexora.domain.schemas import PurchaseRequestIn

# Pydantic error types, rewritten in words a requester understands.
_MESSAGES = {
    "missing": "This field is required.",
    "string_pattern_mismatch": "The format is not valid.",
    "string_too_short": "The text is too short.",
    "string_too_long": "The text is too long.",
    "greater_than": "The value must be greater than zero.",
    "less_than_equal": "The value is above the allowed maximum.",
    "decimal_max_places": "Too many decimal places.",
    "decimal_max_digits": "The number has too many digits.",
    "decimal_parsing": "A number is expected.",
    "date_from_datetime_parsing": "A date is expected (YYYY-MM-DD).",
    "date_parsing": "A date is expected (YYYY-MM-DD).",
    "bool_parsing": "Yes or no is expected.",
    "enum": "This value is not one of the allowed options.",
    "extra_forbidden": "This field is not expected.",
    "too_long": "Too many items.",
}


@dataclass
class ValidationReport:
    request: PurchaseRequestIn | None
    checks: list[CheckResult]

    @property
    def valid(self) -> bool:
        return self.request is not None and not any(c.outcome is Outcome.FAIL for c in self.checks)


def _fail(rule_id: str, field: str | None, message: str, **evidence: Any) -> CheckResult:
    return CheckResult(
        stage="validation",
        rule_id=rule_id,
        outcome=Outcome.FAIL,
        severity=Severity.HIGH,
        message=message,
        field=field,
        evidence=evidence,
    )


def validate(
    payload: dict[str, Any],
    rules: RulesConfig,
    known_categories: set[str],
    today: date,
) -> ValidationReport:
    checks: list[CheckResult] = []
    request: PurchaseRequestIn | None = None
    try:
        request = PurchaseRequestIn.model_validate(payload)
    except ValidationError as error:
        for item in error.errors():
            field = ".".join(str(part) for part in item["loc"]) or None
            message = _MESSAGES.get(item["type"], item["msg"])
            checks.append(_fail(f"schema.{item['type']}", field, message))

    # Business checks run on the raw values too, so that a request with a type
    # error still gets every other problem reported.
    currency = str(payload.get("currency") or "").strip().upper()
    if currency and currency not in rules.fx_rates_to_eur:
        checks.append(
            _fail(
                "currency.unsupported",
                "currency",
                f"Currency {currency} is not supported.",
                supported=sorted(rules.fx_rates_to_eur),
            )
        )
    department = str(payload.get("department") or "").strip()
    if department and department not in rules.departments:
        checks.append(
            _fail(
                "department.unknown",
                "department",
                f"Department {department!r} is not known.",
                known=rules.departments,
            )
        )
    category = str(payload.get("item_category") or "").strip()
    if category and category not in known_categories:
        checks.append(
            _fail("category.unknown", "item_category", f"Category {category!r} is not known.")
        )
    if request is not None and request.delivery_date < today:
        checks.append(
            _fail(
                "delivery_date.past",
                "delivery_date",
                "The delivery date is in the past.",
                delivery_date=request.delivery_date.isoformat(),
                today=today.isoformat(),
            )
        )
    if request is not None and request.currency != currency:
        # Normalise the case once the currency is known to be valid.
        request = request.model_copy(update={"currency": currency})

    if not checks:
        checks.append(
            CheckResult(
                stage="validation",
                rule_id="validation.complete",
                outcome=Outcome.PASS,
                severity=Severity.INFO,
                message="All fields are present and valid.",
            )
        )
    return ValidationReport(request=request if not _has_fail(checks) else None, checks=checks)


def _has_fail(checks: list[CheckResult]) -> bool:
    return any(c.outcome is Outcome.FAIL for c in checks)
