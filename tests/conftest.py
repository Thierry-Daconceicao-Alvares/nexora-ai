from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.config import ROOT, Settings
from nexora.db.models import Base
from nexora.db.session import make_engine
from nexora.domain.rules_config import RulesConfig, load_rules

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

TOKENS = {
    "sophie": "demo-sophie",
    "marc": "demo-marc",
    "karim": "demo-karim",
    "claire": "demo-claire",
    "intake": "demo-intake",
    "admin": "demo-admin",
}


def valid_payload(**changes: Any) -> dict[str, Any]:
    """A request that passes validation and every rule: 20 bearings from an
    active supplier at the reference price, one quote, below €5,000."""
    payload: dict[str, Any] = {
        "external_ref": "PR-2026-00001",
        "department": "Maintenance",
        "supplier_id": "SUP-0002",
        "item_category": "spare_parts",
        "item_code": "MRO-BRG-6205",
        "description": "Deep groove ball bearings 6205-2RS for conveyor line 3",
        "quantity": "20",
        "unit_price": "8.40",
        "currency": "EUR",
        "justification": "Preventive maintenance of conveyor line 3 planned in November",
        "delivery_date": "2026-11-05",
        "is_capex": False,
        "attachments": [{"kind": "quote", "file_name": "quote-beta-2026-1012.pdf"}],
    }
    payload.update(changes)
    return payload


@pytest.fixture
def rules() -> RulesConfig:
    return load_rules(ROOT / "config" / "rules.yaml")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """SQLite by default; NEXORA_TEST_DATABASE_URL runs the same tests on
    PostgreSQL (as CI does), on an emptied schema."""
    url = os.environ.get("NEXORA_TEST_DATABASE_URL")
    if not url:
        return Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            llm_provider="scripted",
            gemini_api_key=None,
        )
    engine = make_engine(url)
    Base.metadata.drop_all(engine)
    engine.dispose()
    return Settings(database_url=url, llm_provider="scripted", gemini_api_key=None)


@pytest.fixture
def clock() -> dict[str, datetime]:
    return {"now": NOW}


@pytest.fixture
def client(settings: Settings, clock: dict[str, datetime]) -> TestClient:
    app = create_app(settings, clock=lambda: clock["now"])
    return TestClient(app)


@pytest.fixture
def client_with(settings: Settings, clock: dict[str, datetime]):
    """A client whose AI analysis is done by the given provider."""

    def make(provider) -> TestClient:  # noqa: ANN001
        return TestClient(create_app(settings, clock=lambda: clock["now"], provider=provider))

    return make


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[user]}"}


def eur(value: str) -> Decimal:
    return Decimal(value)
