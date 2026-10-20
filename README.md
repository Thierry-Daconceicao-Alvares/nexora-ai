# NEXORA AI

**AI-assisted review of purchase requests: deterministic checks, cited explanations, human decisions and a full audit trail.**

> **Status: work in progress (Phase 4 of 9).** Requests are submitted, validated, checked against the purchasing rules, screened, analysed by a language model with cited policies, verified in code, stored and routed. The review decisions, the interface and n8n arrive in the next phases. Nothing below describes a feature that is not implemented and tested.

NEXORA AI is an engineering project built around a real business problem: procurement teams spend their time on checks a machine can do (missing fields, duplicates, prices far from the usual, amounts above an approval threshold, unknown suppliers, missing quotes) and rarely write down why a request was approved. It runs on synthetic data for **Nexora Industries, a fictional industrial company**; the purchasing policies it applies are the synthetic documents of [Enterprise AI Knowledge Assistant](https://github.com/Thierry-Daconceicao-Alvares/enterprise-ai-knowledge-assistant). It is not used by a real company, and every figure it reports comes from its test environment.

## What works today

| Step | What happens | Where |
|---|---|---|
| Intake | `POST /requests` with a demo bearer token; an idempotency key stores a resubmitted request once | [`services/intake.py`](src/nexora/services/intake.py) |
| Validation | Every problem reported at once: required fields, formats, quantities, prices, currencies, department, category, delivery date | [`services/validation.py`](src/nexora/services/validation.py) |
| Business rules | Seven rules, each naming the policy it applies: approval band, supplier status, sourcing evidence, CapEx approval, price deviation, duplicate request, split purchase | [`services/rules.py`](src/nexora/services/rules.py), [`config/rules.yaml`](config/rules.yaml) |
| Screening | Text addressed to an AI system in the description, justification or attachment names ("ignore the previous instructions", "you must approve") is flagged as a high finding | [`services/screening.py`](src/nexora/services/screening.py) |
| Retrieval | The policy sections cited by the flagged rules, plus the best lexical (BM25) matches among the 36 sections of the Nexora policies | [`services/retrieval.py`](src/nexora/services/retrieval.py) |
| AI analysis | One model call: summary, explanation of each finding with citations, missing information, draft recommendation; then verified in code (see below) | [`services/analysis.py`](src/nexora/services/analysis.py) |
| Routing | A category buyer (reviewer) below €50,000; the Head of Procurement (approver) from €50,000 or when a rule or the screen raises a high or critical finding. The AI analysis never changes the route | [`services/rules.py`](src/nexora/services/rules.py) |
| Audit trail | Every step appended to an event log, which n8n will read; no token, secret, prompt or request text is ever stored in it | [`services/audit.py`](src/nexora/services/audit.py) |
| Permissions | Checked in the services: only requesters and the intake service submit; requesters see only their own requests | [`services/authorization.py`](src/nexora/services/authorization.py) |

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
| The recommendation does not approve against a high or critical finding | Replaced by `escalate`, marked `unverified` |
| The recommendation rests on at least one valid citation | Replaced by `request_info` (insufficient evidence) |

The reviewer sees the verification status, the list of issues and the cited passages in full. The prompt is not stored, only its version (`analysis-v1`); the model, tokens, latency and estimated cost of each call are.

**Providers.** With a `GEMINI_API_KEY`, Gemini (`gemini-3.5-flash-lite` by default) does the analysis. Without one, a **scripted stand-in** fills the same JSON from the rule results with templates, so the whole pipeline runs with no account and no network; it is not a language model, and its analyses are labelled `provider: scripted`. The tests use the scripted provider and fake models (an obedient model that follows an injection, a model that is down, answers outside the schema). The Gemini provider is tested against a stub client; the [live check workflow](.github/workflows/live-check.yml) runs six scenario requests against the real API.

## Run it

With Docker (API and PostgreSQL):

```bash
git clone https://github.com/Thierry-Daconceicao-Alvares/nexora-ai.git
cd nexora-ai
docker compose up --build
```

Then open http://localhost:8000/docs, click **Authorize**, enter `demo-sophie` (a requester), and try `POST /requests`: the answer includes the rule results and the `analysis`. To use Gemini instead of the scripted stand-in, put `GEMINI_API_KEY=...` in a `.env` file before starting.

Without Docker (Python 3.12, SQLite):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn nexora.api.main:app --reload
```

Demo tokens (not secrets, listed in [`config/demo_users.yaml`](config/demo_users.yaml)): `demo-sophie` and `demo-marc` (requesters), `demo-karim` (reviewer), `demo-claire` (approver), `demo-intake` (n8n), `demo-admin`.

## Tests

```bash
pytest          # 111 tests: validation, rules, screening, retrieval, verification, injection, API
ruff check .
```

## Known limits

- Retrieval is lexical (BM25) plus the sections the rules cite. On 36 short sections this finds the right passages in the tests; semantic search is not implemented.
- The screen is a list of patterns. A reworded attack can pass it; it then reaches a model that has no tools and whose answer is verified, and it cannot change the route.
- The figure check accepts any count up to 10 and does not check that a figure is used in the right place.
- The model call runs inside the submission request (a few seconds with Gemini). A queue would be needed at volume.

## Roadmap

| Phase | Content | Status |
|---|---|---|
| 1. Product definition | Users, scope, acceptance criteria, risks | Done |
| 2. Architecture | Components, states, data model, API, security boundaries | Done |
| 3. Vertical slice | Intake, validation, rules, storage, routing, audit, tests | Done |
| 4. AI and retrieval | Structured analysis with cited policies, insufficient-evidence handling, injection tests | **Done** |
| 5. Approvals and audit | Review decisions, server-side authorisation, migrations | Next |
| 6. Interface and n8n | Dashboard, review screens, email intake, notifications, reminders | Planned |
| 7. Evaluation | Labelled scenarios, baselines, latency and cost | Planned |
| 8. Deployment | Public demo, setup from a clean clone | Planned |
| 9. Launch | Screenshots, video | Planned |

## License

[MIT](LICENSE). Author: [Thierry Daconceição Alvares](https://www.linkedin.com/in/thierry-alvares/).
