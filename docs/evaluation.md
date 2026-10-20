# How NEXORA AI is evaluated

The [product definition](product.md) sets ten acceptance criteria. They are measured on a
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

## Results (20 October 2026)

Every run is published as it came out, in [`eval/results/`](../eval/results).
The model is `ministral-14b-latest`, the one Mistral's free plan serves.

| Run | Set | Spend category (keyword baseline) | Citations supporting | Suggested decision acceptable | Requests without finding suggested for approval |
|---|---|---|---|---|---|
| [Scripted stand-in](../eval/results/2026-10-20-scripted/report.md) | development | 95.1% (95.1%) | 205/205 | 93.8% | 61/61 |
| [Mistral, prompt v2](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v2/report.md) | development | 94.4% (95.1%) | 208/281 (labels v1) | 68.1% | 16/61 |
| [Mistral, prompt v3](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v3/report.md) | development | 94.4% (95.1%) | 238/296 (80.4%) | 65.3% | 13/61 |
| [Mistral, prompt v4](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v4/report.md) | development | 96.5% (95.1%) | 238/280 (85.0%) | 86.8% | 51/61 |
| [Mistral, prompt v4](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v4-holdout/report.md) | **held-out** | **97.2% (88.7%)** | **217/263 (82.5%)** | **90.1%** | **54/60** |
| [Scripted stand-in](../eval/results/2026-10-20-scripted-holdout/report.md) | held-out | 95.7% (88.7%) | 202/202 | 93.6% | 60/60 |

On every run, criteria 1 to 4, 8, 9 and 10 pass: malformed requests rejected
(12/12), rules and routing as labelled (144/144 and 141/141), no double record,
a valid end state with injected faults (100%), 54/54 forbidden actions refused,
every decision audited, a median of 4.5 to 6.0 s and about $0.0006 per request.

The held-out run is the figure to quote: prompt v4 was frozen before it, and the
held-out set was committed before any tuning.

### What the runs show

- **The deterministic part does what the policies say**, with or without a
  model, and the application stays in a valid state when the model answers
  outside the schema or not at all.
- **Prompt v2 to v3**: v2 did not give the model today's date; it called 20
  simulated delivery dates unrealistic. v3 gives the date (0 such remarks), but
  the model still suggested approval for only 13 of the 61 requests without any
  finding: it asked for documents no passage requires of these purchases and,
  in 5 cases, said three quotes were missing below €5,000.
- **Prompt v4** (tuned on the development set) states that a passed rule is
  met, forbids requirements absent from the rule results and the passages, and
  asks to keep the declared category unless the description clearly says
  otherwise. A new check in code marks an analysis unverified when it says that
  quotes, sourcing evidence, a CapEx approval or the supplier status is missing
  while that rule passed (9 analyses on the development set, 4 on the held-out
  set). On the held-out set: 54 of the 60 clean requests suggested for approval,
  90.1% of suggestions acceptable, spend category above the keyword baseline.
- **What v4 gave up**: keeping the declared category means fewer mislabelled
  requests are caught (2 of 6 on the held-out set, against 6 of 7 for v3 on the
  development set). The keyword baseline drops from 95.1% to 88.7% on the
  held-out set because its keywords were written for the development items: the
  held-out set does what it is for.
- **Still not met: citations (82.5%, target 90%).** The model cites retrieved
  passages that do not govern the finding, most often the "No PO, no pay"
  section for a supplier finding. They are shown with their full text; the
  check in code only guarantees that the passage was given to the model.
- **Remaining wrong suggestions**: for a blocked supplier, the model suggests
  escalating rather than rejecting (8 of 8); with a single-source justification,
  it still asks for three quotes (4 of 4), which the new check now marks as
  contradicting the rule.
- **Screen**: the phrasings outside its patterns are not flagged (4 of 4 on both
  sets). On the development set, the model suggested approving one of them
  (E127); on the held-out set, none. The route never depends on the model.
- **Labels**: the citation labels were revised once, after the first run, to
  let a recommendation cite the policy of a rule it complies with; the reason
  and the effect are written in
  [`acceptable_passages.yaml`](../data/evaluation/acceptable_passages.yaml).

### What would come next

Restricting each finding's citations to its rule's policy in code would reach
the citation target by construction, at the cost of the model's ability to add
a relevant passage; it would need its own justification, not the score. A
larger model than the free plan allows is the other lever.

## The held-out set

[`data/evaluation/holdout.jsonl`](../data/evaluation/holdout.jsonl): 153
requests with the same scenarios and labels as the development set but other
items, justifications, injection phrasings and mislabelled requests
([vocabulary](../scripts/eval_holdout_vocabulary.py)). It was generated and
committed before any change made to the prompt after the first runs, and is
only used to measure a version once it is frozen.
