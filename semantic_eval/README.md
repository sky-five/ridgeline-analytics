# Semantic eval: raw tables vs governed metrics

Does an AI analyst answer business questions more reliably when it can only use governed metrics than when it writes SQL on raw tables? This folder holds the test set for that comparison.

## The question set

`questions.yml` has 25 questions across revenue, retention, funnel, acquisition, contractor outcomes and operations. They are worded the way a stakeholder asks them ("What's our trial-to-paid conversion rate?"), without the definition spelled out, so picking the right definition is part of the task. That is the gap left by the first analyst eval in `analyst/evals/`, where every question stated its definition.

Each question carries:

| Field | Meaning |
|---|---|
| `metric`, `group_by`, `where` | The MetricFlow query that holds the answer |
| `pick`, `answer`, `by` | How to reduce the result to one answer: a value, or the dimension value with the highest / lowest metric |
| `type` | `number`, `ratio` or `text`, scored like the first eval (0.5% / half a point / exact) |
| `period_end` | Last day the answer depends on. Closed periods must give the same answer on every nightly build |
| `trap` | What a query on the raw tables tends to get wrong, e.g. summing daily MRR, counting immature signups, dividing by open leads |

The traps are hypotheses. The next step runs the analyst twice per question (raw-table SQL only, then governed metrics only) and checks which traps it falls into.

## The answer key

```bash
.venv/Scripts/python -m semantic_eval.answer_key            # compute from the semantic layer, write answer_key.json
.venv/Scripts/python -m semantic_eval.answer_key --check    # compare a fresh build with the committed key
```

Every answer comes from `semantic.query`, the same MetricFlow call the dashboards and the analyst use. No hand-written SQL. The committed `answer_key.json` is from data as of 2026-10-29.

## Tests

- **Without a warehouse:** the set has 25 valid questions covering all six areas; the validator rejects unknown fields, bad types and picks on columns the query does not return; the reduce step is unit-tested on fixed rows; the committed key answers every question with the right type.
- **With a built warehouse** (`-m warehouse`, run in CI after the nightly-style build): every question's metric and dimensions exist in the semantic manifest; answers about periods that ended at least 30 days before the data's last day (16 of 25 today) match the committed key; four answers are checked again with plain SQL on the marts.
