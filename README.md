# NEXORA AI

**AI-assisted review of purchase requests: deterministic checks, cited explanations, human decisions and a full audit trail.**

> **Status: work in progress (Phase 3 of 9, vertical slice).** Requests are submitted, validated, checked against the purchasing rules, stored and routed. The AI analysis, the review screens and n8n arrive in the next phases. Nothing below describes a feature that is not implemented and tested.

NEXORA AI is an engineering project built around a real business problem: procurement teams spend their time on checks a machine can do (missing fields, duplicates, prices far from the usual, amounts above an approval threshold, unknown suppliers, missing quotes) and rarely write down why a request was approved. It runs on synthetic data for **Nexora Industries, a fictional industrial company**; the purchasing policies it applies are the synthetic documents of [Enterprise AI Knowledge Assistant](https://github.com/Thierry-Daconceicao-Alvares/enterprise-ai-knowledge-assistant). It is not used by a real company, and every figure it reports comes from its test environment.

## What works today

| Step | What happens | Where |
|---|---|---|
| Intake | `POST /requests` with a demo bearer token; an idempotency key stores a resubmitted request once | [`services/intake.py`](src/nexora/services/intake.py) |
| Validation | Every problem reported at once: required fields, formats, quantities, prices, currencies, department, category, delivery date | [`services/validation.py`](src/nexora/services/validation.py) |
| Business rules | Seven rules, each naming the policy it applies: approval band, supplier status, sourcing evidence, CapEx approval, price deviation, duplicate request, split purchase | [`services/rules.py`](src/nexora/services/rules.py), [`config/rules.yaml`](config/rules.yaml) |
| Routing | A category buyer (reviewer) below €50,000; the Head of Procurement (approver) from €50,000 or when a rule raises a high or critical finding | same |
| Audit trail | Every step appended to an event log, which n8n will read; no token or secret is ever stored | [`services/audit.py`](src/nexora/services/audit.py) |
| Permissions | Checked in the services: only requesters and the intake service submit; requesters see only their own requests | [`services/authorization.py`](src/nexora/services/authorization.py) |

The rules are configuration, not code. For example, the approval bands follow the delegation of authority (NX-PUR-002 §2) and the sourcing evidence follows the procurement policy (NX-PUR-001 §5): one quote below €5,000, three from €5,000, a bid comparison from €50,000, an award decision from €250,000.

## Run it

With Docker (API and PostgreSQL):

```bash
git clone https://github.com/Thierry-Daconceicao-Alvares/nexora-ai.git
cd nexora-ai
docker compose up --build
```

Then open http://localhost:8000/docs, click **Authorize**, enter `demo-sophie` (a requester), and try `POST /requests`.

Without Docker (Python 3.12, SQLite):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn nexora.api.main:app --reload
```

Demo tokens (not secrets, listed in [`config/demo_users.yaml`](config/demo_users.yaml)): `demo-sophie` and `demo-marc` (requesters), `demo-karim` (reviewer), `demo-claire` (approver), `demo-intake` (n8n), `demo-admin`.

## Tests

```bash
pytest          # 58 tests: validation, each rule and its thresholds, the API end to end
ruff check .
```

## Roadmap

| Phase | Content | Status |
|---|---|---|
| 1. Product definition | Users, scope, acceptance criteria, risks | Done |
| 2. Architecture | Components, states, data model, API, security boundaries | Done |
| 3. Vertical slice | Intake, validation, rules, storage, routing, audit, tests | **Done** |
| 4. AI and retrieval | Structured analysis with cited policies, insufficient-evidence handling, injection tests | Next |
| 5. Approvals and audit | Review decisions, server-side authorisation, migrations | Planned |
| 6. Interface and n8n | Dashboard, review screens, email intake, notifications, reminders | Planned |
| 7. Evaluation | Labelled scenarios, baselines, latency and cost | Planned |
| 8. Deployment | Public demo, setup from a clean clone | Planned |
| 9. Launch | Screenshots, video | Planned |

## License

[MIT](LICENSE). Author: [Thierry Daconceição Alvares](https://www.linkedin.com/in/thierry-alvares/).
