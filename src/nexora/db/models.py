"""Database tables (SQLAlchemy 2.0). PostgreSQL in Docker Compose, SQLite in
tests and in the public demo."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    department: Mapped[str] = mapped_column(String(50))


class SupplierRow(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    registration_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    categories: Mapped[list[str]] = mapped_column(JSON)


class ReferencePriceRow(Base):
    __tablename__ = "reference_prices"

    item_code: Mapped[str] = mapped_column(String(30), primary_key=True)
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))


class RequestRow(Base):
    __tablename__ = "purchase_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_ref: Mapped[str] = mapped_column(String(20), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    department: Mapped[str] = mapped_column(String(50))
    supplier_id: Mapped[str] = mapped_column(String(20))
    item_category: Mapped[str] = mapped_column(String(50))
    item_code: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    justification: Mapped[str] = mapped_column(Text)
    delivery_date: Mapped[date] = mapped_column(Date)
    is_capex: Mapped[bool] = mapped_column(default=False)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30))
    route: Mapped[str | None] = mapped_column(String(20))
    highest_severity: Mapped[str] = mapped_column(String(10), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    checks: Mapped[list[CheckRow]] = relationship(
        back_populates="request", order_by="CheckRow.id", cascade="all, delete-orphan"
    )

    analyses: Mapped[list[AnalysisRow]] = relationship(
        back_populates="request", order_by="AnalysisRow.id", cascade="all, delete-orphan"
    )
    decisions: Mapped[list[DecisionRow]] = relationship(
        back_populates="request", order_by="DecisionRow.id", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_requests_requester_created", "requester_id", "created_at"),)


class CheckRow(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    version: Mapped[int]
    stage: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[str] = mapped_column(String(60))
    rule_set_version: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    field: Mapped[str | None] = mapped_column(String(60))
    policy_ref: Mapped[str | None] = mapped_column(String(40))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    request: Mapped[RequestRow] = relationship(back_populates="checks")


class AnalysisRow(Base):
    """One AI analysis of one version of a request. The prompt text is not
    stored, only its version; the output is stored after verification."""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))  # completed, unavailable
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(30))
    verification: Mapped[str | None] = mapped_column(String(20))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    retrieved: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    request: Mapped[RequestRow] = relationship(back_populates="analyses")
    citations: Mapped[list[CitationRow]] = relationship(
        back_populates="analysis", order_by="CitationRow.id", cascade="all, delete-orphan"
    )


class CitationRow(Base):
    """A policy passage that the verified analysis relies on."""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("ai_analyses.id"), index=True)
    passage_id: Mapped[str] = mapped_column(String(40))  # "NX-PUR-001 §5"
    document: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(200))
    passage_hash: Mapped[str] = mapped_column(String(16))

    analysis: Mapped[AnalysisRow] = relationship(back_populates="citations")


class DecisionRow(Base):
    """A decision by a person on one version of a request: who, when, what, why,
    and the evidence they had in front of them."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    version: Mapped[int]
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))  # approve, reject, request_info, escalate
    reason: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    request: Mapped[RequestRow] = relationship(back_populates="decisions")


class AuditEventRow(Base):
    """Append-only log of every step. n8n reads it in order (the outbox)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(60))
    actor_id: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
