"""Engine, sessions and the loading of the demo reference data."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from nexora.db.models import Base, ReferencePriceRow, SupplierRow, UserRow


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record):  # noqa: ANN001
            connection.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create the tables. Phase 3 only: Alembic migrations replace this in Phase 5."""
    Base.metadata.create_all(engine)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def seed_reference_data(session: Session, users_path: Path, synthetic_dir: Path) -> None:
    """Load the demo users, suppliers and reference prices once."""
    if session.scalar(select(UserRow.id).limit(1)) is None:
        users = yaml.safe_load(users_path.read_text(encoding="utf-8"))["users"]
        session.add_all(
            UserRow(
                id=u["id"],
                name=u["name"],
                email=u["email"],
                role=u["role"],
                department=u["department"],
            )
            for u in users
        )
    if session.scalar(select(SupplierRow.id).limit(1)) is None:
        with (synthetic_dir / "suppliers.csv").open(encoding="utf-8") as handle:
            session.add_all(
                SupplierRow(
                    id=row["supplier_id"],
                    name=row["name"],
                    registration_number=row["registration_number"],
                    status=row["status"],
                    categories=row["categories"].split(";"),
                )
                for row in csv.DictReader(handle)
            )
    if session.scalar(select(ReferencePriceRow.item_code).limit(1)) is None:
        with (synthetic_dir / "reference_prices.csv").open(encoding="utf-8") as handle:
            session.add_all(
                ReferencePriceRow(
                    item_code=row["item_code"],
                    category=row["category"],
                    description=row["description"],
                    unit_price=Decimal(row["unit_price"]),
                    currency=row["currency"],
                )
                for row in csv.DictReader(handle)
            )
