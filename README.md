# NEXORA AI

**AI-assisted review of purchase requests: deterministic checks, cited explanations, human decisions and a full audit trail.**

> **Status: work in progress (Phase 7 of 9).** Requests arrive by form, CSV file, API or email; they are validated, checked against the purchasing rules, screened, analysed by a language model with cited policies, verified in code, routed, and decided in a review interface by the people whose role allows it; n8n handles the emails. It is evaluated on a labelled set, failures included. The public demo and the launch come next. Nothing below describes a feature that is not implemented and tested.

![The review screen: findings, AI analysis, decision panel](docs/images/review.png)

NEXORA AI is an engineering project built around a real business problem: procurement teams spend their time on checks a machine can do (missing fields, duplicates, prices far from the usual, amounts above an approval threshold, unknown suppliers, missing quotes) and rarely write down why a request was approved. It runs on synthetic data for **Nexora Industries, a fictional industrial company**; the purchasing policies it applies are the synthetic documents of [Enterprise AI Knowledge Assistant](https://github.com/Thierry-Daconceicao-Alvares/enterprise-ai-knowledge-assistant). It is not used by a real company, and every figure it reports comes from its test environment.

## What works today

| Step | What happens | Where |
|---|---|---|
| Intake | A form in the interface, a CSV file (each row stored or refused on its own), the API, or an email to the purchasing mailbox through n8n (submitted on behalf of the sender, who must be a known requester); an idempotency key stores a resubmitted request once | [`services/intake.py`](src/nexora/services/intake.py), [`services/csv_import.py`](src/nexora/services/csv_import.py) |
| Validation | Every problem reported at once: required fields, formats, quantities, prices, currencies, department, category, delivery date | [`services/validation.py`](src/nexora/services/validation.py) |
| Business rules | Seven rules, each naming the policy it applies: approval band, supplier status, sourcing evidence, CapEx approval, price deviation, duplicate request, split purchase | [`services/rules.py`](src/nexora/services/rules.py), [`config/rules.yaml`](config/rules.yaml) |
| Screening | Text addressed to an AI system in the description, justification or attachment names ("ignore the previous instructions", "you must approve") is flagged as a high finding | [`services/screening.py`](src/nexora/services/screening.py) |
| Retrieval | The policy sections cited by the flagged rules, plus the best lexical (BM25) matches among the 36 sections of the Nexora policies | [`services/retrieval.py`](src/nexora/services/retrieval.py) |
| AI analysis | One model call: summary, explanation of each finding with citations, missing information, draft recommendation; then verified in code (see below) | [`services/analysis.py`](src/nexora/services/analysis.py) |
| Routing | A category buyer (reviewer) below €50,000; the Head of Procurement (approver) from €50,000 or when a rule or the screen raises a high or critical finding. The AI analysis never changes the route | [`services/rules.py`](src/nexora/services/rules.py) |
| Review decisions | The category buyer approves, rejects, asks for information or escalates; the Head of Procurement decides on requests routed or escalated to her. A reason is always required, and each decision is stored with the evidence the decider had (findings, AI recommendation and its verification, cited passages) | [`services/review.py`](src/nexora/services/review.py), [`domain/workflow.py`](src/nexora/domain/workflow.py) |
| Information requested | The requester completes the request (`PUT /requests/{id}`): a new version, and every check, the screen and the analysis run again | [`services/intake.py`](src/nexora/services/intake.py) |
| Audit trail | Every step and every decision (who, when, what, why, on which version, with which evidence) appended to an event log, which n8n will read; no token, secret, prompt or request text is stored in it | [`services/audit.py`](src/nexora/services/audit.py) |
| Permissions | Checked in the services: only requesters and the intake service submit; requesters see only their own requests; only the role a request waits for decides, never on its own request, once per transition (compare-and-set) and on the version it saw | [`services/authorization.py`](src/nexora/services/authorization.py), [`services/review.py`](src/nexora/services/review.py) |
| Interface | Streamlit: the requester's requests and form, the buyer's and the approver's queue ordered by the most serious finding, the review screen with the decision panel, a dashboard, the audit log. It only calls the API, so it has the permissions of any client | [`app/`](app) |
| Dashboard | Queue, oldest wait, findings by rule, decisions, median time to a decision, AI verification and estimated cost, all computed by the API from the stored data | [`services/metrics.py`](src/nexora/services/metrics.py) |
| n8n | Email intake, notifications (to review, to approve, information needed, decided), reminders after 48 hours, weekly digest. The backend chooses who is told what; n8n delivers | [`n8n/`](n8n) |
| Database migrations | Alembic, applied at start-up; a database created before the migrations is taken over | [`db/migrations`](src/nexora/db/migrations) |

The rules are configuration, not code. For example, the approval bands follow the delegation of authority (NX-PUR-002 §2) and the sourcing evidence follows the procurement policy (NX-PUR-001 §5): one quote below €5,000, three from €5,000, a bid comparison from €50,000, an award decision from €250,000.

## How the AI analysis is kept honest

The model is given three labelled blocks: the rule results (facts it must not contradict), the retrieved policy passages (the only text it may cite) and the request itself, marked as untrusted data and escaped so that it cannot close its block. It has no tools. Its JSON answer is then checked in code before anyone sees it:

| Check | What happens when it fails |
|---|---|
| The answer matches the schema | One retry, then the analysis is recorded as unavailable; the request is still checked and routed |
| Each citation names a passage that was retrieved | The citation is removed (`corrected`) |
| Each explanation concerns a rule that actually flagged | The explanation is removed (`corrected`) |
| Every flagged rule is explained | The analysis is marked `unverified` |
| Every figure (amount, threshold, percentage) appears in the input; counts up to 10 are allowed | The analysis is marked `unverified` and the figure is listed |
| Every quotation appears in the input | The analysis is marked `unverified` and the quotation is listed |
| The recommendation does not approve against a high or critical finding | Replaced by `escalate`, marked `unverified` |
| The recommendation rests on at least one valid citation | Replaced by `request_info` (insufficient evidence) |

The reviewer sees the verification status, the list of issues and the cited passages in full. The prompt is not stored, only its version (`analysis-v1`); the model, tokens, latency and estimated cost of each call are.

**Providers.** With a `MISTRAL_API_KEY`, Mistral (`ministral-14b-latest`, served on Mistral's free plan) does the analysis; Gemini is also supported (`GEMINI_API_KEY`). Both sit behind one interface, with a strict JSON schema, a timeout and bounded retries. Without a key, a **scripted stand-in** fills the same JSON from the rule results with templates, so the whole pipeline runs with no account and no network; it is not a language model, and its analyses are labelled `provider: scripted`. The tests use the scripted provider and fake models (an obedient model that follows an injection, a model that is down, answers outside the schema); the Mistral and Gemini providers are tested against mock HTTP and SDK clients.

**Live check.** Six scenario requests through the pipeline with Mistral on 20 October 2026: 6 of 6 answers in the schema at the first attempt and verified, about 3.7 to 7.2 seconds and 1,900 to 3,100 tokens per request (about $0.0005 at list price), no route changed by the model. One earlier run produced an invented quotation, which led to the quotation check. Details, limits and how to reproduce: [docs/live-check.md](docs/live-check.md).

## Evaluation

Labelled synthetic requests run through the whole application: a development set (156 requests, 30 scenarios) used to improve the prompt, and a held-out set (153 requests, other items and phrasings) committed before any tuning ([method and all runs](docs/evaluation.md)). With Mistral (`ministral-14b-latest`, free plan), prompt v4, [held-out set](eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v4-holdout/report.md):

| Criterion | Target | Result |
|---|---|---|
| Malformed requests rejected, with the fields to fix | 100% | 12/12 |
| Rules and routing as labelled | 100% | 141/141 |
| Repeated submissions processed once | 0 double records | 0 |
| Valid end state when the model answers outside the schema or times out | 100% | 282/282 |
| Spend category, against a keyword baseline (88.7%) | above | 97.2% |
| Citations supporting the statement | ≥ 90% | **82.5%, not met** |
| Unsupported figures, quotations, citations, explanations, contradictions | shown, never hidden | 70 caught and shown to the reviewer |
| Unauthorised actions blocked | 100% | 54/54 |
| Decisions audited (who, when, what, why, version, evidence) | 100% | 162/162 |
| Median time from submission to recommendation; cost | < 10 s; < $0.01 | 5.6 s; $0.00058 |

The deterministic part meets its criteria with or without a model. The first prompt suggested approval for only 13 of 61 requests without any finding; prompt v4 and a check that flags statements contradicting a passed rule bring the suggestions in line with the labels for 90.1% of held-out requests (54 of 60 clean requests suggested for approval). Citations stay below target, and the screen misses injection phrasings outside its patterns; nothing the model suggests changes a finding or a route.

## The review workflow

```
awaiting_review    category buyer (reviewer)   approve  -> approved, or awaiting_approver when routed to the approver
                                               escalate -> awaiting_approver
                                               request_info -> info_requested
                                               reject   -> rejected
awaiting_approver  Head of Procurement         approve -> approved | request_info | reject
info_requested     the requester               completes the request -> new version, checked again -> awaiting_review
```

Any other transition is refused with HTTP 409, a wrong role with 403. The AI analysis may recommend an action; only a person takes it.

## Run it

With Docker, the whole stack (API, interface, n8n, a local mailbox, PostgreSQL):

```bash
git clone https://github.com/Thierry-Daconceicao-Alvares/nexora-ai.git
cd nexora-ai
docker compose up --build
```

| Open | What |
|---|---|
| http://localhost:8501 | The interface. Choose who you are in the sidebar: Sophie (requester), Karim (category buyer), Claire (Head of Procurement) |
| http://localhost:8025 | Mailpit, the local mailbox: every email n8n sends lands here, nothing leaves the machine |
| http://localhost:5678 | n8n and its four workflows (it asks to create a local account the first time) |
| http://localhost:8000/docs | The API |

To send a request by email, see [n8n/README.md](n8n/README.md). To use a real model instead of the scripted stand-in, put `MISTRAL_API_KEY=...` (or `GEMINI_API_KEY=...`) in a `.env` file before starting. To fill the database with a realistic set of requests and decisions: `docker compose exec api python scripts/seed_demo.py --database "$NEXORA_DATABASE_URL"`.

Without Docker (Python 3.12, SQLite), the interface alone, with the API running inside it:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev]"
python scripts/seed_demo.py --database sqlite:///nexora.db   # optional demo data
streamlit run app/streamlit_app.py
```

Demo tokens (not secrets, listed in [`config/demo_users.yaml`](config/demo_users.yaml)): `demo-sophie` and `demo-marc` (requesters), `demo-karim` (reviewer), `demo-claire` (approver), `demo-intake` (n8n), `demo-admin`.

| Queue | Dashboard |
|---|---|
| ![Queue](docs/images/queue.png) | ![Dashboard](docs/images/dashboard.png) |

## Tests

```bash
pytest          # 177 tests: validation, rules, screening, retrieval, verification, injection,
                # review workflow and permissions, concurrency, migrations, feeds, CSV, API,
                # and the scripted evaluation on the labelled set
pip install -e ".[ui,e2e]" && playwright install chromium
pytest -m ui tests/ui   # 5 browser tests: submit, ask, complete, approve; every page
ruff check .
```

CI also starts the whole Docker Compose stack and runs [`scripts/e2e_n8n.py`](scripts/e2e_n8n.py): real emails to the purchasing mailbox, then the answers, the stored request, the notifications and the digest are checked.

## Known limits

- Retrieval is lexical (BM25) plus the sections the rules cite. On 36 short sections this finds the right passages in the tests; semantic search is not implemented.
- The screen is a list of patterns. A reworded attack can pass it; it then reaches a model that has no tools and whose answer is verified, and it cannot change the route.
- The figure check accepts any count up to 10 and does not check that a figure is used in the right place.
- Code checks that a cited passage was given to the model, not that it is the most relevant one (see the live check).
- The model call runs inside the submission request (a few seconds with a real model). A queue would be needed at volume.
- Users and roles are demo bearer tokens from a file; single sign-on and a real identity provider are out of scope.
- Attachments are recorded by type and file name; their content is not read (OCR is out of scope).
- The email intake expects one `Label: value` line per field; free-text emails are sent back with the template.
- There is one category buyer and one approver; assigning requests by category or plant, and delegation during absence (NX-PUR-002 §6), are not implemented.

## Roadmap

| Phase | Content | Status |
|---|---|---|
| 1. Product definition | Users, scope, acceptance criteria, risks | Done |
| 2. Architecture | Components, states, data model, API, security boundaries | Done |
| 3. Vertical slice | Intake, validation, rules, storage, routing, audit, tests | Done |
| 4. AI and retrieval | Structured analysis with cited policies, insufficient-evidence handling, injection tests | Done |
| 5. Approvals and audit | Review decisions, server-side authorisation, migrations | Done |
| 6. Interface and n8n | Dashboard, review screens, email intake, notifications, reminders | Done |
| 7. Evaluation | Labelled scenarios, baselines, latency and cost | **Done** |
| 8. Deployment | Public demo, setup from a clean clone | Next |
| 9. Launch | Screenshots, video | Planned |

## License

[MIT](LICENSE). Author: [Thierry Daconceição Alvares](https://www.linkedin.com/in/thierry-alvares/).
