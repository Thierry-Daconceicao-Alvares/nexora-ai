"""What n8n sends, and to whom. The backend decides; n8n only delivers.

n8n reads three feeds with the integration service account:

- `outbox(after)`: the audit events that call for a message (a request to
  review, to approve, information requested, approved, rejected), each with
  its recipients, subject, text and a link to the request. n8n keeps the
  cursor, so every event is sent once.
- `reminders(older_than_hours)`: requests waiting for a person for too long.
- `digest(days)`: the weekly summary for the Head of Procurement.

Recipients come from the users table: reviewers, approvers, or the requester.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexora.db.models import AuditEventRow, DecisionRow, RequestRow, UserRow
from nexora.services import metrics

# status reached -> (kind of message, who receives it)
TRIGGERS = {
    "awaiting_review": ("review_needed", "reviewer"),
    "awaiting_approver": ("approval_needed", "approver"),
    "info_requested": ("info_requested", "requester"),
    "approved": ("approved", "requester"),
    "rejected": ("rejected", "requester"),
}
WAITING_FOR = {
    "awaiting_review": "reviewer",
    "awaiting_approver": "approver",
    "info_requested": "requester",
}


def _people(session: Session, who: str, request: RequestRow) -> list[dict[str, str]]:
    if who == "requester":
        users = [session.get(UserRow, request.requester_id)]
    else:
        users = list(session.scalars(select(UserRow).where(UserRow.role == who)))
    return [{"name": u.name, "email": u.email, "role": u.role} for u in users if u]


def _summary(request: RequestRow, ui_url: str) -> dict[str, Any]:
    return {
        "id": request.id,
        "external_ref": request.external_ref,
        "version": request.version,
        "department": request.department,
        "supplier_id": request.supplier_id,
        "description": request.description,
        "amount": float(request.amount),
        "currency": request.currency,
        "amount_eur": float(request.amount_eur),
        "status": request.status,
        "route": request.route,
        "highest_severity": request.highest_severity,
        "link": f"{ui_url.rstrip('/')}/?request={request.id}",
    }


def _last_reason(session: Session, request: RequestRow) -> str | None:
    decision = session.scalar(
        select(DecisionRow)
        .where(DecisionRow.request_id == request.id)
        .order_by(DecisionRow.id.desc())
        .limit(1)
    )
    return decision.reason if decision else None


def _message(kind: str, data: dict[str, Any], reason: str | None) -> tuple[str, str]:
    ref, amount = data["external_ref"], f"{data['amount']:,.2f} {data['currency']}"
    head = f"{ref} - {data['description']} ({amount}, {data['department']})"
    findings = (
        f"Highest finding: {data['highest_severity']}."
        if data["highest_severity"] != "info"
        else "No rule finding."
    )
    texts = {
        "review_needed": (
            f"[NEXORA] To review: {ref}",
            f"A purchase request waits for your review.\n\n{head}\n{findings}",
        ),
        "approval_needed": (
            f"[NEXORA] To approve: {ref}",
            f"A purchase request waits for your approval.\n\n{head}\n{findings}",
        ),
        "info_requested": (
            f"[NEXORA] Information needed: {ref}",
            f"Procurement needs more information before deciding.\n\n{head}\n\n"
            f"Request from the reviewer: {reason}",
        ),
        "approved": (
            f"[NEXORA] Approved: {ref}",
            f"Your purchase request was approved.\n\n{head}\n\nReason: {reason}",
        ),
        "rejected": (
            f"[NEXORA] Rejected: {ref}",
            f"Your purchase request was rejected.\n\n{head}\n\nReason: {reason}",
        ),
    }
    subject, text = texts[kind]
    return subject, f"{text}\n\nOpen the request: {data['link']}"


def outbox(session: Session, after: int, ui_url: str, limit: int = 100) -> dict[str, Any]:
    # A cursor beyond the last event means the database was reset while n8n
    # kept its cursor: start again from the beginning rather than miss events.
    last = session.scalar(select(func.max(AuditEventRow.id))) or 0
    reset = after > last
    if reset:
        after = 0
    events = list(
        session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.id > after)
            .order_by(AuditEventRow.id)
            .limit(limit)
        )
    )
    items = []
    for event in events:
        to_status = (event.payload or {}).get("to_status")
        if event.type != "request.status_changed" or to_status not in TRIGGERS:
            continue
        request = session.get(RequestRow, event.request_id)
        if request is None:
            continue
        kind, who = TRIGGERS[to_status]
        data = _summary(request, ui_url)
        reason = _last_reason(session, request) if who == "requester" else None
        subject, text = _message(kind, data, reason)
        items.append(
            {
                "event_id": event.id,
                "kind": kind,
                "request": data,
                "reason": reason,
                "recipients": _people(session, who, request),
                "subject": subject,
                "text": text,
            }
        )
    cursor = events[-1].id if events else after
    return {"next_cursor": cursor, "cursor_reset": reset, "items": items}


def reminders(
    session: Session, now: datetime, older_than_hours: int, ui_url: str
) -> list[dict[str, Any]]:
    limit = now - timedelta(hours=older_than_hours)
    items = []
    rows = session.scalars(
        select(RequestRow)
        .where(RequestRow.status.in_(list(WAITING_FOR)))
        .order_by(RequestRow.updated_at)
    )
    for request in rows:
        updated = metrics._aware(request.updated_at, now)
        if updated > limit:
            continue
        who = WAITING_FOR[request.status]
        data = _summary(request, ui_url)
        hours = round((now - updated).total_seconds() / 3600)
        items.append(
            {
                "request": data,
                "waiting_for": who,
                "waiting_hours": hours,
                "recipients": _people(session, who, request),
                "subject": f"[NEXORA] Reminder: {data['external_ref']} waits for you",
                "text": (
                    f"{data['external_ref']} - {data['description']} has been waiting "
                    f"for the {who} for {hours} hours.\n\nOpen the request: {data['link']}"
                ),
            }
        )
    return items


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def digest(session: Session, now: datetime, days: int, ui_url: str) -> dict[str, Any]:
    figures = metrics.compute(session, now, days)
    r, q, d, ai = figures["requests"], figures["queue"], figures["decisions"], figures["ai"]
    approvers = [
        {"name": u.name, "email": u.email, "role": u.role}
        for u in session.scalars(select(UserRow).where(UserRow.role == "approver"))
    ]
    rules = ", ".join(f"{k} ({v})" for k, v in figures["exceptions"]["by_rule"].items())
    cost = ai["estimated_cost_usd"]
    names = {
        "approve": "approved",
        "reject": "rejected",
        "request_info": "information requested",
        "escalate": "escalated",
    }
    actions = ", ".join(f"{v} {names.get(k, k)}" for k, v in d["by_action"].items())
    median = d["cycle_time_hours_median"]
    lines = [
        f"Purchase requests of the last {days} days",
        "",
        f"Submitted: {r['total']} for EUR {r['amount_eur']:,.2f}",
        f"Decisions: {d['total']}" + (f" ({actions})" if actions else ""),
        "Median time to a final decision: "
        + (f"{median} hours" if median is not None else "no request closed yet"),
        f"Waiting now: {q['awaiting_review']} for review, {q['awaiting_approver']} for "
        f"approval, {q['info_requested']} for the requester",
        f"Findings by rule: {rules or 'none'}",
        f"Approved despite a high or critical finding: {d['approved_despite_high_findings']}",
        f"AI analyses: {ai['analyses']}, estimated model cost USD {cost:.4f}",
        "",
        f"Dashboard: {ui_url}",
    ]
    return {
        "recipients": approvers,
        "subject": f"[NEXORA] Weekly digest: {_count(r['total'], 'request')}, "
        f"{q['awaiting_approver']} waiting for approval",
        "text": "\n".join(lines),
        "metrics": figures,
    }
