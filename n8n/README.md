# n8n workflows

n8n handles the edges of NEXORA AI: email in, emails out. The backend keeps
every rule, every permission and the choice of who is told what; n8n reads what
the backend exposes to its service account (`demo-intake`) and delivers.

| Workflow | When | What it does |
|---|---|---|
| [1 - Email intake](workflows/1-email-intake.json) | every minute | Reads the unread emails sent to `purchasing@nexora.example`, turns each one into a request (one `Label: value` line per field, attachments recognised by file name), submits it **on behalf of the sender** with an idempotency key, and answers the sender: received, refused with the reasons, or not understood with the template |
| [2 - Notifications](workflows/2-notifications.json) | every minute | Reads `/integration/outbox` from its cursor and emails each recipient: the category buyer (to review), the Head of Procurement (to approve), the requester (information needed, approved, rejected). The cursor moves only after the emails are sent |
| [3 - Reminders](workflows/3-reminders.json) | working days, 08:15 | Reminds whoever a request has been waiting for, for more than 48 hours |
| [4 - Weekly digest](workflows/4-weekly-digest.json) | Mondays, 07:45 | Sends the Head of Procurement the figures of the week, computed by the backend |

Locally, Mailpit is the mailbox: n8n sends through its SMTP server and reads
the purchasing mailbox through its API, and every message stays on the
machine (http://localhost:8025). In production, the SMTP credential would point
to the company's mail server and an IMAP or Outlook trigger would replace the
first two nodes of the intake.

## Run

`docker compose up --build` starts n8n with these workflows imported and
published ([start.sh](start.sh) runs at every start). Open http://localhost:5678
to see them; n8n asks to create a local owner account the first time.

To submit a request by email, send it to `purchasing@nexora.example` through
Mailpit's SMTP server (`localhost:1025`), from the address of a demo requester
such as `sophie.martin@nexora.example`, with a body like:

```
Reference: PR-2026-01234
Department: Maintenance
Supplier: SUP-0002
Category: spare_parts
Item code: MRO-BRG-6205
Description: Ball bearings 6205-2RS for conveyor line 3
Quantity: 20
Unit price: 8.40
Currency: EUR
Justification: Preventive maintenance of conveyor line 3
Needed by: 2026-12-01
CapEx: no
```

and a file named like `quote-beta.pdf` attached. The answer arrives in Mailpit
within a minute.

## Tested

[`scripts/e2e_n8n.py`](../scripts/e2e_n8n.py) sends three emails (a valid
request, an unknown sender, an email outside the template), then checks the
answers, the stored request, the notification of the buyer, the message to the
requester after a decision and the weekly digest. It runs in CI against the
whole Docker Compose stack.
