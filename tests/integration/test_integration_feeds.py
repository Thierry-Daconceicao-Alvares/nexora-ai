"""What n8n and the dashboard read: requests on behalf of a requester, the
outbox of messages, reminders, the weekly digest, the metrics, and the CSV
import."""

from __future__ import annotations

from datetime import timedelta

from tests.conftest import auth, valid_payload

RISKY = valid_payload(
    external_ref="PR-2026-00002",
    supplier_id="SUP-0012",
    quantity="1",
    unit_price="12000",
    item_code=None,
)


def by_email(sender: str) -> dict[str, str]:
    return {**auth("intake"), "On-Behalf-Of": sender}


def outbox(client, after=0):
    response = client.get(f"/integration/outbox?after={after}", headers=auth("intake"))
    assert response.status_code == 200, response.text
    return response.json()


def test_the_intake_service_submits_on_behalf_of_a_requester(client):
    response = client.post(
        "/requests", json=valid_payload(), headers=by_email("Sophie.Martin@nexora.example")
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["requester_id"], body["channel"]) == ("u-sophie", "email")
    mine = client.get("/requests", headers=auth("sophie")).json()
    assert [r["id"] for r in mine] == [body["id"]]


def test_only_known_requesters_can_be_represented(client):
    unknown = client.post("/requests", json=valid_payload(), headers=by_email("x@example.com"))
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["field"] == "on_behalf_of"
    reviewer = client.post(
        "/requests", json=valid_payload(), headers=by_email("karim.benali@nexora.example")
    )
    assert reviewer.status_code == 422
    impersonation = client.post(
        "/requests",
        json=valid_payload(),
        headers={**auth("sophie"), "On-Behalf-Of": "marc.leroy@nexora.example"},
    )
    assert impersonation.status_code == 403


def test_the_outbox_says_who_to_tell_and_moves_with_the_cursor(client):
    request = client.post("/requests", json=valid_payload(), headers=auth("sophie")).json()
    first = outbox(client)
    [review] = first["items"]
    assert review["kind"] == "review_needed"
    assert [r["email"] for r in review["recipients"]] == ["karim.benali@nexora.example"]
    assert review["subject"] == "[NEXORA] To review: PR-2026-00001"
    assert f"?request={request['id']}" in review["text"]
    assert outbox(client, first["next_cursor"])["items"] == []

    client.post(
        f"/requests/{request['id']}/decisions",
        json={"action": "request_info", "reason": "Which conveyor line exactly?", "version": 1},
        headers=auth("karim"),
    )
    [info] = outbox(client, first["next_cursor"])["items"]
    assert info["kind"] == "info_requested"
    assert [r["email"] for r in info["recipients"]] == ["sophie.martin@nexora.example"]
    assert info["reason"] == "Which conveyor line exactly?"
    assert "Which conveyor line exactly?" in info["text"]


def test_approval_and_rejection_messages_go_to_the_requester(client):
    risky = client.post("/requests", json=RISKY, headers=auth("sophie")).json()
    reason = {"reason": "Supplier blocked in the vendor master.", "version": 1}
    client.post(
        f"/requests/{risky['id']}/decisions",
        json={"action": "approve", **reason},
        headers=auth("karim"),
    )
    client.post(
        f"/requests/{risky['id']}/decisions",
        json={"action": "reject", **reason},
        headers=auth("claire"),
    )
    kinds = [(i["kind"], i["recipients"][0]["role"]) for i in outbox(client)["items"]]
    assert kinds == [
        ("review_needed", "reviewer"),
        ("approval_needed", "approver"),
        ("rejected", "requester"),
    ]


def test_reminders_list_requests_waiting_too_long(client, clock):
    client.post("/requests", json=valid_payload(), headers=auth("sophie"))
    assert client.get("/integration/reminders", headers=auth("intake")).json() == []
    clock["now"] += timedelta(hours=50)
    [item] = client.get("/integration/reminders", headers=auth("intake")).json()
    assert (item["waiting_for"], item["waiting_hours"]) == ("reviewer", 50)
    assert item["recipients"][0]["email"] == "karim.benali@nexora.example"
    later = client.get("/integration/reminders?older_than_hours=72", headers=auth("intake"))
    assert later.json() == []


