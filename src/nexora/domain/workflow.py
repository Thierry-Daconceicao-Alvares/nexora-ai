"""The review workflow: which role may take which action in which state.

    awaiting_review   --reviewer-->  approve (route reviewer) -> approved
                                     approve (route approver) -> awaiting_approver
                                     escalate                 -> awaiting_approver
                                     request_info             -> info_requested
                                     reject                   -> rejected
    awaiting_approver --approver-->  approve                  -> approved
                                     request_info             -> info_requested
                                     reject                   -> rejected
    info_requested    --requester--> completes the request: new version, every
                                     check runs again, back to awaiting_review

Any other transition is refused. Only a person takes these actions; the AI
analysis can recommend one, never take it.
"""

from __future__ import annotations

from enum import StrEnum

from nexora.domain.models import Role, Status


class Action(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"
    ESCALATE = "escalate"


# State -> (the role that decides in this state, the actions it may take)
DECIDERS: dict[Status, tuple[Role, tuple[Action, ...]]] = {
    Status.AWAITING_REVIEW: (
        Role.REVIEWER,
        (Action.APPROVE, Action.REJECT, Action.REQUEST_INFO, Action.ESCALATE),
    ),
    Status.AWAITING_APPROVER: (
        Role.APPROVER,
        (Action.APPROVE, Action.REJECT, Action.REQUEST_INFO),
    ),
}


def deciding_role(status: str) -> Role | None:
    entry = DECIDERS.get(Status(status))
    return entry[0] if entry else None


def allowed_actions(status: str, role: Role) -> tuple[Action, ...]:
    entry = DECIDERS.get(Status(status))
    return entry[1] if entry and entry[0] is role else ()


def next_status(status: str, action: Action, route: str | None) -> Status:
    """The state after `action`; only called for an allowed action."""
    if action is Action.REJECT:
        return Status.REJECTED
    if action is Action.REQUEST_INFO:
        return Status.INFO_REQUESTED
    if action is Action.ESCALATE:
        return Status.AWAITING_APPROVER
    if Status(status) is Status.AWAITING_REVIEW and route == "approver":
        return Status.AWAITING_APPROVER
    return Status.APPROVED
