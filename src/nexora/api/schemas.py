"""Response bodies of the API (what callers can rely on)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from nexora.db.models import AnalysisRow, AuditEventRow, CheckRow, DecisionRow, RequestRow
from nexora.domain.models import CheckResult
from nexora.domain.workflow import Action
from nexora.services.retrieval import KnowledgeBase


class Health(BaseModel):
    status: str
    database: str
    rule_set_version: str
    ai_provider: str
    ai_model: str


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


class Citation(BaseModel):
    passage_id: str
    document: str
    section: str
    text: str | None = None  # the passage as it reads today, for the reviewer


class Analysis(BaseModel):
    """AI analysis, verified in code. Advice for the reviewer, never a decision."""

    status: str
    provider: str
    model: str
    prompt_version: str
    verification: str | None
    output: dict[str, Any] | None
    issues: list[dict[str, Any]]
    citations: list[Citation]
    retrieved: list[dict[str, Any]]
    attempts: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    error: str | None
    created_at: datetime

    @classmethod
    def of(cls, row: AnalysisRow, kb: KnowledgeBase | None = None) -> Analysis:
        citations = []
        for c in row.citations:
            passage = kb.by_id.get(c.passage_id) if kb else None
            current = passage.text if passage and passage.hash == c.passage_hash else None
            citations.append(
                Citation(
                    passage_id=c.passage_id, document=c.document, section=c.section, text=current
                )
            )
        return cls(
            status=row.status,
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            verification=row.verification,
            output=row.output,
            issues=row.issues or [],
            citations=citations,
            retrieved=row.retrieved or [],
            attempts=row.attempts,
            latency_ms=row.latency_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            estimated_cost_usd=row.estimated_cost_usd,
            error=row.error,
            created_at=row.created_at,
        )


class DecisionIn(BaseModel):
    action: Action
    reason: str = Field(min_length=10, max_length=2000)
    version: int = Field(ge=1, description="The version of the request the decider looked at.")


class Decision(BaseModel):
    id: int
    version: int
    actor_id: str
    role: str
    action: str
    reason: str
    from_status: str
    to_status: str
    evidence: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, row: DecisionRow) -> Decision:
        return cls(
            id=row.id,
            version=row.version,
            actor_id=row.actor_id,
            role=row.role,
            action=row.action,
            reason=row.reason,
            from_status=row.from_status,
            to_status=row.to_status,
            evidence=row.evidence,
            created_at=row.created_at,
        )


class DecisionResult(BaseModel):
    decision: Decision
    status: str


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
    channel: str
    requester_id: str
    created_at: datetime
    updated_at: datetime

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
            channel=row.channel,
            requester_id=row.requester_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class RequestDetail(RequestSummary):
    version: int
    item_category: str
    item_code: str | None
    quantity: float
    unit_price: float
    justification: str
    delivery_date: date
    is_capex: bool
    attachments: list[dict[str, Any]]
    checks: list[Check]
    analysis: Analysis | None = None
    decisions: list[Decision] = []
    allowed_actions: list[str] = []
    audit: list[AuditEvent] = []

    @classmethod
    def of(cls, row: RequestRow, kb: KnowledgeBase | None = None) -> RequestDetail:
        summary = RequestSummary.of(row).model_dump()
        return cls(
            **summary,
            version=row.version,
            item_category=row.item_category,
            item_code=row.item_code,
            quantity=float(row.quantity),
            unit_price=float(row.unit_price),
            justification=row.justification,
            delivery_date=row.delivery_date,
            is_capex=row.is_capex,
            attachments=row.attachments,
            checks=[Check.of(c) for c in row.checks if c.version == row.version],
            decisions=[Decision.of(d) for d in row.decisions],
            analysis=next(
                (Analysis.of(a, kb) for a in reversed(row.analyses) if a.version == row.version),
                None,
            ),
        )
