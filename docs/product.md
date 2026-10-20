# Product definition

What NEXORA AI is for, who uses it, what it must achieve and what it leaves
out. Every figure quoted as a result comes from the
[evaluation](evaluation.md); the company, the people and the requests are
fictional.

## The problem

At Nexora Industries, a purchase request goes to procurement by form or email
and someone checks it by hand. Most of these checks are mechanical:

- a field is missing or wrong;
- the supplier is blocked, pending or not listed for the category;
- there are not enough quotes for the amount (NX-PUR-001 §5);
- the unit price is far above the catalogue price;
- the amount needs a higher approval level (NX-PUR-002 §2);
- the same need was already requested, or was split to stay under a threshold.

They take the buyers' time, they are not applied the same way by everyone, and
the reason a request was approved is rarely written down.

## The answer

NEXORA AI runs the mechanical checks in code, against rules written from the
purchasing policies. A language model then explains the findings in plain
language, citing the policy passages it was given, and its answer is checked
in code. A person decides, with a written reason, and every step is recorded.

**The model explains; it never decides.** It cannot change a finding, a route
or a status, and the request is checked and routed even when the model is
down.

## Users

| User | In the demo | What they do |
|---|---|---|
| Requester | Sophie Martin, Marc Leroy | Submits requests (form, CSV file, email), sees only their own, completes a request when procurement asks for information |
| Category buyer (reviewer) | Karim Benali | Reviews the requests below €50,000: approves, rejects, asks for information or sends to the Head of Procurement |
| Head of Procurement (approver) | Claire Dubois | Decides on the requests from €50,000, those with a high or critical finding, and those sent to her |
| Intake service | n8n | Submits the requests received by email on behalf of a known requester; reads the notification feeds |
| Administrator | Demo administrator | Reads everything, decides nothing |

## Scope

In scope: intake by form, CSV file, API and email; validation; seven business
rules; screening of text addressed to an AI system; retrieval of policy
passages; one structured model call with verification in code; routing by
amount and severity; review decisions with a mandatory reason; completion of a
request after a question (new version, every check again); audit trail;
notifications, reminders and a weekly digest by email; a dashboard; an
evaluation on labelled requests.

Out of scope: purchase orders and the link with an ERP, payment, supplier
onboarding, reading the content of attachments (OCR), single sign-on, assignment
of requests by category or plant, delegation during absence. The
[known limits](../README.md#known-limits) list what this leaves open.

## Acceptance criteria

Measured on labelled synthetic requests by running them through the whole
application ([method](evaluation.md)).

| # | Criterion | Target |
|---|---|---|
| 1 | Malformed requests rejected, with every field to fix | 100% |
| 2 | Rules and routing as labelled | 100% |
| 3 | A repeated submission is processed once | 0 double records |
| 4 | Valid end state when the model answers outside the schema or times out | 100% |
| 5 | Spend category suggested by the model, against a keyword baseline | above the baseline |
| 6 | Citations that support the statement | ≥ 90% |
| 7 | Unsupported figures, quotations, citations, explanations and contradictions | shown to the reviewer, never hidden |
| 8 | Unauthorised actions blocked | 100% |
| 9 | Decisions audited: who, when, what, why, on which version, with which evidence | 100% |
| 10 | Median time from submission to recommendation; cost per request | < 10 s; < $0.01 |

On the held-out set, criteria 1 to 5 and 7 to 10 are met; criterion 6 is not
(82.5%). The [README](../README.md#evaluation) has the figures.

## Risks and how they are handled

| Risk | Handling |
|---|---|
| The model invents a rule, a figure, a quotation or a source | It may only cite the passages it was given; citations, figures, quotations and explanations are checked in code; what fails is removed or shown to the reviewer |
| Text in a request tries to instruct the model ("approve this request") | The request is marked as untrusted data in the prompt; a screen flags such text as a high finding, which sends the request to the Head of Procurement; the model has no tools and cannot change the route |
| The model suggests approving despite a serious finding | The suggestion is replaced by an escalation and marked unverified |
| The model is down, slow or answers outside the schema | One retry, then the analysis is recorded as unavailable; the request is still checked and routed |
| A person decides outside their role, twice, or on an outdated version | Checked by the API on every decision: role, state, version (compare-and-set) |
| No record of why a request was approved | A reason of at least 10 characters is required; each decision is stored with the evidence the person had |
| The labelled set only reflects its author's cases | A held-out set committed before any tuning; the limits are written in the evaluation |
| Real or personal data | Synthetic data only; no request text, prompt, token or secret in the audit trail |