def test_the_digest_goes_to_the_approver_with_measured_figures(client):
    client.post("/requests", json=valid_payload(), headers=auth("sophie"))
    client.post("/requests", json=RISKY, headers=auth("sophie"))
    digest = client.get("/integration/digest", headers=auth("intake")).json()
    assert [r["email"] for r in digest["recipients"]] == ["claire.dubois@nexora.example"]
    assert "Submitted: 2 for EUR 12,168.00" in digest["text"]
    assert "supplier_status (1)" in digest["text"]


def test_the_feeds_are_for_the_integration_service(client):
    for path in ("/integration/outbox", "/integration/reminders", "/integration/digest"):
        assert client.get(path, headers=auth("karim")).status_code == 403
        assert client.get(path, headers=auth("sophie")).status_code == 403


def test_metrics_come_from_the_stored_data(client, clock):
    small = client.post("/requests", json=valid_payload(), headers=auth("sophie")).json()
    client.post("/requests", json=RISKY, headers=auth("sophie"))
    clock["now"] += timedelta(hours=5)
    client.post(
        f"/requests/{small['id']}/decisions",
        json={"action": "approve", "reason": "Within budget, quote attached.", "version": 1},
        headers=auth("karim"),
    )
    figures = client.get("/metrics", headers=auth("claire")).json()
    assert figures["requests"]["total"] == 2
    assert figures["requests"]["by_status"] == {"approved": 1, "awaiting_review": 1}
    assert figures["queue"]["awaiting_review"] == 1
    assert figures["queue"]["oldest_waiting_hours"] == 5.0
    assert figures["exceptions"]["by_rule"] == {"supplier_status": 1, "sourcing_evidence": 1}
    assert figures["decisions"]["cycle_time_hours_median"] == 5.0
    assert figures["ai"]["by_provider"] == {"scripted": 2}
    assert figures["ai"]["estimated_cost_usd"] == 0
    assert sum(d["requests"] for d in figures["requests"]["daily"]) == 2
    assert client.get("/metrics", headers=auth("sophie")).status_code == 403


CSV = """external_ref,department,supplier_id,item_category,item_code,description,quantity,unit_price,currency,justification,delivery_date,is_capex,attachments
PR-2026-00101,Maintenance,SUP-0002,spare_parts,MRO-BRG-6205,Ball bearings 6205-2RS for line 3,20,8.40,EUR,Preventive maintenance of line 3,2026-11-05,false,quote:q1.pdf
PR-2026-00102,Maintenance,SUP-0002,spare_parts,,Ball bearings for the crusher,10,31.50,JPY,Crusher overhaul in November,2026-11-05,no,
PR-2026-00103,Production,SUP-0012,spare_parts,,Rewiring of the lighting in hall B,1,12000,EUR,Safety inspection of September,2026-11-20,false,quote:a.pdf|specification:spec.pdf
"""  # noqa: E501


def import_csv(client, text, user="sophie"):
    files = {"file": ("requests.csv", text.encode("utf-8"), "text/csv")}
    return client.post("/requests/import", files=files, headers=auth(user))


def test_csv_import_reports_every_row(client):
    response = import_csv(client, CSV)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["rows"], body["created"], body["refused"]) == (3, 2, 1)
    lines = {r["line"]: r for r in body["results"]}
    assert lines[2]["status"] == "created"
    assert lines[3]["status"] == "refused"
    assert lines[3]["errors"][0]["field"] == "currency"
    assert (lines[4]["route"], lines[4]["highest_severity"]) == ("approver", "critical")
    stored = client.get("/requests", headers=auth("sophie")).json()
    assert {r["channel"] for r in stored} == {"csv"}

    again = import_csv(client, CSV).json()
    assert (again["created"], again["already_submitted"], again["refused"]) == (0, 2, 1)


def test_a_csv_with_unknown_columns_is_refused(client):
    response = import_csv(client, "ref,amount\nPR-2026-00001,10\n")
    assert response.status_code == 422
    assert "Unknown or missing columns" in response.json()["detail"]["message"]


def test_a_semicolon_separated_csv_is_accepted(client):
    response = import_csv(client, CSV.replace(",", ";").replace("8;40", "8.40"))
    assert response.status_code == 200
    assert response.json()["created"] == 2


def test_reviewers_cannot_import(client):
    assert import_csv(client, CSV, user="karim").status_code == 403
