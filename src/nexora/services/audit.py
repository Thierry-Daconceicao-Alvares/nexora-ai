"""Append-only audit trail. Payloads hold identifiers, outcomes and evidence
references only: never tokens, secrets or full prompts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from nexora.db.models import AuditEventRow

FORBIDDEN_KEYS = {"token", "authorization", "api_key", "password", "prompt"}


def record(
    session: Session,
    event_type: str,
    *,
    at: datetime,
    request_id: str | None = None,
    actor_id: str | None = None,
    **payload: Any,
) -> AuditEventRow:
    leaked = FORBIDDEN_KEYS & {key.lower() for key in payload}
    if leaked:
        raise ValueError(f"Audit payload must not contain {sorted(leaked)}")
    row = AuditEventRow(
        request_id=request_id, type=event_type, actor_id=actor_id, payload=payload, created_at=at
    )
    session.add(row)
    return row
