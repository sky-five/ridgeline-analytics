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

The traps were hypotheses before the run below; the raw-table failures show which ones happen.

## The answer key

```bash
.venv/Scripts/python -m semantic_eval.answer_key            # compute from the semantic layer, write answer_key.json
.venv/Scripts/python -m semantic_eval.answer_key --check    # compare a fresh build with the committed key
```

Every answer comes from `semantic.query`, the same MetricFlow call the dashboards and the analyst use. No hand-written SQL. The committed `answer_key.json` is from data as of 2026-10-29.

## Tests

- **Without a warehouse:** the set has 25 valid questions covering all six areas; the validator rejects unknown fields, bad types and picks on columns the query does not return; the reduce step is unit-tested on fixed rows; the committed key answers every question with the right type.
- **With a built warehouse** (`-m warehouse`, run in CI after the nightly-style build): every question's metric and dimensions exist in the semantic manifest; answers about periods that ended at least 30 days before the data's last day (16 of 25 today) match the committed key; four answers are checked again with plain SQL on the marts.

## Raw tables vs governed metrics: the run

The analyst answers every question twice, each time with one set of tools and nothing else (`arms.py`):

| Arm | Tools | What it sees |
|---|---|---|
| raw | `list_raw_tables`, `run_raw_sql` | The 11 tables as the loaders landed them (accounts, subscriptions, invoices, events, leads, tickets, ad spend ...), copied into a separate DuckDB file so no mart, view or metric table can be reached, even through `query()` or catalog functions |
| governed | `list_governed_metrics`, `query_governed_metric` | The 27 MetricFlow metrics and their dimensions. No SQL |

Each arm is its own MCP server (`server.py`); Claude Code runs headless with only that server's tools. Truth is the answer key's governed query on the same warehouse.

**Recorded run (2026-11-03, data as of 2026-11-02, Claude Code headless, default model):**

| | Raw tables | Governed metrics |
|---|---|---|
| Correct | 17 / 25 | 25 / 25 |
| Revenue | 7 / 7 | 7 / 7 |
| Funnel | 4 / 7 | 7 / 7 |
| Contractor outcomes | 2 / 4 | 4 / 4 |
| Acquisition | 2 / 3 | 3 / 3 |
| Retention | 1 / 2 | 2 / 2 |
| Operations | 1 / 2 | 2 / 2 |
| Median tool calls / seconds | 4 / 11.8 s | 2 / 11.0 s |
| Cost at API rates, 25 questions | $0.82 | $0.66 |

Revenue questions came out right on raw tables too: MRR lives in one column of the subscription change log, and the agent rebuilt balances and movements correctly. The misses are all definition questions, where the raw tables don't say what the business means:

| Question | Raw answer | Governed answer | What the raw arm did |
|---|---|---|---|
| Trial-to-paid conversion | 18.5% | 15.7% | Any subscription ever, signups older than 90 days (governed: paid within 60 days) |
| Share of 2025 signups activated | 58.3% | 31.3% | Invented a definition (a measurement order within 14 days); governed activation is a proposal sent within 14 days |
| Activated accounts that became paying | 20.6% | 38.9% | Guessed both "activated" and "paying" |
| Lead close rate | 37.8% | 22.9% | Also dropped unqualified leads from the denominator |
| 2025 CAC | $783 | $883 | Counted conversions by subscription start, not signup date |
| Net revenue retention | 56% | 61.7% | Its own 12-month window and base |

In several misses the raw arm said the data has no definition and it had to pick one, then still returned a single number. Two of its eight misses (fastest lead-response bucket, top 2025 ticket theme) named the right thing in its own words rather than the governed label (`lt_5m`, `measurement_accuracy`); they are scored wrong because the raw tables have no such labels and the scorer only accepts the label. Counting those, raw tables get 19 / 25 on substance.

One run per arm and question, one model, 25 questions: a demonstration, not a benchmark. Scoring was tightened once after the run (month names and a label followed by a count now match), and the committed file was rescored with `--replay`; that moved the governed arm from 23 to 25 and the raw arm not at all.

```bash
python -m semantic_eval.run                         # both arms, needs a built warehouse and a logged-in Claude Code
python -m semantic_eval.run --replay semantic_eval/results/raw-vs-governed-2026-11-03.json   # no warehouse, no key
```

Tests: the raw arm can't reach marts, staging, dlt tables or `query()`; scoring and the summary are unit-tested; the committed run replays to the same scores; both MCP servers start and answer (warehouse tests); the eval's read-only truth equals the answer key.

