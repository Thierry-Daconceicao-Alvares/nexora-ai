"""Reads the rules need, from the database (implements services.rules.RuleFacts)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexora.db.models import ReferencePriceRow, RequestRow, SupplierRow
from nexora.domain.rules_config import RulesConfig
from nexora.services.rules import RecentRequest, SupplierFact, to_eur


class DatabaseFacts:
    def __init__(self, session: Session, rules: RulesConfig) -> None:
        self.session = session
        self.rules = rules

    def supplier(self, supplier_id: str) -> SupplierFact | None:
        row = self.session.get(SupplierRow, supplier_id)
        if row is None:
            return None
        return SupplierFact(row.id, row.name, row.status, tuple(row.categories))

    def reference_price_eur(self, item_code: str) -> Decimal | None:
        row = self.session.get(ReferencePriceRow, item_code)
        if row is None:
            return None
        return to_eur(Decimal(row.unit_price), row.currency, self.rules)

    def recent_requests(self, requester_id: str, since: datetime) -> list[RecentRequest]:
        rows = self.session.scalars(
            select(RequestRow)
            .where(RequestRow.requester_id == requester_id, RequestRow.created_at >= since)
            .where(RequestRow.status != "validation_failed")
            .order_by(RequestRow.created_at)
        )
        return [
            RecentRequest(
                id=r.id,
                external_ref=r.external_ref,
                supplier_id=r.supplier_id,
                item_category=r.item_category,
                description=r.description,
                amount_eur=Decimal(r.amount_eur),
                created_at=r.created_at,
            )
            for r in rows
        ]


def known_categories(session: Session) -> set[str]:
    categories = set(session.scalars(select(ReferencePriceRow.category)))
    for supplier_categories in session.scalars(select(SupplierRow.categories)):
        categories.update(supplier_categories)
    return categories
