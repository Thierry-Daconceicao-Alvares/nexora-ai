"""Review decisions through HTTP: the workflow, who may decide what, one
decision per transition, mandatory reasons and the audit of every decision."""

from __future__ import annotations

import pytest

from tests.conftest import auth, valid_payload

SMALL = valid_payload()  # €168, no finding: route reviewer
RISKY = valid_payload(  # blocked supplier, one quote for €12,000: route approver
    external_ref="PR-2026-00002",
    supplier_id="SUP-0012",
    quantity="1",
    unit_price="12000",
    item_code=None,
)
REASON = "Checked against the policy and the attached quote."


def submit(client, payload=SMALL, user="sophie"):
    response = client.post("/requests", json=payload, headers=auth(user))
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, request, user, action, reason=REASON, version=None):
    body = {"action": action, "reason": reason, "version": version or request["version"]}
    return client.post(f"/requests/{request['id']}/decisions", json=body, headers=auth(user))


def detail(client, request, user="karim"):
    return client.get(f"/requests/{request['id']}", headers=auth(user)).json()


def test_a_reviewer_approves_a_request_within_their_authority(client):
    request = submit(client)
    assert detail(client, request)["allowed_actions"] == [
        "approve",
        "reject",
        "request_info",
        "escalate",
    ]
    response = decide(client, request, "karim", "approve")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "approved"

    after = detail(client, request)
    assert after["status"] == "approved"
    assert after["allowed_actions"] == []
    [decision] = after["decisions"]
    assert (decision["actor_id"], decision["role"], decision["action"]) == (
        "u-karim",
        "reviewer",
        "approve",
    )
    assert decision["reason"] == REASON
    assert (decision["from_status"], decision["to_status"]) == ("awaiting_review", "approved")


def test_a_request_above_the_reviewer_authority_needs_the_approver(client):
    request = submit(client, RISKY)
    assert request["route"] == "approver"
    assert decide(client, request, "karim", "approve").json()["status"] == "awaiting_approver"
    assert detail(client, request, "claire")["allowed_actions"] == [
        "approve",
        "reject",
        "request_info",
    ]
    assert decide(client, request, "claire", "approve").json()["status"] == "approved"

    decisions = detail(client, request)["decisions"]
    assert [d["role"] for d in decisions] == ["reviewer", "approver"]
    # The approval against a critical finding is written down as such.
    assert decisions[1]["evidence"]["approved_despite"] == ["supplier_status"]


def test_a_reviewer_escalates_and_the_approver_rejects(client):
    request = submit(client)
    escalated = decide(client, request, "karim", "escalate").json()
    assert escalated["status"] == "awaiting_approver"
    assert detail(client, request)["route"] == "approver"
    assert decide(client, request, "claire", "reject").json()["status"] == "rejected"


def test_every_decision_is_in_the_audit_trail_with_its_evidence(client):
    request = submit(client, RISKY)
    decide(client, request, "karim", "reject", reason="Supplier blocked in the vendor master.")
    events = detail(client, request, "admin")["audit"]
    recorded = next(e for e in events if e["type"] == "decision.recorded")
    assert recorded["actor_id"] == "u-karim"
    payload = recorded["payload"]
    assert payload["reason"] == "Supplier blocked in the vendor master."
    assert payload["version"] == 1
    flags = {f["rule_id"]: f["severity"] for f in payload["evidence"]["flags"]}
    assert flags == {"supplier_status": "critical", "sourcing_evidence": "medium"}
    analysis = payload["evidence"]["analysis"]
    assert (analysis["provider"], analysis["verification"], analysis["recommendation"]) == (
        "scripted",
        "verified",
        "reject",
    )
    assert analysis["citations"] == ["NX-PUR-003 §1", "NX-PUR-001 §5"]
    assert [e["type"] for e in events][-2:] == ["request.status_changed", "request.rejected"]


@pytest.mark.parametrize(
    ("user", "status"),
    [
        ("sophie", 403),  # a requester never decides
        ("claire", 403),  # the approver acts after the reviewer, not before
        ("admin", 403),  # administration is not a purchasing authority
        ("intake", 404),  # the n8n service account does not even see it
        ("marc", 404),  # another requester does not even see the request
    ],
)
def test_only_the_reviewer_decides_on_a_request_awaiting_review(client, user, status):
    request = submit(client)
    response = decide(client, request, user, "approve")
    assert response.status_code == status, response.text
    assert detail(client, request)["status"] == "awaiting_review"
    assert detail(client, request)["decisions"] == []


