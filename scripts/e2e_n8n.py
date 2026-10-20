"""End-to-end check of the n8n workflows against a running stack.

Sends emails to the purchasing mailbox (Mailpit SMTP), then waits for n8n to
submit them to NEXORA and to answer, for the notification of the reviewer,
for the message to the requester after a decision, and for the weekly digest.

    python scripts/e2e_n8n.py --api http://localhost:8000 --mailpit http://localhost:8025 \
        --smtp localhost:1025 --digest-command "docker compose exec -T n8n n8n execute --id ..."

Exits with 1 at the first expectation not met, after printing what it saw.
"""

from __future__ import annotations

import argparse
import shlex
import smtplib
import subprocess
import sys
import time
from email.message import EmailMessage

import httpx

PURCHASING = "purchasing@nexora.example"
SOPHIE = "sophie.martin@nexora.example"


def form(ref: str, **fields: str) -> str:
    values = {
        "Reference": ref,
        "Department": "Maintenance",
        "Supplier": "SUP-0002",
        "Category": "spare_parts",
        "Item code": "MRO-BRG-6205",
        "Description": "Ball bearings 6205-2RS for conveyor line 3",
        "Quantity": "20",
        "Unit price": "8.40",
        "Currency": "EUR",
        "Justification": "Preventive maintenance of conveyor line 3",
        "Needed by": "2099-01-15",
        "CapEx": "no",
        **fields,
    }
    lines = [f"{k}: {v}" for k, v in values.items() if v]
    return "Hello,\n\nPlease find my purchase request below.\n\n" + "\n".join(lines) + "\n"


def send(smtp: str, sender: str, subject: str, body: str, files: list[str]) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, PURCHASING, subject
    message.set_content(body)
    for name in files:
        message.add_attachment(
            b"%PDF-1.4 demo", maintype="application", subtype="pdf", filename=name
        )
    host, port = smtp.split(":")
    with smtplib.SMTP(host, int(port)) as server:
        server.send_message(message)


def wait_for_email(mailpit: str, to: str, subject_start: str, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    seen: list[str] = []
    while time.time() < deadline:
        messages = httpx.get(f"{mailpit}/api/v1/messages", params={"limit": 500}).json()
        for m in messages.get("messages", []):
            addresses = [a["Address"] for a in m.get("To", [])]
            if to in addresses and m["Subject"].startswith(subject_start):
                return httpx.get(f"{mailpit}/api/v1/message/{m['ID']}").json()
        seen = [
            f"{m['Subject']} -> {[a['Address'] for a in m['To']]}"
            for m in messages.get("messages", [])
        ]
        time.sleep(3)
    print(f"FAIL: no email '{subject_start}...' to {to} within {timeout} s. Seen:")
    print("\n".join(f"  {s}" for s in seen))
    sys.exit(1)


def check(condition: bool, message: str, context: object = None) -> None:
    print(("ok    " if condition else "FAIL  ") + message)
    if not condition:
        if context is not None:
            print(context)
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--mailpit", default="http://localhost:8025")
    parser.add_argument("--smtp", default="localhost:1025")
    parser.add_argument("--digest-command", help="command that runs the digest workflow once")
    args = parser.parse_args()
    karim = {"Authorization": "Bearer demo-karim"}

    # 1. A request by email, with a quote attached.
    send(
        args.smtp,
        f"Sophie Martin <{SOPHIE}>",
        "Purchase request bearings",
        form("PR-2026-07001"),
        ["quote-beta-bearings.pdf"],
    )
    # 2. An unknown sender, and 3. an email that does not follow the template.
    send(args.smtp, "Someone <someone@example.com>", "Request", form("PR-2026-07002"), [])
    send(
        args.smtp,
        f"Sophie Martin <{SOPHIE}>",
        "Bearings please",
        "Hi, can you order 20 bearings for line 3? Thanks",
        [],
    )

    reply = wait_for_email(args.mailpit, SOPHIE, "[NEXORA] Received: PR-2026-07001")
    # A category buyer, or the Head of Procurement when a rule finds a possible duplicate.
    check(
        "It will be reviewed by" in reply["Text"],
        "the requester is told who will review",
        reply["Text"],
    )
    requests = httpx.get(f"{args.api}/requests", headers=karim).json()
    request = next((r for r in requests if r["external_ref"] == "PR-2026-07001"), None)
    check(request is not None, "the emailed request is stored in NEXORA")
    check(
        request["channel"] == "email" and request["requester_id"] == "u-sophie",
        "it belongs to Sophie and came by email",
    )
    detail = httpx.get(f"{args.api}/requests/{request['id']}", headers=karim).json()
    check(
        detail["attachments"] == [{"kind": "quote", "file_name": "quote-beta-bearings.pdf"}],
        "the attached quote is recorded",
    )

    refused = wait_for_email(args.mailpit, "someone@example.com", "[NEXORA] Not submitted")
    check("not a known requester" in refused["Text"], "an unknown sender is refused")
    wait_for_email(args.mailpit, SOPHIE, "[NEXORA] Not understood")
    print("ok    an email outside the template is sent back with the template")

    # 4. The reviewer is notified, then the requester after a decision.
    wait_for_email(args.mailpit, "karim.benali@nexora.example", "[NEXORA] To review: PR-2026-07001")
    print("ok    the category buyer is notified")
    decision = httpx.post(
        f"{args.api}/requests/{request['id']}/decisions",
        json={
            "action": "request_info",
            "reason": "Which conveyor line exactly?",
            "version": detail["version"],
        },
        headers=karim,
    )
    check(decision.status_code == 201, "the buyer asks for information")
    asked = wait_for_email(args.mailpit, SOPHIE, "[NEXORA] Information needed: PR-2026-07001")
    check("Which conveyor line exactly?" in asked["Text"], "the requester receives the question")

    # 5. The weekly digest, run once.
    if args.digest_command:
        subprocess.run(shlex.split(args.digest_command), check=True)
        digest = wait_for_email(
            args.mailpit, "claire.dubois@nexora.example", "[NEXORA] Weekly digest", timeout=60
        )
        check("Submitted:" in digest["Text"], "the Head of Procurement receives the digest")
    print("All n8n workflows behaved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
