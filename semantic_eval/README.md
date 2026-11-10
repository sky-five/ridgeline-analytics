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

**Recorded run (2026-11-03, data as of 2026-11-02, Claude Code headless, model claude-sonnet-5-5 via Anthropic; other models will score differently):**

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


## Other model providers

The recorded run above used Claude Code. The same eval also runs through a provider-agnostic API agent (`analyst/llm.py`), so it can be repeated on another model without changing the arms, prompts or scoring:

| Provider | Client | Key |
|---|---|---|
| `anthropic` | `AnthropicClient`, the Messages API | `ANTHROPIC_API_KEY` |
| `gemini` | `ChatClient` on the Gemini API's OpenAI-compatible endpoint, standard library only | `GEMINI_API_KEY` (a free-tier key from Google AI Studio) |

```bash
python -m semantic_eval.run --backend api --provider gemini --limit 20 --pace 6
```

Each arm keeps its two tools and its system prompt, and the caps are the analyst's (12 model calls, 300k tokens per answer). Answers go into `results/raw-vs-governed-<provider>-<model>-<date>.json` one at a time; running the command again resumes the file and asks only what is missing or ended in an error, so a free daily quota can be spread over several runs. `--limit` caps new answers per run, `--pace` spaces requests (6 s is 10 a minute), and rate-limit or server errors are retried with backoff. Each record keeps the provider, model, turns, tool calls and token counts.

On the Gemini API free tier (checked 2026-11-04), a new key can no longer use `gemini-2.5-*` and `gemini-3.5-flash` allows 20 requests a day, while one answer takes several requests, so the Gemini default is `gemini-3.5-flash-lite`. Gemini 3 models return a `thought_signature` with each tool call and reject the next turn unless it is sent back; `ChatClient` passes it through, and recordings leave it out since replay never calls the API.

### Recording in GitHub Actions

`.github/workflows/record-eval.yml` is a manual (`workflow_dispatch`) job that builds DuckDB for a fixed as-of date, records both arms through Gemini and commits the answers to `results/raw-vs-governed-gemini-<model>-as-of-<date>.json`. The default as-of date is 2026-11-02, the same simulated day as the Claude Code run above, so the two are scored against the same answer key. Running it again with the same inputs resumes that file. It needs the repository secret `GEMINI_API_KEY` and stops at the first step without it; the key is passed only to the recording step.

| Input | Default | Meaning |
|---|---|---|
| `model` | `gemini-3.5-flash-lite` | Gemini model id |
| `as_of` | `2026-11-02` | warehouse date; keep it fixed while resuming |
| `limit` | `50` | most new answers per run (50 is both arms, all questions) |
| `pace` | `6` | seconds between model requests |

### The same eval on Gemini

Recorded 2026-11-10 by `record-eval.yml` (workflow run 42725303765) through the Gemini API free tier, model `gemini-3.5-flash-lite`, data as of 2026-11-02: the same warehouse day, questions, tools, prompts and answer key as the Claude Code run. One run per arm and question; other models score differently.

| | Claude Code, claude-sonnet-5-5 (Anthropic) | | gemini-3.5-flash-lite (Gemini API) | |
|---|---|---|---|---|
| | Raw tables | Governed metrics | Raw tables | Governed metrics |
| Correct | 17 / 25 | 25 / 25 | 12 / 25 | 24 / 25 |
| Revenue | 7 / 7 | 7 / 7 | 4 / 7 | 7 / 7 |
| Funnel | 4 / 7 | 7 / 7 | 4 / 7 | 7 / 7 |
| Contractor outcomes | 2 / 4 | 4 / 4 | 3 / 4 | 4 / 4 |
| Acquisition | 2 / 3 | 3 / 3 | 1 / 3 | 3 / 3 |
| Retention | 1 / 2 | 2 / 2 | 0 / 2 | 1 / 2 |
| Operations | 1 / 2 | 2 / 2 | 0 / 2 | 2 / 2 |
| Median tool calls / seconds | 4 / 11.8 s | 2 / 11.0 s | 7 / 43.3 s | 3 / 24.3 s |

