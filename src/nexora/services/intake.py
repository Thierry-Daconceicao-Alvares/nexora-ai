"""Intake: from a submitted payload to a stored, checked and routed request.

Order of the steps: validation, business rules, screening of the free text,
retrieval of the policy passages, AI analysis (one model call, verified in
code), routing. The analysis is advice: the route depends on the amount and on
the rule and screening results only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexora.db.models import AnalysisRow, CheckRow, CitationRow, RequestRow
from nexora.db.repository import DatabaseFacts, known_categories
from nexora.domain.models import CheckResult, Status, User
from nexora.domain.rules_config import RulesConfig
from nexora.domain.schemas import PurchaseRequestIn
from nexora.llm.base import LLMProvider
from nexora.services import audit, rules, screening
from nexora.services.analysis import AnalysisRecord, analyse
from nexora.services.authorization import require_submit
from nexora.services.retrieval import KnowledgeBase, retrieve
from nexora.services.validation import validate


class Conflict(Exception):
    """The request clashes with one already stored."""


@dataclass
class IntakeResult:
    request: RequestRow | None
    checks: list[CheckResult] = field(default_factory=list)
    replayed: bool = False

    @property
    def accepted(self) -> bool:
        return self.request is not None


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submit(
    session: Session,
    actor: User,
    payload: dict[str, Any],
    rule_set: RulesConfig,
    now: datetime,
    idempotency_key: str | None = None,
    provider: LLMProvider | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> IntakeResult:
    require_submit(actor)
    digest = payload_hash(payload)
    key = idempotency_key or f"ref:{payload.get('external_ref')}"

    existing = session.scalar(select(RequestRow).where(RequestRow.idempotency_key == key))
    if existing is not None:
        if existing.payload_hash != digest:
            raise Conflict("This idempotency key was already used for a different request.")
        return IntakeResult(request=existing, replayed=True)

    report = validate(payload, rule_set, known_categories(session), now.date())
    if not report.valid:
        audit.record(
            session,
            "request.validation_failed",
            at=now,
            actor_id=actor.id,
            external_ref=payload.get("external_ref"),
            errors=[{"rule_id": c.rule_id, "field": c.field} for c in report.checks],
        )
        return IntakeResult(request=None, checks=report.checks)

    data = report.request
    assert data is not None
    if session.scalar(select(RequestRow.id).where(RequestRow.external_ref == data.external_ref)):
        raise Conflict(f"A request with reference {data.external_ref} already exists.")

    amount_eur = rules.to_eur(data.amount, data.currency, rule_set)
    request = RequestRow(
        id=str(uuid.uuid4()),
        external_ref=data.external_ref,
        idempotency_key=key,
        payload_hash=digest,
        version=1,
        requester_id=actor.id,
        department=data.department,
        supplier_id=data.supplier_id,
        item_category=data.item_category,
        item_code=data.item_code,
        description=data.description,
        quantity=data.quantity,
        unit_price=data.unit_price,
        currency=data.currency,
        amount=data.amount,
        amount_eur=amount_eur,
        justification=data.justification,
        delivery_date=data.delivery_date,
        is_capex=data.is_capex,
        attachments=[a.model_dump(mode="json") for a in data.attachments],
        status=Status.SUBMITTED,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    try:
        session.flush()
    except IntegrityError as error:  # a concurrent submission won the race
        session.rollback()
        raise Conflict("This request was submitted at the same time by another call.") from error

    audit.record(
        session,
        "request.submitted",
        at=now,
        request_id=request.id,
        actor_id=actor.id,
        external_ref=request.external_ref,
        amount_eur=float(amount_eur),
    )
    _store_checks(session, request, report.checks, rule_set.version)
    _move(session, request, Status.VALIDATED, now, actor.id)

    rule_input = rules.RuleInput(
        request=data,
        requester_id=actor.id,
        amount_eur=amount_eur,
        unit_price_eur=rules.to_eur(Decimal(data.unit_price), data.currency, rule_set),
        submitted_at=now,
    )
    results = rules.evaluate(rule_input, rule_set, DatabaseFacts(session, rule_set))
    _store_checks(session, request, results, rule_set.version)
    request.highest_severity = rules.highest_severity(results).value
    audit.record(
        session,
        "rules.evaluated",
        at=now,
        request_id=request.id,
        rule_set_version=rule_set.version,
        flags=[r.rule_id for r in results if r.outcome.value != "pass"],
        highest_severity=request.highest_severity,
    )

    screen = screening.screen(data)
    _store_checks(session, request, [screen], rule_set.version)
    if screen.outcome.value != "pass":
        audit.record(
            session,
            "screening.flagged",
            at=now,
            request_id=request.id,
            fields=sorted({m["field"] for m in screen.evidence["matches"]}),
        )
    checked = [*results, screen]
    request.highest_severity = rules.highest_severity(checked).value

    if provider is not None and knowledge_base is not None:
        record = _analyse(provider, knowledge_base, data, request, checked)
        _store_analysis(session, request, record, now)
        _move(session, request, Status.ANALYSED, now, None)

    request.route = (
        "approver" if rules.needs_approver(rule_input, checked, rule_set) else "reviewer"
    )
    _move(session, request, Status.AWAITING_REVIEW, now, None, route=request.route)
    return IntakeResult(request=request, checks=report.checks + checked)


def _analyse(
    provider: LLMProvider,
    kb: KnowledgeBase,
    data: PurchaseRequestIn,
    request: RequestRow,
    checked: list[CheckResult],
) -> AnalysisRecord:
    flagged = [r for r in checked if r.outcome.value != "pass"]
    anchors = [(r.rule_id, r.policy_ref) for r in flagged]
    anchors += [(r.rule_id, r.policy_ref) for r in checked if r.rule_id == "approval_band"]
    query = " ".join([data.description, data.justification, *(r.message for r in flagged)])
    hits = retrieve(kb, query, anchors)
    view = data.model_dump(mode="json")
    view["amount"] = str(request.amount)
    view["amount_eur"] = str(request.amount_eur)
    return analyse(provider, view, checked, hits)


def _store_analysis(
    session: Session, request: RequestRow, record: AnalysisRecord, now: datetime
) -> None:
    passages = {h.passage.id: h.passage for h in record.hits}
    row = AnalysisRow(
        request_id=request.id,
        version=request.version,
        status=record.status,
        provider=record.provider,
        model=record.model,
        prompt_version=record.prompt_version,
        verification=record.verification,
        output=record.output,
        issues=record.issues,
        retrieved=[
            {"passage_id": h.passage.id, "reason": h.reason, "score": h.score} for h in record.hits
        ],
        attempts=record.attempts,
        latency_ms=record.latency_ms,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        estimated_cost_usd=record.estimated_cost_usd,
        error=record.error,
        created_at=now,
        citations=[
            CitationRow(
                passage_id=pid,
                document=f"{passages[pid].doc_id} {passages[pid].doc_title}",
                section=f"§{passages[pid].section} {passages[pid].section_title}",
                passage_hash=passages[pid].hash,
            )
            for pid in record.cited_ids
        ],
    )
    session.add(row)
    audit.record(
        session,
        f"analysis.{record.status}",
        at=now,
        request_id=request.id,
        provider=record.provider,
        model=record.model,
        prompt_version=record.prompt_version,
        verification=record.verification,
        issues=sorted({i["code"] for i in record.issues}),
        citations=record.cited_ids,
        recommendation=(record.output or {}).get("recommendation", {}).get("action"),
        attempts=record.attempts,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        estimated_cost_usd=record.estimated_cost_usd,
        error=record.error,
    )


def _store_checks(
    session: Session, request: RequestRow, results: list[CheckResult], rule_set_version: str
) -> None:
    session.add_all(
        CheckRow(
            request_id=request.id,
            version=request.version,
            stage=r.stage,
            rule_id=r.rule_id,
            rule_set_version=rule_set_version,
            outcome=r.outcome.value,
            severity=r.severity.value,
            message=r.message,
            field=r.field,
            policy_ref=r.policy_ref,
            evidence=r.evidence,
        )
        for r in results
    )


def _move(
    session: Session,
    request: RequestRow,
    status: Status,
    now: datetime,
    actor_id: str | None,
    **payload: Any,
) -> None:
    previous = request.status
    request.status = status
    request.updated_at = now
    audit.record(
        session,
        "request.status_changed",
        at=now,
        request_id=request.id,
        actor_id=actor_id,
        from_status=str(previous),
        to_status=status.value,
        **payload,
    )
