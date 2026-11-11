# Metric glossary

Every governed metric in `dbt/models/semantic/_metrics.yml` gets a second calculation that does not go
through MetricFlow, and the two must agree for every month. The site's
[Metric glossary page](https://sky-five.github.io/ridgeline-analytics/metrics/) shows each definition, its last
full month, the check's status and the check's SQL.

## Why a second calculation

The metric contract (`metric_contract/`) catches a metric whose numbers *change*. It cannot catch one that was
wrong from the start: a measure that sums a level, a ratio over the wrong denominator, a mart that drops rows.
A check written separately, from an earlier table where possible, disagrees with the governed metric when
either side has that kind of bug.

| Metrics | Checked from | What the check rebuilds |
|---|---|---|
| MRR, paying accounts | `fct_mrr_movements` | each account's month-end balance from the movement ledger, not the daily MRR mart |
| New, expansion, churned, net new MRR | `fct_mrr_movements` | sums by movement type |
| Signups | `stg_app_db__accounts` | distinct accounts by signup month |
| Activation, mature signups, free to paid | `fct_account_funnel` | the 60-day flags from their timestamps and activation from the 14-day proposal count, not the `is_*` columns |
| Ad spend, paid conversions, CAC | `stg_ads__ad_spend`, `stg_app_db__accounts` | spend from the ad rows; conversions from every channel, so CAC over all channels is blended |
| Leads, won/closed leads, close rate, speed to lead | `stg_contractor_ops__leads` | outcome groups and whole minutes to first contact from the staging rows |
| Tickets | `stg_support__tickets` | distinct tickets by month |
| Measurement orders, redos, redo rate | `stg_app_db__measurement_orders` | redo = a redo request time is set |
| 12-month NRR, cohort MRR | `fct_cohort_retention` | sums by cohort month |

All 27 metrics agree on all 35 months of the warehouse built as of 2026-11-10 (945 metric-months). Values are
compared with a relative tolerance of 1e-9 (absolute 1e-6). A month present on only one side fails unless the
other side would be zero or empty there.

## Run it

```bash
python scripts/run_all.py --fresh          # build the warehouse
python -m metric_glossary                  # 27 of 27 governed metrics reconcile with their independent check
```

It exits 1 on any month that differs, or if a metric in `_metrics.yml` has no check, so a new metric needs a
check in `checks.py` before CI passes. CI and the nightly build run it after the warehouse build.

Tests: `tests/metric_glossary/` (the comparison rules, one check per metric, every metric described) and
`tests/test_metric_glossary.py` (all 27 agree on the built warehouse; a check that leaves out reactivations
fails on net new MRR; the glossary table is exported for the site).