This model widens the gap: governed metrics lose one answer, raw tables lose five more. Its raw misses go beyond definitions into plain SQL mistakes: MRR at the end of September ($231,695 against $243,419), paying accounts at the end of 2025 (340 against 552) and the 2025 redo rate (it returned the count of redone orders, 3,762, not the rate). Three raw answers (activation rate, trial-to-paid, CAC by channel) hit the 12-call cap without answering and are scored wrong. The one governed miss is net revenue retention, where it picked a single November 2025 cohort (70.7%) instead of all cohorts (61.7%). No question was right on raw tables and wrong on governed metrics. On substance, two raw misses are right but miss the scorer's form: "June" for the best 2026 month (the scorer wants the year) and "0-5 minutes" for `lt_5m`, so raw tables get 14 / 25 counted that way.

```bash
python -m semantic_eval.run --replay semantic_eval/results/raw-vs-governed-gemini-gemini-3.5-flash-lite-as-of-2026-11-02.json
```

This run is DuckDB only; the governed side on Snowflake (below) is the Claude Code run's.

**Gemini on Snowflake: not recorded.** `.github/workflows/record-eval-snowflake.yml` asks the governed questions through Gemini on a Snowflake build and then on a DuckDB build of the same day, and pairs the answers (`python -m semantic_eval.cross_target runs sf.json duckdb.json`). With `RIDGELINE_DBT_TARGET=snowflake` the governed tool runs MetricFlow's compiled query on Snowflake after a one-SELECT check (`sql_guard.check_snowflake_sql`, sqlglot's Snowflake dialect). Its first run on 2026-11-10 never reached the model: the Snowflake trial account had been suspended that day. The code and its tests (`tests/semantic_eval/test_governed_on_snowflake.py`, fakes only) stay for an account that has Snowflake.

Tests (`tests/analyst/test_llm.py`, `tests/semantic_eval/test_eval_api_backend.py`, `tests/semantic_eval/test_record_workflow.py`) use a fake SDK and a fake HTTP transport, so nothing calls a model: tool specs, tool results passed back by id, the `thought_signature` round trip, caps, retries and pacing, resume after a limit or a provider failure, and that the workflow keeps its as-of date and results file fixed and the key out of every step but recording. Every committed results file, complete or partial, must replay to the scores it stored.

## The governed side on Snowflake

The same dbt project also builds on Snowflake (`.github/workflows/snowflake.yml`). That workflow now asks the 25 questions through MetricFlow on both warehouses and checks the answers match (`cross_target.py`):

1. Right after the Snowflake dbt build, while the semantic manifest points at Snowflake tables, it answers every question with `RIDGELINE_DBT_TARGET=snowflake`.
2. It builds DuckDB from the same simulated day and answers them again there.
3. It compares the pairs: text answers must be equal, numbers equal to within 1e-6, and both sides must be on the same as-of date. Any difference fails the job. The table goes to the job summary and the JSON to an artifact.

**Recorded run (2026-11-03, data as of 2026-11-02, [workflow run](https://github.com/sky-five/ridgeline-analytics/actions/runs/41635695859)):** 25 / 25 governed answers match, largest numeric difference 0. The report is `results/governed-snowflake-vs-duckdb-2026-11-03.json`.

This covers the governed arm only: the metric definitions give the same answers on either engine. The raw-table arm and the AI analyst ran on DuckDB. The Snowflake account was a trial and was suspended on 2026-11-10, so this check no longer runs; the recorded report stays.

```bash
RIDGELINE_DBT_TARGET=snowflake python -m semantic_eval.cross_target snapshot --out sf.json   # after dbt build --target snowflake
python -m semantic_eval.cross_target compare sf.json                                        # after the DuckDB build
```

Tests: tolerance (fixed-point rounding passes, real differences fail), text compared exactly, a question missing on one side or a different as-of date fails, the CLI exit code, and the committed Snowflake report reads 25 / 25.
