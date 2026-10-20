"""The vertical slice through HTTP: submission, validation, rules, storage,
routing, audit trail, permissions and idempotency."""

from __future__ import annotations

from tests.conftest import auth, valid_payload


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_valid_request_is_checked_stored_and_routed(client):
    response = client.post("/requests", json=valid_payload(), headers=auth("sophie"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "awaiting_review"
    assert body["route"] == "reviewer"
    assert body["amount_eur"] == 168.0
    assert body["highest_severity"] == "info"
    rule_ids = [c["rule_id"] for c in body["checks"] if c["stage"] == "rule"]
    assert rule_ids == [
        "approval_band",
        "supplier_status",
        "sourcing_evidence",
        "capex_approval",
        "price_deviation",
        "duplicate_request",
        "split_purchase",
    ]

    detail = client.get(f"/requests/{body['id']}", headers=auth("karim")).json()
    events = [(e["type"], e["payload"].get("to_status")) for e in detail["audit"]]
    assert events == [
        ("request.submitted", None),
        ("request.status_changed", "validated"),
        ("rules.evaluated", None),
        ("analysis.completed", None),
        ("request.status_changed", "analysed"),
        ("request.status_changed", "awaiting_review"),
    ]


def test_invalid_request_lists_every_error_and_is_not_stored(client):
    payload = valid_payload(currency="JPY", quantity="-1", delivery_date="2026-01-01")
    response = client.post("/requests", json=payload, headers=auth("sophie"))
    assert response.status_code == 422
    errors = {e["field"]: e["rule_id"] for e in response.json()["detail"]["errors"]}
    assert errors == {"quantity": "schema.greater_than", "currency": "currency.unsupported"}
    assert client.get("/requests", headers=auth("karim")).json() == []
    feed = client.get("/events", headers=auth("intake")).json()
    assert [e["type"] for e in feed] == ["request.validation_failed"]


def test_flags_and_routing_for_a_risky_request(client):
    payload = valid_payload(
        external_ref="PR-2026-00002",
        supplier_id="SUP-0012",  # blocked
        quantity="1",
        unit_price="12000",
        item_code=None,
    )
    body = client.post("/requests", json=payload, headers=auth("sophie")).json()
    flags = {c["rule_id"]: c["severity"] for c in body["checks"] if c["outcome"] == "flag"}
    assert flags == {"supplier_status": "critical", "sourcing_evidence": "medium"}
    assert body["route"] == "approver"
    assert body["highest_severity"] == "critical"


def test_authentication_and_roles(client):
    assert client.post("/requests", json=valid_payload()).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.post("/requests", json=valid_payload(), headers=bad).status_code == 401
    response = client.post("/requests", json=valid_payload(), headers=auth("karim"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_requesters_only_see_their_own_requests(client):
    created = client.post("/requests", json=valid_payload(), headers=auth("sophie")).json()
    assert client.get(f"/requests/{created['id']}", headers=auth("marc")).status_code == 404
    assert client.get(f"/requests/{created['id']}", headers=auth("sophie")).status_code == 200
    assert client.get("/requests", headers=auth("marc")).json() == []
    assert len(client.get("/requests", headers=auth("karim")).json()) == 1


def test_same_submission_twice_is_stored_once(client):
    headers = {**auth("sophie"), "Idempotency-Key": "form-7f3a"}
    first = client.post("/requests", json=valid_payload(), headers=headers)
    second = client.post("/requests", json=valid_payload(), headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/requests", headers=auth("karim")).json()) == 1


def test_reused_key_or_reference_is_a_conflict(client):
    headers = {**auth("sophie"), "Idempotency-Key": "form-7f3a"}
    client.post("/requests", json=valid_payload(), headers=headers)
    changed = client.post("/requests", json=valid_payload(quantity="21"), headers=headers)
    assert changed.status_code == 409
    other_key = {**auth("sophie"), "Idempotency-Key": "form-9b10"}
    same_ref = client.post("/requests", json=valid_payload(quantity="21"), headers=other_key)
    assert same_ref.status_code == 409


def test_duplicate_and_split_detection_across_requests(client):
    first = valid_payload(
        external_ref="PR-2026-00010", quantity="1", unit_price="4000", item_code=None
    )
    client.post("/requests", json=first, headers=auth("sophie"))
    second = valid_payload(
        external_ref="PR-2026-00011", quantity="1", unit_price="4000", item_code=None
    )
    body = client.post("/requests", json=second, headers=auth("sophie")).json()
    flags = {c["rule_id"] for c in body["checks"] if c["outcome"] == "flag"}
    assert flags == {"duplicate_request", "split_purchase"}


def test_event_feed_is_for_the_integration_service_only(client):
    client.post("/requests", json=valid_payload(), headers=auth("sophie"))
    assert client.get("/events", headers=auth("karim")).status_code == 403
    feed = client.get("/events", headers=auth("intake")).json()
    assert len(feed) == 6
    later = client.get(f"/events?after={feed[1]['id']}", headers=auth("intake")).json()
    assert [e["id"] for e in later] == [e["id"] for e in feed[2:]]


def test_audit_never_contains_tokens(client):
    client.post("/requests", json=valid_payload(), headers=auth("sophie"))
    feed = client.get("/events", headers=auth("admin")).text
    assert "demo-sophie" not in feed
    assert "Bearer" not in feed


def test_other_currency_is_converted(client):
    payload = valid_payload(currency="USD", unit_price="9.13")
    body = client.post("/requests", json=payload, headers=auth("sophie")).json()
    assert body["amount_eur"] == 167.99  # 20 x 9.13 USD x 0.92
    price = next(c for c in body["checks"] if c["rule_id"] == "price_deviation")
    assert price["outcome"] == "pass"


def test_the_analysis_cites_the_policies_behind_the_findings(client):
    payload = valid_payload(
        external_ref="PR-2026-00003",
        supplier_id="SUP-0012",
        quantity="1",
        unit_price="12000",
        item_code=None,
    )
    created = client.post("/requests", json=payload, headers=auth("sophie")).json()
    analysis = client.get(f"/requests/{created['id']}", headers=auth("karim")).json()["analysis"]
    assert analysis["status"] == "completed"
    assert analysis["provider"] == "scripted"
    assert analysis["verification"] == "verified"
    assert [c["passage_id"] for c in analysis["citations"]] == ["NX-PUR-003 §1", "NX-PUR-001 §5"]
    assert "vendor master" in analysis["citations"][0]["text"]
    assert analysis["output"]["recommendation"]["action"] == "reject"
    retrieved = {r["passage_id"]: r["reason"] for r in analysis["retrieved"]}
    assert retrieved["NX-PUR-002 §2"] == "rule:approval_band"


def test_health_names_the_ai_provider(client):
    body = client.get("/health").json()
    assert (body["ai_provider"], body["ai_model"]) == ("scripted", "scripted-v1")
