"""Who may do what. Checked in the services, so that the API and the
Streamlit interface cannot bypass it."""

from __future__ import annotations

from nexora.domain.models import Role, User


class Forbidden(Exception):
    """The actor's role does not allow the action."""


SUBMIT_ROLES = {Role.REQUESTER, Role.INTAKE_SERVICE}
READ_ALL_ROLES = {Role.REVIEWER, Role.APPROVER, Role.ADMIN}


def require_submit(actor: User) -> None:
    if actor.role not in SUBMIT_ROLES:
        raise Forbidden(f"Role {actor.role} cannot submit purchase requests.")


def can_read(actor: User, requester_id: str) -> bool:
    return actor.role in READ_ALL_ROLES or actor.id == requester_id
