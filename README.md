# Ridgeline Analytics

The analytics platform of **Ridgeline**, a fictional SaaS company that sells software to roofing contractors. It covers the full path from source systems, through ingestion and a tested dbt model, to the metrics a revenue, product and customer team would use.

> **All data is synthetic.** A deterministic simulator generates it, with business patterns planted on purpose (listed below). No real company's data or code is used.

**Status:** Phase 1 of 5 is done: simulator, dlt ingestion, and dbt on DuckDB with CI. Next come Snowflake + Cortex, the MetricFlow semantic layer, Evidence dashboards and an AI analyst. See the [roadmap](#roadmap).

## Architecture

```
simulator/ ──► dlt pipelines ──► warehouse RAW ──► dbt ──► marts + metrics ──► Evidence site (Phase 3)
 6 fake source systems            (DuckDB now,                               └─► AI analyst API (Phase 4)
 paginated API, updated_at        Snowflake in Phase 2)
GitHub Actions: lint · unit tests · fresh load · dbt build · freshness · SQL lint
```

| Layer | What it does |
|---|---|
| `simulator/` | Deterministic history of six systems: app DB, product events, CRM, support desk, ad spend, and contractors' own homeowner leads. Served "as of" any date through a paginated mock API with `updated_at` cursors. |
| `pipelines/` | One dlt source per system. Incremental on `updated_at`, merge for mutable tables, append for logs, schema contracts that freeze data types. Loads about 1.2M rows in ~30s. |
| `dbt/` | Staging → intermediate → six domain mart folders. 28 models, 12 with enforced contracts, 88 tests. |

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
| customer_success | `fct_support_tickets` | ticket | Reply and resolution times |
| customer_success | `fct_account_health` | paying account | Rule-based health score and risk band |
| contractor_outcomes | `fct_contractor_leads` | homeowner lead | Speed to lead in minutes, outcomes that don't overlap |
| contractor_outcomes | `fct_contractor_benchmarks` | contractor × month | Close rate and speed vs crew-size peers |
| ops | `fct_measurement_quality` | measurement order | Turnaround and redo rate |

## How it's tested

| Kind | Count | Examples |
|---|---|---|
| dbt generic tests | 76 | Keys, accepted values, relationships, `dbt_utils` range and combination checks |
| dbt unit tests | 9 | MRR movement types and month boundaries, the 60-day paid cutoff, early signals stopping at first payment (no leakage), CAC using only cohorts with a known outcome, rep follow-ups, health-score rules, speed-to-lead buckets, peer ranks |
| dbt singular tests | 3 | Every subscription invoice equals the MRR log at issue time. Last-day MRR ties to the sum of accounts. The score's top decile beats average by ≥2.5× on held-out data. |
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
simulator/   accounts, lifecycle, side systems, world (as-of view), mock API
pipelines/   dlt sources + load CLI
dbt/         models/{staging,intermediate,marts/*}, tests/, seeds/, macros/ (cross-database helpers)
scripts/     run_all.py
tests/       pytest suites
docs/        design spec and implementation plans
```

## Roadmap

1. ✅ Simulator, dlt, dbt on DuckDB, tests, CI
2. Snowflake as a second dbt target, Cortex to classify ticket themes, snapshots
3. MetricFlow semantic layer, Evidence dashboards, nightly refresh and deploy
4. AI analyst (Claude + the semantic layer, with spending caps), retention and contractor pages
5. Polish: architecture diagram, demo video

## Notes

Built by Shubham (Sky) Yadav with Claude Code as a pair programmer. I set the design, metrics and checks, and reviewed every number.
