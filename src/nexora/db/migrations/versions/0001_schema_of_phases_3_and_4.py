"""Schema of phases 3 and 4

Revision ID: 0001
Revises:

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("actor_id", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_events_request_id"), ["request_id"], unique=False
        )

    op.create_table(
        "reference_prices",
        sa.Column("item_code", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.PrimaryKeyConstraint("item_code"),
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("registration_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("department", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_ref", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.String(length=40), nullable=False),
        sa.Column("department", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.String(length=20), nullable=False),
        sa.Column("item_category", sa.String(length=50), nullable=False),
        sa.Column("item_code", sa.String(length=30), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_eur", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("is_capex", sa.Boolean(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("route", sa.String(length=20), nullable=True),
        sa.Column("highest_severity", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_ref"),
        sa.UniqueConstraint("idempotency_key"),
    )
    with op.batch_alter_table("purchase_requests", schema=None) as batch_op:
        batch_op.create_index(
            "ix_requests_requester_created", ["requester_id", "created_at"], unique=False
        )

    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=30), nullable=False),
        sa.Column("verification", sa.String(length=20), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("retrieved", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["purchase_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ai_analyses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_analyses_request_id"), ["request_id"], unique=False)

    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("rule_id", sa.String(length=60), nullable=False),
        sa.Column("rule_set_version", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=True),
        sa.Column("policy_ref", sa.String(length=40), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["purchase_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("check_results", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_check_results_request_id"), ["request_id"], unique=False
        )

    op.create_table(
        "citations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("passage_id", sa.String(length=40), nullable=False),
        sa.Column("document", sa.String(length=200), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=False),
        sa.Column("passage_hash", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["ai_analyses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("citations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_citations_analysis_id"), ["analysis_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("citations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_citations_analysis_id"))

    op.drop_table("citations")
    with op.batch_alter_table("check_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_check_results_request_id"))

    op.drop_table("check_results")
    with op.batch_alter_table("ai_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ai_analyses_request_id"))

    op.drop_table("ai_analyses")
    with op.batch_alter_table("purchase_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_requests_requester_created")

    op.drop_table("purchase_requests")
    op.drop_table("users")
    op.drop_table("suppliers")
    op.drop_table("reference_prices")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_events_request_id"))

    op.drop_table("audit_events")
