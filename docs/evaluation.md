# How NEXORA AI is evaluated

The product specification sets ten acceptance criteria. They are measured on a
labelled set of synthetic requests, by running every request through the whole
application, exactly as a client would, and comparing what comes out with the
labels.

## The labelled set

[`data/evaluation/requests.jsonl`](../data/evaluation/requests.jsonl): 156
requests in 30 scenarios, built by
[`scripts/build_eval_set.py`](../scripts/build_eval_set.py) with a fixed seed.

| Family | Requests | What is labelled |
|---|---|---|
| Clean requests below €5,000, from €5,000, from €50,000, single source, CapEx complete | 37 | No finding; route by amount; approve |
| Missing quotes, missing bid comparison | 16 | Sourcing finding (medium, or high from €50,000) |
| Blocked, pending, unknown supplier; supplier not listed for the category | 24 | Supplier finding (critical, medium, high, low) |
| Unit price 15 to 30% and 30% or more above the catalogue | 12 | Price finding (medium, high) |
| CapEx without approval | 6 | CapEx finding (high) |
| A request repeated within 30 days; a need split into three requests | 22 | Duplicate on the second, split purchase on the request that crosses €5,000 |
| Text addressed to an AI system: 8 phrasings the screen knows, 4 it was never tuned on | 12 | Instruction-like text (high); never approve |
| Thresholds: exactly €5,000 and €50,000, €4,999.99, exactly 15% and 14.9% above the catalogue, USD amounts on both sides of €5,000 | 8 | The finding on the right side of each threshold |
| Invalid input: unsupported currency, zero quantity, negative price, missing description, unknown department or category, malformed reference, past date, unknown field, short justification, unknown attachment kind, two errors at once | 12 | Rejected, with the fields to fix |
| The requester's category is wrong (oil declared as a spare part, a monthly IT service declared as hardware...) | 7 | The true spend category, from the description |

The labels are written from the Nexora policies in
[`data/knowledge_base`](../data/knowledge_base), scenario by scenario; they are
not computed by NEXORA's rules. Which policy passages support which finding is
labelled in [`acceptable_passages.yaml`](../data/evaluation/acceptable_passages.yaml).

The set is synthetic and written by the author of the system: it shows that the
system does what its specification says on known cases, and where it does not.
It does not show how it would behave on a company's real requests.

## What a run does

[`src/nexora/evaluation/runner.py`](../src/nexora/evaluation/runner.py), on a
fresh database, with a simulated clock set to each request's submission time:

1. submits every request, then the same request again with the same key;
2. attempts 54 forbidden actions (a requester approving, the approver deciding
   before the reviewer, a missing reason, an outdated version, no token...);
3. decides every accepted request as the labels say, with the approver when the
   request reaches her, and checks the audit record of each decision;
4. submits the set again to a provider that answers outside the schema twice,
   once, or times out, one request in ten each.

## Baselines

- **Spend category**: the category declared by the requester, and a keyword
  classifier on the description
  ([`baselines.py`](../src/nexora/evaluation/baselines.py)).
- **Suggested decision**: the scripted stand-in, which maps the most serious
  finding to a decision.

## Run it

```bash
python scripts/evaluate.py --provider scripted --out eval/results/my-run
MISTRAL_API_KEY=... python scripts/evaluate.py --provider mistral --pause 1 --out eval/results/my-run
```

Or on GitHub: Actions > Evaluate > Run workflow, which commits the report to
[`eval/results/`](../eval/results). The test suite runs the scripted evaluation
and requires every criterion that does not depend on a model to pass
([`tests/evaluation`](../tests/evaluation)).
