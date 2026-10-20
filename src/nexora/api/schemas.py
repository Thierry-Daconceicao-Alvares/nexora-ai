"""Response bodies of the API (what callers can rely on)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from nexora.db.models import AuditEventRow, CheckRow, RequestRow
from nexora.domain.models import CheckResult


class Health(BaseModel):
    status: str
    database: str
    rule_set_version: str


class Check(BaseModel):
    stage: str
    rule_id: str
    outcome: str
    severity: str
    message: str
    field: str | None = None
    policy_ref: str | None = None
    evidence: dict[str, Any] = {}

    @classmethod
    def of(cls, item: CheckResult | CheckRow) -> Check:
        return cls(
            stage=item.stage,
            rule_id=item.rule_id,
            outcome=str(getattr(item.outcome, "value", item.outcome)),
            severity=str(getattr(item.severity, "value", item.severity)),
            message=item.message,
            field=item.field,
            policy_ref=item.policy_ref,
            evidence=item.evidence or {},
        )


class ValidationFailure(BaseModel):
    code: str
    message: str
    errors: list[Check]


class AuditEvent(BaseModel):
    id: int
    request_id: str | None
    type: str
    actor_id: str | None
    payload: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, row: AuditEventRow) -> AuditEvent:
        return cls(
            id=row.id,
            request_id=row.request_id,
            type=row.type,
            actor_id=row.actor_id,
            payload=row.payload,
            created_at=row.created_at,
        )


class RequestSummary(BaseModel):
    id: str
    external_ref: str
    department: str
    supplier_id: str
    description: str
    amount: float
    currency: str
    amount_eur: float
    status: str
    route: str | None
    highest_severity: str
    created_at: datetime

    @classmethod
    def of(cls, row: RequestRow) -> RequestSummary:
        return cls(
            id=row.id,
            external_ref=row.external_ref,
            department=row.department,
            supplier_id=row.supplier_id,
            description=row.description,
            amount=float(row.amount),
            currency=row.currency,
            amount_eur=float(row.amount_eur),
            status=row.status,
            route=row.route,
            highest_severity=row.highest_severity,
            created_at=row.created_at,
        )


class RequestDetail(RequestSummary):
    version: int
    requester_id: str
    item_category: str
    item_code: str | None
    quantity: float
    unit_price: float
    justification: str
    delivery_date: date
    is_capex: bool
    attachments: list[dict[str, Any]]
    checks: list[Check]
    audit: list[AuditEvent] = []

    @classmethod
    def of(cls, row: RequestRow) -> RequestDetail:
        summary = RequestSummary.of(row).model_dump()
        return cls(
            **summary,
            version=row.version,
            requester_id=row.requester_id,
            item_category=row.item_category,
            item_code=row.item_code,
            quantity=float(row.quantity),
            unit_price=float(row.unit_price),
            justification=row.justification,
            delivery_date=row.delivery_date,
            is_capex=row.is_capex,
            attachments=row.attachments,
            checks=[Check.of(c) for c in row.checks if c.version == row.version],
        )
