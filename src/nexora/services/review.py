"""Review decisions: approve, reject, request information, escalate.

Every check is done here, not in the interface:
- only reviewers and approvers decide, nobody on their own request;
- the role must be the one the current state waits for, and the action must
  be allowed in that state (see domain/workflow.py);
- the decision applies to the version the person looked at;
- a reason is always written;
- one decision per transition: the state is changed with a compare-and-set,
  so two people deciding at the same time cannot both succeed.

The decision is stored with the evidence in front of the decider (the findings,
the AI recommendation and its verification status, the cited passages), and
recorded in the audit trail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from nexora.db.models import DecisionRow, RequestRow
from nexora.domain.models import Role, Severity, Status, User
from nexora.domain.workflow import Action, allowed_actions, deciding_role, next_status
from nexora.services import audit
from nexora.services.authorization import Forbidden, can_read
from nexora.services.errors import Conflict, Invalid, NotFound

DECIDER_ROLES = {Role.REVIEWER, Role.APPROVER}
MIN_REASON = 10


def actions_for(actor: User, request: RequestRow) -> list[str]:
    """What this actor may do on this request now (shown by the interface)."""
    if actor.role not in DECIDER_ROLES or actor.id == request.requester_id:
        return []
    return [a.value for a in allowed_actions(request.status, actor.role)]


def _evidence(request: RequestRow, action: Action) -> dict[str, Any]:
    flags = [
        {"rule_id": c.rule_id, "severity": c.severity, "policy_ref": c.policy_ref}
        for c in request.checks
        if c.version == request.version and c.outcome != "pass"
    ]
    analysis = next((a for a in reversed(request.analyses) if a.version == request.version), None)
    evidence: dict[str, Any] = {
        "amount_eur": float(request.amount_eur),
        "route": request.route,
        "flags": flags,
        "analysis": None,
    }
    if analysis is not None:
        output = analysis.output or {}
        evidence["analysis"] = {
            "id": analysis.id,
            "status": analysis.status,
            "provider": analysis.provider,
            "verification": analysis.verification,
            "recommendation": (output.get("recommendation") or {}).get("action"),
            "citations": [c.passage_id for c in analysis.citations],
        }
    if action is Action.APPROVE:
        evidence["approved_despite"] = [
            f["rule_id"] for f in flags if Severity(f["severity"]).rank >= Severity.HIGH.rank
        ]
    return evidence


def decide(
    session: Session,
    actor: User,
    request_id: str,
    action: Action,
    reason: str,
    version: int,
    now: datetime,
) -> DecisionRow:
    request = session.get(RequestRow, request_id)
    if request is None or not can_read(actor, request.requester_id):
        raise NotFound("No such request.")
    if actor.role not in DECIDER_ROLES:
        raise Forbidden(f"Role {actor.role} cannot decide on purchase requests.")
    if actor.id == request.requester_id:
        raise Forbidden("Nobody decides on their own request.")

    status = request.status
    role = deciding_role(status)
    if role is None:
        raise Conflict(f"The request is {status}: there is no decision to take.")
    if role is not actor.role:
        raise Forbidden(f"This request waits for the {role.value}, not the {actor.role.value}.")
    if action not in allowed_actions(status, actor.role):
        raise Conflict(f"'{action.value}' is not possible when the request is {status}.")
    if version != request.version:
        raise Conflict(
            f"The request changed since you opened it: version {request.version} is current."
        )
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise Invalid(f"A reason of at least {MIN_REASON} characters is required.", field="reason")

    target = next_status(status, action, request.route)
    route = "approver" if action is Action.ESCALATE else request.route
    evidence = _evidence(request, action)

    # Compare-and-set: succeeds only if nobody changed the request meanwhile.
    changed = session.execute(
        update(RequestRow)
        .where(
            RequestRow.id == request.id,
            RequestRow.status == status,
            RequestRow.version == version,
        )
        .values(status=target.value, route=route, updated_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise Conflict("Another decision was recorded on this request at the same time.")
    session.refresh(request)

    decision = DecisionRow(
        request_id=request.id,
        version=version,
        actor_id=actor.id,
        role=actor.role.value,
        action=action.value,
        reason=reason,
        from_status=status,
        to_status=target.value,
        evidence=evidence,
        created_at=now,
    )
    session.add(decision)
    audit.record(
        session,
        "decision.recorded",
        at=now,
        request_id=request.id,
        actor_id=actor.id,
        role=actor.role.value,
        action=action.value,
        reason=reason,
        version=version,
        from_status=status,
        to_status=target.value,
        evidence=evidence,
    )
    audit.record(
        session,
        "request.status_changed",
        at=now,
        request_id=request.id,
        actor_id=actor.id,
        from_status=status,
        to_status=target.value,
        route=route,
    )
    if target in (Status.APPROVED, Status.REJECTED):
        audit.record(
            session, f"request.{target.value}", at=now, request_id=request.id, actor_id=actor.id
        )
    session.flush()
    return decision
