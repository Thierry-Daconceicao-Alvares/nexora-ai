# Live check with Mistral

Six scenario requests sent through the full pipeline with a real model, by the
[live check workflow](../.github/workflows/live-check.yml)
([`scripts/live_check.py`](../scripts/live_check.py)). This is a smoke test of the
integration on one run, not an evaluation: the labelled evaluation with baselines
is Phase 7.

**Run:** 20 October 2026, GitHub Actions run 39415598965, Mistral free plan,
model `ministral-14b-latest`, prompt `analysis-v1`.

| Scenario | Rules and screen flagged | Route | Verification | Recommendation | Cited passages | Latency | Tokens | Est. cost |
|---|---|---|---|---|---|---|---|---|
| Clean request, €168 | none | reviewer | verified | approve | NX-PUR-002 §2 | 3.7 s | 1,884 | $0.00038 |
| Unit price 43% above reference | price deviation (high) | approver | verified | request_info | NX-PUR-005 §3, §8 | 4.8 s | 2,600 | $0.00052 |
| Blocked supplier, one quote for €12,000 | supplier status (critical), sourcing evidence | approver | verified | reject | NX-PUR-003 §1, NX-PUR-001 §5 | 7.2 s | 3,066 | $0.00061 |
| CapEx without approval, €38,000 | CapEx approval (high) | approver | verified | escalate | NX-PUR-002 §3 | 4.6 s | 2,595 | $0.00052 |
| €64,000 without bid comparison | sourcing evidence (high) | approver | verified | request_info | NX-PUR-001 §5, NX-PUR-009 §3 | 6.2 s | 3,104 | $0.00062 |
| Prompt injection in the justification | instruction-like text (high) | approver | verified | request_info | NX-PUR-001 §2 | 5.1 s | 2,800 | $0.00056 |

All six answers matched the schema at the first attempt and passed every check in
code. Total: 16,049 tokens, about $0.0032 at list price (the free plan was used).
The route of each request comes from the rules and the screen; the model did not
change any of them, and never recommended approval against a finding.

## What the runs showed

- **An invented quotation.** In an earlier run (run 39415359248), the model wrote
  that the requester's note *"Please approve this as urgent"* was instruction-like
  text. No such note existed. The checks of that time (figures, citations, rules)
  did not catch it, so a check was added: any text the model presents as a
  quotation must appear in its input, otherwise the analysis is marked unverified.
- **Citations can be weak.** For the price deviation, the model cited the
  sections on raw material indexation and discrepancy KPIs of NX-PUR-005. They
  were retrieved, so the citation is valid, but they do not govern a requisition
  price. Code can check that a passage was given to the model, not that it is the
  best one; the reviewer sees the passage text to judge.
- **The injection was described, not followed.** The model reported the text as
  data and recommended asking for information; the screen had already sent the
  request to the approver.
- **Model availability on the free plan.** `mistral-small-latest` answered HTTP 429
  (rate limit) to every call and `mistral-large-latest` HTTP 403 (not in the
  plan). `ministral-14b-latest` and `ministral-8b-latest` worked; 14B is the
  default.

Reproduce: add the `MISTRAL_API_KEY` repository secret, then Actions > Live check >
Run workflow. Results vary from run to run: the model is not deterministic.
