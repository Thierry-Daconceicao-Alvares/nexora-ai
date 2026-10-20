"""Alembic environment. Run by nexora.db.session.migrate() at start-up, or by
hand: `alembic upgrade head` (see alembic.ini)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from nexora.config import get_settings
from nexora.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url") or get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
        engine = engine_from_config(
            {"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool
        )
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connection)


def _run(connection) -> None:  # noqa: ANN001
    # render_as_batch: SQLite cannot alter columns in place.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
