# Ridgeline Analytics

The analytics platform of **Ridgeline**, a fictional SaaS company that sells software to roofing contractors. It covers the full path from source systems, through ingestion and a tested dbt model, to the metrics a revenue, product and customer team would use.

> **All data is synthetic.** A deterministic simulator ([saas-world-sim](https://github.com/sky-five/saas-world-sim), pinned to a tag) generates it, with business patterns planted on purpose (listed below). No real company's data or code is used.

**Live site:** https://sky-five.github.io/ridgeline-analytics/ (rebuilt every night with one more day of the same seeded history; see [how the data is made](#how-the-data-is-made))

**Status:** Phases 1–4 of 5 are done. The same dbt project builds on **DuckDB and Snowflake** (identical numbers); CI tested both until the Snowflake trial account was suspended on 2026-11-10, and runs DuckDB only since then. A MetricFlow semantic layer feeds the Evidence site, which a nightly GitHub Actions job rebuilds and publishes. An AI analyst answers questions over the same metrics; its recorded eval is on the site's Ask the data page. See the [roadmap](#roadmap).

## Architecture

![Ridgeline Analytics architecture](reports/static/architecture.svg)

| Layer | What it does |
|---|---|
| [`saas-world-sim`](https://github.com/sky-five/saas-world-sim) (installed package) | Deterministic history of six systems: app DB, product events, CRM, support desk, ad spend, and contractors' own homeowner leads. Served "as of" any date through a paginated mock API with `updated_at` cursors. |
| `pipelines/` | One dlt source per system. Incremental on `updated_at`, merge for mutable tables, append for logs, schema contracts that freeze data types. Loads about 1.2M rows in ~30s. |
| `dbt/` | Staging → intermediate → six domain mart folders. 31 models (29 SQL, 2 Python), 12 with enforced contracts, 94 tests. |

## Data model (marts)

| Domain | Model | Grain | Answers |
|---|---|---|---|
| finance | `fct_mrr_movements` | subscription change | New, expansion, contraction, churn, reactivation |
| finance | `fct_mrr_daily` | day | Company MRR and paying accounts every day |
| finance | `dim_accounts` | account | Current plan, MRR, churn date and reason |
| growth | `fct_account_funnel` | account | First-14-day behaviour, activation, paid within 60 days |
| growth | `fct_marketing_channel_daily` | day × channel | Spend, signups, conversions, trailing-90-day CAC |
| growth | `fct_cohort_retention` | cohort × month | Logo retention, NRR, GRR |
| sales | `fct_pqa_scores` | account | Likelihood to pay (dbt **Python** model, scikit-learn), with reasons |
| sales | `fct_rep_followups` | top-decile account | Did a rep call within 3 days? |
| customer_success | `fct_support_tickets` | ticket | Reply and resolution times, churn theme |
| customer_success | `fct_ticket_themes` | ticket | Theme from hand labels + classifier (dbt **Python** model) |
| customer_success | `fct_account_health` | paying account | Rule-based health score and risk band |
| contractor_outcomes | `fct_contractor_leads` | homeowner lead | Speed to lead in minutes, outcomes that don't overlap |
| contractor_outcomes | `fct_contractor_benchmarks` | contractor × month | Close rate and speed vs crew-size peers |
| ops | `fct_measurement_quality` | measurement order | Turnaround and redo rate |

## How it's tested

| Kind | Count | Examples |
|---|---|---|
| dbt generic tests | 80 | Keys, accepted values, relationships, `dbt_utils` range and combination checks |
| dbt unit tests | 9 | MRR movement types and month boundaries, the 60-day paid cutoff, early signals stopping at first payment (no leakage), CAC using only cohorts with a known outcome, rep follow-ups, health-score rules, speed-to-lead buckets, peer ranks |
| dbt singular tests | 5 | Every subscription invoice equals the MRR log at issue time. Last-day MRR ties to the sum of accounts. The score's top decile beats average by ≥2.5× on held-out data. One current snapshot row per subscription. Ticket-theme classifier holds its accuracy on held-out labels. |
| Model contracts | 12 marts | Column names and types are enforced at build time |
| Source freshness | 11 tables | Time since the last successful pipeline load: warn after 36h, error after 72h |
| pytest | 41 | Simulator determinism, history stable across dates, planted patterns present, API paging, dlt idempotency and merge behaviour |

## What the data shows (as of 2026-10-07)

| Finding | Number |
|---|---|
| MRR / paying accounts | $243.7k / 779 |
| Accounts that send a proposal in their first 14 days | convert 39% vs 5% (~8×) |
| Top 10% by score, on 2026 signups the model never saw | 59% convert vs 16% average (3.7×) |
| Homeowner leads contacted in under 5 minutes | close 39% vs 20% at 5–60 minutes |
| Leads worked but with no first-contact time logged | 7%, a data-quality gap the dashboards must show |
| 12-month NRR | 61% (SMB churn is heavy, so retention is a key lever) |

## How the data is made

- **One fixed history.** [saas-world-sim](https://github.com/sky-five/saas-world-sim) simulates the whole period, 2024-01-01 to 2027-12-31, once from a single seed. Random draws come from keyed streams, so the result does not depend on machine or run order.
- **Revealed one day per night.** Each build cuts that history at the end of an as-of date (yesterday, UTC, in CI and the nightly job). Rows created later are dropped and statuses are recomputed, so each night the business is one day older, not a new random business.
- **Same date, same rows.** Building the same date twice gives identical tables, and an earlier date is a prefix of a later one. `tests/test_engine_pin.py` locks the 2026-06-30 row counts and money totals; `tests/revrec/test_billing.py` locks the billing snapshot.
- **Patterns are planted on purpose**, listed below (and for billing: monthly plans churn at about 3.8% of renewals, annual plans at 20%, and some churned customers come back on a new subscription).

## Planted patterns

These were built into the simulator so the analysis has something real to find:
- Channel quality differs: referral and supplier-partner signups convert best, Facebook worst.
- Sending a proposal in week 1 is the strongest upgrade signal.
- Bigger crews convert more, choose the higher plan and churn less.
- Storm season (Apr–Aug) brings more signups and leads.
- Contractors who answer leads in under 5 minutes close about 2× as often.
- Measurement-report redos lead to support tickets and raise churn.
- About 8% of lead stage times are never logged.
- Churn reasons are written in the support-ticket text.

## Where the data comes from

The simulated business used to live in a `simulator/` folder here. It is now its own package, [saas-world-sim](https://github.com/sky-five/saas-world-sim), so other demos can use the same engine. This repo installs it from git at a pinned tag (`v0.5.0`, in `requirements.txt`) and imports it in one place, `pipelines/engine.py`. The full seeded history is still cached in `.cache/` at the repo root.

Moving it did not change any number. Before the switch, the old folder and the package gave identical tables (every column, every row) as of 2024-03-01, 2025-07-15, 2026-06-30, 2026-11-02 and 2026-11-07, which is 1,245,216 rows on the last date. `tests/test_engine_pin.py` keeps it that way: it fails if `requirements.txt`, the engine tag and the installed version disagree, or if the 2026-06-30 row counts and invoice and MRR totals move. The engine's own unit tests and fingerprint tests run in its repo.

## AI analyst (Phase 4)

An agent that answers business questions from the warehouse the way an analytics engineer would: find the right mart, read its definition, prefer the governed metric, run read-only SQL, and cite where the number came from. `analyst/` holds it.

| Piece | What it does |
|---|---|
| `catalog.py` | Reads dbt's `manifest.json` and `semantic_manifest.json`: search, columns, tests, contracts, lineage back to the raw sources, and the mart each metric is built on |
| `sql_guard.py` | Read-only at three levels: the DuckDB file opens `read_only`, the session turns off file and network access and locks its settings, and every statement must parse as a single `SELECT`. Rows and run time are capped |
| `tools.py` | Six tools: `search_catalog`, `describe_model`, `get_lineage`, `list_metrics`, `query_metric`, `run_sql`. Metric queries are compiled by MetricFlow and run through the same guard, so the agent's numbers match the dashboards |
| `server.py` | MCP server over stdio, so Claude Code, Claude Desktop or any MCP client can use the tools |
| `agent.py`, `llm.py` | The same tools as an API agent, capped at 12 model calls and 300k tokens per question. The model client is pluggable: Claude (`claude-opus-5-5` by default) or Gemini's free tier (`--provider gemini`) |
| `evals/` | 20 questions with answers computed from the marts at run time, scored for correctness (0.5% or half a point) and grounding (did it cite the right mart) |

```bash
claude mcp add ridgeline -- .venv/Scripts/python -m analyst.server     # use it from Claude Code
.venv/Scripts/python -m analyst.agent "What was MRR at the end of September 2026?"
.venv/Scripts/python -m analyst.evals.run --backend claude-code        # or --backend api
```

The eval questions cover governed metrics, ad hoc SQL with the right filters (mature signups only, open leads excluded), lineage, and one question the warehouse can't answer, where the right reply is "no data" rather than a guess.

**First run (2026-10-30, data as of 2026-10-29, Claude Code headless with the MCP server):**

| Result | Number |
|---|---|
| Correct answers | 20 / 20 |
| Cited the right mart | 20 / 20 |
| Answered through a governed metric | 15 / 20 |
| Median time / tool calls per question | 28 s / 5 |
| Cost at API rates, all 20 questions | $3.66 |

For the NPS question it searched every table and column for survey data, found none and returned no number. Full transcripts: `analyst/evals/results/`. These questions state their definitions; the next eval adds vaguer questions ("how are we doing on retention?") where choosing the definition is the hard part.

## Semantic eval: raw tables vs governed metrics

`semantic_eval/` is a test set for one question: is an AI analyst more reliable when it can only use governed metrics? 25 business questions, worded the way a stakeholder would ask them, each with an answer computed from the MetricFlow metrics and a note on the mistake a raw-table query tends to make (summing daily MRR, counting signups too young to judge, dividing by open leads). Answers about closed periods are checked on every CI build.

The analyst answered each question twice, once with only the raw loaded tables and once with only the governed metrics (Claude Code, claude-sonnet-5-5). **Governed metrics: 25 / 25 correct. Raw tables: 17 / 25.** Revenue questions were right either way; the raw misses were all definition questions (trial-to-paid, activation, lead close rate, CAC, NRR), where it picked its own definition and returned a confident number. The same eval on a free-tier model (gemini-3.5-flash-lite through the Gemini API): governed 24 / 25, raw tables 12 / 25. Both recorded runs replay without an API key. The site's [Raw tables vs governed metrics page](https://sky-five.github.io/ridgeline-analytics/raw-vs-governed/) shows both runs side by side and opens each of the 20 raw-table misses (8 + 12) with the trap, the definition the agent picked and its last SQL. Details: [semantic_eval/README.md](semantic_eval/README.md).

```bash
.venv/Scripts/python -m semantic_eval.answer_key
.venv/Scripts/python -m semantic_eval.run --replay semantic_eval/results/raw-vs-governed-2026-11-03.json
```

## Metric contract

A PR that changes a governed metric's numbers has to say so. Each of the 27 metrics carries a version, and `metric_contract/contract.json` records its values on a fixed snapshot (the warehouse as of 2026-06-30, by month). A CI job rebuilds that snapshot on every PR and fails if a metric's value moved while its version stayed the same; a deliberate change bumps the version and re-records the values, so the new numbers show up in review. [PR #1](https://github.com/sky-five/ridgeline-analytics/pull/1) is the demo: a one-line change that counts win-backs as expansion MRR passes the build and fails the contract. Details: [metric_contract/README.md](metric_contract/README.md).

## Metric glossary and reconciliation

Each of the 27 governed metrics has a second calculation in plain SQL that skips MetricFlow and, where it can, starts from an earlier table: MRR is rebuilt from the movement ledger instead of the daily MRR mart, signups, spend, leads, tickets and orders from the staging models, and the 60-day funnel flags from their timestamps. `python -m metric_glossary` compares the two for every month and fails on any difference, or on a metric with no check; CI and the nightly build run it. On the warehouse as of 2026-11-10 all 27 agree on all 35 months. The site's [Metric glossary page](https://sky-five.github.io/ridgeline-analytics/metrics/) lists each definition, its last full month and the check's SQL. Details: [metric_glossary/README.md](metric_glossary/README.md).

## Ask the funnel

The site's [Ask the funnel page](https://sky-five.github.io/ridgeline-analytics/ask-the-funnel/) is a question box that answers only with governed metrics. It has no language model: one SQL query matches the question's words against a phrase list for six funnel metrics (signups, activation rate, free to paid, paid conversions, ad spend, CAC), an optional channel and an optional month or year, and looks the value up in a table queried through MetricFlow. A question that names none of them ("what is our churn rate?") is refused, and a period with no value gets "no value", not a guess. The page runs the query in the browser; the repo has the same query in `funnel_ask/route.sql`, and a test keeps the two identical. Details: [funnel_ask/README.md](funnel_ask/README.md).

```bash
python -m funnel_ask "What was CAC for Google Ads in March 2026?"
```

## ARR and revenue recognition

`revrec/` is the month-end close on the engine's billing pack, a separate seeded subscription business with monthly and annual plans, prorated upgrades, refunds, seat changes and churn. It builds ratable revenue by day, a deferred revenue rollforward and a per-customer ARR bridge in DuckDB SQL. A separate Python calculation then has to match every number to the cent (201 of them), and a test plants an error to show the check catches it. It also shows three ARR definitions side by side (contract, billed and revenue run-rate) with a bridge that explains the gap; in September 2026 contract ARR is $736,260 and run-rate ARR $679,531. CI and the nightly job run the close and the parallel check as of yesterday. Details: [revrec/README.md](revrec/README.md).

```bash
.venv/Scripts/python -m revrec
```

## ARR source of truth

`arr_source_of_truth/` reconciles what sales booked in the CRM with the ARR billing actually started. Billing's contract side is the one source of truth: a small dbt project on DuckDB builds the ARR bridge (new, reactivation, expansion, contraction, churn) from it, matches each closed-won deal to the billing change it should have started, and walks CRM bookings to billing ARR month by month in signed steps that add up to the cent (duplicates, won but never billed, awaiting billing, amount fixes, timing, missing deals, then seat changes and churn). The CRM deals are made from the billing pack with five kinds of planted mistakes whose labels the warehouse never sees. As of 2026-09-30 all 461 matched deals land on the change they came from, 84 of the 85 planted mistakes are flagged (the last is an annual deal closed in late September that billing has not started yet) with no false flags, and the dbt bridge equals revrec's independent Python reference in all 21 months. The site's [ARR: from CRM to billing page](https://sky-five.github.io/ridgeline-analytics/arr-walk/) shows the walk for any month, the bridge, each deal's match status and the deals that need a look, rebuilt every night with the rest of the site. An ARR agent answers questions only through these three models (no SQL tool), names the model behind each answer, and has a check that holds back any answer citing a model it didn't read or quoting a number no tool returned. On a 20-question eval (14 answerable, 6 out of scope) a recorded gemini-3.5-flash-lite run got 14 of 14 right and refused all 6; a no-model keyword baseline got 11 of 14 and refused all 6; neither delivered a wrong number. Details: [arr_source_of_truth/README.md](arr_source_of_truth/README.md).

## Trusted HR metrics

`trusted_metrics_agent/` serves governed HR and payroll metrics through a read-only MCP server with a role check in front. Synthetic exports for about 300 people (no names or personal fields) go through a small dbt project on DuckDB into one table; `metrics.yml` defines nine metrics on it (headcount, hires, leavers, 12-month attrition, tenure, payroll cost, overtime share, average salary), each with an owner, version and sensitivity, and four roles with the metrics and breakdowns each may see. Every result carries the definition it came from; anything outside the role is declined with a reason and no values; pay values for groups under 5 people are withheld. There is no SQL tool, and no tool takes a role. Tests recompute every metric for every month straight from the raw exports and check each role against the policy. An agent answers plain-language questions only through that server (stdio, one server per role); a check holds back any answer whose numbers or cited definitions did not come from a tool result. On a 30-question eval (18 answerable, 6 the role may not see, 6 out of scope), gemini-3.5-flash-lite on Gemini's free tier got all 18 answers right and delivered no value it should not have; the committed run replays with no key. Details: [trusted_metrics_agent/README.md](trusted_metrics_agent/README.md).

## Acquisition spend

`acquisition_spend/` asks where the next marketing dollar should go. It computes channel CAC from the governed funnel and spend marts (blended $846, paid channels $1,427 per paying account, May 2025 to April 2026), then a budget what-if built on lead-score deciles: each paid channel's yield per dollar is its signups per dollar times its mix across score deciles times each decile's paid rate. Moving 10% of trade-show spend to Google Ads adds about 1.5 paying accounts a month. A back-test fitted on 2025 predicted 98.7 paid accounts from January-April 2026 spend against 101 actual. Details: [acquisition_spend/README.md](acquisition_spend/README.md).

```bash
.venv/Scripts/python -m acquisition_spend --move trade_show google_ads 2000
```

## Outbound notes

`outbound_notes/` drafts a short first note for each of the 25 top-decile leads on the call list (2026-06-30 snapshot), using only that lead's own first-14-day signals and the score's top reasons, and checks every note: each number must be one of the lead's facts, each activity or channel it mentions must be backed by one, and it must not mention the score or offer money. A no-model template passes 25 of 25; drafts recorded once from Gemini's free tier (`gemini-3.5-flash-lite`) pass 23 of 25 and replay in CI without a key. Details: [outbound_notes/README.md](outbound_notes/README.md).

## A/B test analysis

`experiments/` is a learning project on simulated data: an onboarding experiment (a guided setup checklist vs the current flow) with a planted true lift of 4 points on 30% activation. It plans the sample size (2,131 per arm), reads out the test with a 95% interval, checks the traffic split for a sample-ratio mismatch (and catches a planted tracking bug that would have doubled the apparent lift), and shows with 2,000 A/A tests why stopping at the first significant day is a mistake (5.1% false positives testing once, 25.6% testing daily). The site's [A/B test page](https://sky-five.github.io/ridgeline-analytics/experiments) shows the readout. Details: [experiments/README.md](experiments/README.md).

```bash
.venv/Scripts/python -m experiments
```

## Orchestration with Airflow

`orchestration/` is a learning project on simulated data: the nightly build as one Airflow 3 DAG (load, dbt build, reporting refresh, warehouse tests and source freshness, then a last-good-build marker), with retries and backoff, a failure alert callback and a backfill example. A separate workflow runs DAG integrity tests and one full `airflow dags test` run on every change; the GitHub Actions nightly still publishes the site. Details: [orchestration/README.md](orchestration/README.md).

## Sales CRM data model

`crm_pipeline/` is a learning project on simulated data. It takes the standard CRM objects from saas-world-sim's sales CRM pack (leads, accounts, contacts, opportunities, opportunity history) and models them in a small dbt project on DuckDB: pipeline coverage, stage conversion, sales velocity and a quarter-start forecast back-tested over 9 quarters. The pack's duplicate accounts and backdated close dates are fixed in the models and scored against labels the warehouse never sees. As of 2026-06-30, the models find 60 of 61 duplicates and all 9 backdated deals closed by then, with no false matches. Stage win rates learned from history cut the forecast error from 27.1% to 19.6%. There are also four SOQL-style example queries, each with a SQL version that runs. Details: [crm_pipeline/README.md](crm_pipeline/README.md).

## Wholesale vehicle auction

`vehicle_auction/` is a learning project on simulated data: 26 weekly sales of dealers' used cars in a physical lane, a lane with online simulcast and a timed online sale, modelled in a small dbt project on DuckDB. Sell-through has three tested definitions (on the block, with if-sales, and per car across relists); in the physical lane the same cars give 57%, 70% or 84%. A simulated reserve-price test (95% vs 100% of book value, 6,300 cars split by a hash of the id) raises first-run conversion by 12.2 points (95% CI 10.0 to 14.4); the simulator knows the true effect on the same cars, +13.1 points, and the tests check the interval covers it. The site's [Vehicle auction page](https://sky-five.github.io/ridgeline-analytics/vehicle-auction/) shows the three definitions by channel and week and the test readout next to the true effect. Details: [vehicle_auction/README.md](vehicle_auction/README.md).

## Migration kit

`migration_kit/` moves a table from a nightly full reload to an incremental load and proves the two match. It runs both loaders side by side on real snapshots of the public USGS earthquake feed (magnitude 2.5+, past 30 days), which changes every few minutes. The new loader is a DuckDB `MERGE` with a row-hash change-capture step and a change log; events that leave the feed are kept and labelled aged out or deleted. After every load a reconciliation checks row counts, keys, all 22 columns row by row and four aggregates. On the 4 committed snapshots it matched every time, while an event-time watermark loader (the usual shortcut) failed on 3 of 4 by missing revisions and age-outs. A generated retirement checklist covers column lineage, the parallel-run record and any code still reading the old table; the nightly workflow repeats the check on that day's feed. Details: [migration_kit/README.md](migration_kit/README.md).

## Report reconciliation

`report_reconciliation/` checks three reports (project hours and cost by month, resource utilisation by week, project budget burn) against their sources before they go to UAT. The project, resource and time data is synthetic and built from source to mart in DuckDB. Each mart is compared with numbers recomputed in pandas from the source tables: row counts by grain key, totals per measure and per key, refresh age of every input, and column lineage against the catalog. All three reports pass; five planted faults (a rate join that double-counts people with a raise, rejected hours left in, closed projects dropped, a 30-hour-old extract, an undocumented column) are each caught, and CI fails if one gets through. A generated UAT checklist per report ticks the automated items and leaves the owner's sign-off open. The site's [Report reconciliation page](https://sky-five.github.io/ridgeline-analytics/report-reconciliation/) shows pass/fail by report and check, the planted-fault matrix and the open UAT items. Details: [report_reconciliation/README.md](report_reconciliation/README.md).

## Customer health scoring

`customer_health/` is a learning project on simulated data. It takes a monthly snapshot of every live subscriber's usage, tickets, re-measure requests, late invoices and plan, using only data from before the snapshot date. It then compares a hand-weighted health score with a logistic-regression model at predicting a cancel in the next 60 days, on 280 held-out accounts. Both are only a little better than chance (ROC AUC 0.594 for the score, 0.599 for the model), because churn in this simulation is mostly random and crew size is the main driver. The site's [Renewals at risk page](https://sky-five.github.io/ridgeline-analytics/renewals-at-risk/) lists the 683 live subscriptions on 2026-07-01 with the riskiest fifth by each method and the reasons behind each score. Details: [customer_health/README.md](customer_health/README.md).

## Data health

`data_health/` writes a contract for the simulator's product events (16 rules on columns, types, ids, the six event types, proposal values and timestamps) and checks each day's batch against it. All 623,164 events up to 2026-06-30 pass. 18 injected bad batches (an unknown event type, a value in cents, a replayed batch, an event from tomorrow, a dropped column and others) each fail on exactly the rule meant to catch them, and the command exits 1. CI checks yesterday's batch on every push.

A table health scorecard grades every source table's daily batch green, amber or red on freshness, volume and null rate, each against the table's own last 28 days, with a one-line reason. On 2,013 clean table-days it gives no red and 39 ambers; injected faults (a stuck loader, half a batch, a batch loaded twice, a column going blank) turn red on the busy feeds, and the README lists which small tables are too small to show which fault. It is on the [Data health page](https://sky-five.github.io/ridgeline-analytics/data-health/), and CI fails if yesterday's batches have a red table. Details: [data_health/README.md](data_health/README.md).

## Account reviews

One Evidence page template renders a review for each of the 25 largest paying accounts by MRR, rebuilt every night: [Account reviews](https://sky-five.github.io/ridgeline-analytics/account-reviews/). Each review shows the last 12 complete months of MRR, homeowner leads won and closed, measurement orders and redos, and support tickets, plus the account's health score and a few talking points built from the same numbers. Each review opens with a short written summary; a checker finds every number in it and the build fails unless each one matches the review's own tables ([how it works](account_reviews/README.md#checked-summary)). The monthly figures are the governed metrics grouped by the `account` entity, so a review can't disagree with the company-wide pages. A warehouse test checks every account's month-end MRR against the MRR movements and its tickets against the support mart. Code: [account_reviews/](account_reviews/), template: [reports/pages/account-reviews/[account_id].md](reports/pages/account-reviews/%5Baccount_id%5D.md).

[Opportunities](https://sky-five.github.io/ridgeline-analytics/account-reviews/opportunities/) lists every paying account whose measurement orders fell 40% or more, or whose lead close rate dropped 15 points or more, comparing the last 3 complete months with the 3 before, with a one-line reason built from those totals. On the 2026-11-10 build it flagged 63 of 796 paying accounts (22 on orders, 42 on close rate, 1 on both). A warehouse test recounts every flagged account's orders and leads straight from the marts ([rules and limits](account_reviews/README.md#opportunities)).

## Snowflake

The Snowflake trial account was suspended on 2026-11-10. Since then CI builds DuckDB only and `.github/workflows/snowflake.yml` runs on demand only; the parity checks recorded while the trial lasted are in `semantic_eval/results/`.

Run `infra/snowflake/setup.sql` once as ACCOUNTADMIN (it replaces `<PUBLIC_KEY>` with your key's public half), put the dlt credentials in `.dlt/secrets.toml`, then:

```bash
python -m pipelines.run --destination snowflake
cd dbt && SNOWFLAKE_PRIVATE_KEY_PATH=~/.ridgeline/rsa_key.p8 dbt build --profiles-dir . --target snowflake
python scripts/compare_targets.py   # same numbers on both warehouses
```

## Run it

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python scripts/run_all.py --fresh                          # simulate → load → dbt build
.venv/Scripts/python -m pytest -m "not e2e"                              # Python tests
```

`run_all.py` loads data as of yesterday by default. `--as-of YYYY-MM-DD` picks a date between 2024-03-01 (before that, some systems have no rows yet) and 2027-12-31 (the end of the simulated history). The same date always gives the same data. Use `--fresh` when moving to an earlier date. The first run simulates the full history (about a minute) and caches it in `.cache/`.

## Repo map

```
pipelines/   dlt sources + load CLI; engine.py imports the pinned saas-world-sim package
dbt/         models/{staging,intermediate,marts/*}, tests/, seeds/, macros/ (cross-database helpers)
semantic_eval/ business questions, governed-metric answer key, raw-vs-governed eval and its recorded run
orchestration/ Airflow DAG for the nightly build, failure alerts, last-good marker (learning project)
experiments/ simulated A/B test: sample size, readout, SRM check, peeking demo (learning project)
crm_pipeline/ sales CRM objects in dbt: dedupe, close-date fixes, coverage, velocity, forecast back-test (learning project)
migration_kit/ full reload to incremental merge on a public feed, reconciled after every load, retirement checklist
report_reconciliation/ three reports checked against their sources (rows, totals, refresh, lineage), planted faults, UAT checklist
vehicle_auction/ simulated car auction in dbt: sell-through by channel, a reserve-price test checked against the truth (learning project)
account_reviews/ the tables behind one review page per large account, from the governed metrics
metric_contract/ versioned governed metrics, checked on a fixed snapshot in CI
metric_glossary/ an independent SQL check for every governed metric, compared month by month
funnel_ask/  questions answered only from governed funnel metrics, or refused (the Ask the funnel page)
data_health/ product-event contract and table health scorecard, checked daily, with injected faults as tests
customer_health/ monthly account snapshots, a health score vs a churn model on held-out accounts (learning project)
acquisition_spend/ channel CAC and a budget what-if on lead-score deciles, with a back-test
outbound_notes/ per-lead outbound notes for the top score decile, drafted and checked against each lead's facts
trusted_metrics_agent/ governed HR and payroll metrics behind a role check, a read-only MCP server, and an agent with a 30-question eval
arr_source_of_truth/ CRM closed-won deals reconciled to the billing ARR bridge, in dbt, scored on planted mistakes
revrec/      ARR bridge, ratable revenue and deferred revenue on synthetic billing, with a parallel-run check
scripts/     run_all.py, compare_targets.py (DuckDB vs Snowflake parity)
tests/       pytest suites
docs/        design spec and implementation plans
```

## Roadmap

1. ✅ Simulator, dlt, dbt on DuckDB, tests, CI
2. ✅ Snowflake as a second target (key-pair service user, least-privilege roles, credit-capped warehouse: `infra/snowflake/setup.sql`), with its own CI job and a DuckDB parity check. SCD2 snapshot of subscriptions. Support-ticket churn themes come from 300 tickets labelled by Claude Code plus a TF-IDF classifier (100% on held-out labels). Snowflake Cortex `AI_CLASSIFY` is blocked on trial accounts, so it sits behind a `use_cortex` flag for paid accounts.
3. ✅ MetricFlow semantic layer (27 governed metrics), Evidence site (scorecard, acquisition, ready for sales, data health, metric glossary), nightly simulate → load → build → deploy to GitHub Pages with a smoke test
4. ✅ AI analyst: MCP server, read-only SQL guard, Claude API agent with spending caps, 20-question eval, shown on the site's "Ask the data" page as a recorded run (no live LLM calls). Retention and contractor outcome pages
5. Polish: architecture diagram, demo video

## Notes

Built by Shubham Yadav with Claude Code as a pair programmer. I set the design, metrics and checks, and reviewed every number.
