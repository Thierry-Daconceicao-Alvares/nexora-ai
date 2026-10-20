"""CSV import: one purchase request per row, each stored or refused on its own.

Columns (header row required, comma or semicolon separated, UTF-8):
external_ref, department, supplier_id, item_category, item_code, description,
quantity, unit_price, currency, justification, delivery_date, is_capex,
attachments. `attachments` lists `kind:file name` pairs separated by `|`, for
example `quote:q1.pdf|quote:q2.pdf`. A row sent again with the same reference
is recognised and not stored twice.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from nexora.domain.models import User
from nexora.domain.rules_config import RulesConfig
from nexora.llm.base import LLMProvider
from nexora.services import intake
from nexora.services.errors import Conflict, Invalid
from nexora.services.retrieval import KnowledgeBase

MAX_CSV_BYTES = 1_000_000
MAX_ROWS = 200
COLUMNS = (
    "external_ref",
    "department",
    "supplier_id",
    "item_category",
    "item_code",
    "description",
    "quantity",
    "unit_price",
    "currency",
    "justification",
    "delivery_date",
    "is_capex",
    "attachments",
)
TRUE = {"true", "yes", "1", "y"}


def _attachments(value: str) -> list[dict[str, str]]:
    items = []
    for part in filter(None, (p.strip() for p in value.split("|"))):
        kind, _, name = part.partition(":")
        items.append({"kind": kind.strip(), "file_name": name.strip()})
    return items


def parse(content: bytes) -> list[tuple[int, dict[str, Any]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise Invalid("The file is not UTF-8 text.", field="file") from error
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip() for h in reader.fieldnames or []]
    unknown = sorted(set(header) - set(COLUMNS))
    if not header or unknown:
        raise Invalid(
            f"Unknown or missing columns: {', '.join(unknown) or 'no header'}. "
            f"Expected: {', '.join(COLUMNS)}.",
            field="file",
        )
    rows = []
    for number, raw in enumerate(reader, start=2):  # line 1 is the header
        if len(rows) == MAX_ROWS:
            raise Invalid(f"At most {MAX_ROWS} rows per file.", field="file")
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        payload: dict[str, Any] = {k: v for k, v in row.items() if v != ""}
        payload.pop("attachments", None)
        payload["is_capex"] = row.get("is_capex", "").lower() in TRUE
        payload["attachments"] = _attachments(row.get("attachments", ""))
        rows.append((number, payload))
    return rows


def submit_row(
    session: Session,
    actor: User,
    line: int,
    payload: dict[str, Any],
    rule_set: RulesConfig,
    now: datetime,
    provider: LLMProvider | None,
    knowledge_base: KnowledgeBase | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"line": line, "external_ref": payload.get("external_ref")}
    try:
        with session.begin_nested():
            outcome = intake.submit(
                session,
                actor,
                payload,
                rule_set,
                now,
                provider=provider,
                knowledge_base=knowledge_base,
                channel="csv",
            )
    except Conflict as error:
        return {**result, "status": "refused", "errors": [{"message": str(error)}]}
    if not outcome.accepted:
        errors = [
            {"field": c.field, "message": c.message}
            for c in outcome.checks
            if c.outcome.value == "fail"
        ]
        return {**result, "status": "refused", "errors": errors}
    request = outcome.request
    return {
        **result,
        "status": "already_submitted" if outcome.replayed else "created",
        "request_id": request.id,
        "request_status": request.status,
        "route": request.route,
        "highest_severity": request.highest_severity,
    }
