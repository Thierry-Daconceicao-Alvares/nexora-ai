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

## Results (20 October 2026)

Three runs, all published as they came out:
[scripted stand-in](../eval/results/2026-10-20-scripted/report.md),
[Mistral, prompt v2](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v2/report.md),
[Mistral, prompt v3](../eval/results/2026-10-20-mistral-ministral-14b-latest-prompt-v3/report.md).
The model is `ministral-14b-latest`, the one Mistral's free plan serves.

| Criterion | Target | Scripted stand-in | Mistral, prompt v3 |
|---|---|---|---|
| 1. Malformed requests rejected | 100% | 12/12 | 12/12 |
| 2. Rules and routing as labelled | 100% | 144/144 | 144/144 |
| 3. Processed once | 0 double records | 0 | 0 |
| 4. Valid end state, with faults | 100% | 288/288 | 288/288 |
| 5. Spend category (keyword baseline 95.1%) | above the baseline | 95.1% (it copies the declared category) | **94.4%: not met** |
| 6. Citations supporting the statement | at least 90% | 205/205 | **238/296 (80.4%): not met** |
| 7. Unsupported claims | 0 unflagged | none produced | 27 caught and shown (6 analyses unverified); other kinds not measured |
| 8. Unauthorised actions blocked | 100% | 54/54 | 54/54 |
| 9. Decisions audited | 100% | 167/167 | 167/167 |
| 10. Median time and cost | under 10 s, under $0.01 | 0.02 s, $0 | 6.0 s (p90 8.5 s), $0.00055 |

### What the runs show

- **The deterministic part does what the policies say.** Every rule, route,
  rejection, replay, refusal and audit record matches the labels, with or
  without a model, and the application stays in a valid state when the model
  answers outside the schema or not at all.
- **The model does not decide anything, and that matters.** On the 61 requests
  with no finding, the model suggested approval for 13 only: it asked for
  documents the policies do not require of these purchases (supplier
  certifications meant for direct material suppliers, a catalogue code), and in
  5 cases it stated that three quotes were missing for amounts below €5,000,
  contradicting the rule result it was given. The suggested decision matches
  the labels for 65.3% of the requests, against 93.8% for the scripted
  stand-in, which maps the most serious finding to a decision. The route and
  the findings never depend on the model.
- **Prompt v2 to v3.** v2 did not give the model today's date; it judged the
  simulated dates of the set against its own and called 20 delivery dates
  unrealistic. v3 gives the date: 0 such remarks, but the agreement did not
  improve (68.1% then 65.3%): the dates were not the main cause.
- **Spend category.** The model recognises more mislabelled requests than the
  keyword baseline (6 of 7 against 5 of 7; the declared category gets none), but
  makes errors on correctly declared ones (an automated storage tower filed as
  automation), so its overall accuracy (94.4%) stays just below the baseline
  (95.1%).
- **Citations.** 80.4% of the citations are labelled as supporting. The others
  cite a retrieved passage that does not govern the finding, most often the
  "No PO, no pay" section for a supplier finding. The check in code guarantees
  that a citation was given to the model, not that it is the right one.
- **Screen.** The four injection phrasings the screen was not tuned on were
  not flagged; the model treated them as data, never suggested approval, and the
  routes stayed those of the rules.
- **Labels.** The citation labels were revised once, after the first run, to
  let a recommendation cite the policy of a rule it complies with; the reason
  and the effect (208/281 then 231/281 on that run) are written in
  [`acceptable_passages.yaml`](../data/evaluation/acceptable_passages.yaml).

### What would come next

A prompt that forbids requirements absent from the passages and the rule
results, and a check in code that flags a recommendation contradicting a passed
rule, measured on a **new** labelled set: this set has now been read, and a
prompt tuned on it would be judged on the cases it was tuned for. A larger
model than the free plan allows is the other lever.
