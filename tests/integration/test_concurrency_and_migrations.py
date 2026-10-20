"""One decision per transition under concurrency, and the database schema
built by the Alembic migrations."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from nexora.db.models import Base, RequestRow
from nexora.db.session import make_engine, make_session_factory, migrate
from nexora.domain.models import Role, User
from nexora.domain.workflow import Action
from nexora.services import review
from nexora.services.errors import Conflict
from tests.conftest import NOW, auth, valid_payload

KARIM = User("u-karim", "Karim Benali", "karim.benali@nexora.example", Role.REVIEWER, "Procurement")


def test_two_simultaneous_decisions_cannot_both_succeed(client, settings):
    request = client.post("/requests", json=valid_payload(), headers=auth("sophie")).json()
    factory = make_session_factory(make_engine(settings.database_url))
    first, second = factory(), factory()
    try:
        # Both reviewers have the request open, in the same state.
        seen_first = first.get(RequestRow, request["id"])
        seen_second = second.get(RequestRow, request["id"])
        assert seen_first.status == seen_second.status == "awaiting_review"
        review.decide(first, KARIM, request["id"], Action.APPROVE, "First decision taken.", 1, NOW)
        first.commit()
        try:
            review.decide(
                second, KARIM, request["id"], Action.REJECT, "Second decision, too late.", 1, NOW
            )
        except Conflict as error:
            assert "same time" in str(error)
        else:
            raise AssertionError("the second decision should have been refused")
        second.rollback()
    finally:
        first.close()
        second.close()
    decisions = client.get(f"/requests/{request['id']}", headers=auth("karim")).json()
    assert [d["action"] for d in decisions["decisions"]] == ["approve"]


def test_the_migrations_build_exactly_the_models(client, settings):
    engine = make_engine(settings.database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0002"


def test_a_database_created_before_the_migrations_is_upgraded(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    legacy = [t for t in Base.metadata.sorted_tables if t.name != "decisions"]
    Base.metadata.create_all(engine, tables=legacy)  # what phases 3 and 4 did
    migrate(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"decisions", "alembic_version", "purchase_requests"} <= tables
    migrate(engine)  # a second run changes nothing