def test_the_reviewer_cannot_take_the_approver_decision(client):
    request = submit(client, RISKY)
    decide(client, request, "karim", "approve")
    response = decide(client, request, "karim", "approve")
    assert response.status_code == 403
    assert "waits for the approver" in response.json()["detail"]["message"]


def test_a_decision_is_taken_once(client):
    request = submit(client)
    assert decide(client, request, "karim", "approve").status_code == 201
    second = decide(client, request, "karim", "reject")
    assert second.status_code == 409
    assert detail(client, request)["status"] == "approved"


def test_the_approver_cannot_escalate(client):
    request = submit(client, RISKY)
    decide(client, request, "karim", "escalate")
    assert decide(client, request, "claire", "escalate").status_code == 409


def test_a_decision_on_an_outdated_version_is_refused(client):
    request = submit(client)
    response = decide(client, request, "karim", "approve", version=2)
    assert response.status_code == 409
    assert "version 1 is current" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "approve", "version": 1},
        {"action": "approve", "reason": "ok", "version": 1},
        {"action": "approve", "reason": "    ok        ", "version": 1},
        {"action": "order", "reason": REASON, "version": 1},
        {"action": "approve", "reason": REASON},
    ],
)
def test_a_reason_and_a_known_action_are_required(client, body):
    request = submit(client)
    response = client.post(f"/requests/{request['id']}/decisions", json=body, headers=auth("karim"))
    assert response.status_code == 422
    assert detail(client, request)["status"] == "awaiting_review"


def test_queues_list_what_each_person_can_act_on(client):
    small = submit(client)
    risky = submit(client, RISKY)
    decide(client, risky, "karim", "approve")
    karim = client.get("/requests?actionable=true", headers=auth("karim")).json()
    claire = client.get("/requests?actionable=true", headers=auth("claire")).json()
    assert [r["id"] for r in karim] == [small["id"]]
    assert [r["id"] for r in claire] == [risky["id"]]
    assert client.get("/requests?actionable=true", headers=auth("sophie")).json() == []


# ------------------------------------------------------- information requested


def test_the_requester_completes_a_request_and_it_is_checked_again(client):
    request = submit(client, RISKY)
    decide(client, request, "karim", "request_info", reason="Please attach two more quotes.")
    assert detail(client, request, "sophie")["status"] == "info_requested"

    completed = dict(
        RISKY,
        supplier_id="SUP-0004",  # an active supplier
        item_category="facility_services",
        attachments=[{"kind": "quote", "file_name": f"q{i}.pdf"} for i in range(3)],
    )
    response = client.put(f"/requests/{request['id']}", json=completed, headers=auth("sophie"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["version"], body["status"]) == (2, "awaiting_review")
    assert {c["rule_id"] for c in body["checks"] if c["outcome"] == "flag"} == set()
    assert body["route"] == "reviewer"
    assert body["analysis"]["output"]["recommendation"]["action"] == "approve"

    # A decision taken on what the reviewer saw before is refused.
    assert decide(client, request, "karim", "approve", version=1).status_code == 409
    approved = decide(client, request, "karim", "approve", version=2)
    assert approved.json()["status"] == "approved"
    versions = [d["version"] for d in detail(client, request)["decisions"]]
    assert versions == [1, 2]


def test_only_the_requester_completes_and_only_when_asked(client):
    request = submit(client, RISKY)
    url = f"/requests/{request['id']}"
    assert client.put(url, json=RISKY, headers=auth("sophie")).status_code == 409  # not asked
    decide(client, request, "karim", "request_info", reason="Please attach two more quotes.")
    assert client.put(url, json=RISKY, headers=auth("karim")).status_code == 403
    assert client.put(url, json=RISKY, headers=auth("marc")).status_code == 404


def test_an_invalid_completion_changes_nothing(client):
    request = submit(client, RISKY)
    decide(client, request, "karim", "request_info", reason="Please attach two more quotes.")
    url = f"/requests/{request['id']}"
    renamed = client.put(
        url, json=dict(RISKY, external_ref="PR-2026-00999"), headers=auth("sophie")
    )
    assert renamed.status_code == 422
    assert renamed.json()["detail"]["field"] == "external_ref"
    invalid = client.put(url, json=dict(RISKY, quantity="-1"), headers=auth("sophie"))
    assert invalid.status_code == 422
    after = detail(client, request, "sophie")
    assert (after["status"], after["version"]) == ("info_requested", 1)
