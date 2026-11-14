# Self-service claims metrics (simulated data)

A claims team wants to answer its own questions (what is the loss ratio by region this quarter, are
claims closing faster, which channel gets denied most) without filing a ticket for each one. This folder
is the part that makes that safe: a star schema in dbt on DuckDB and a MetricFlow semantic layer that
defines loss ratio, claim cycle time and approval rate once, so every slice of them is computed the same
way. Everything runs on seeded synthetic data; no real insurer, policy or claim is in it.

```bash
python -m claims_self_service           # simulate, load, dbt build, query the semantic layer, write results/
python -m claims_self_service --check   # fail if the committed results are out of date (CI)
```

## The data

`simulate.py` writes 20,000 one-year policies starting through 2025 (half personal auto, 35% homeowners,
15% small commercial property) across four regions and three sales channels, and the 2,203 claims
reported against them up to the as-of date, 2026-06-30: 1,756 approved, 251 denied, 85 withdrawn and 111
still open. An open claim carries a case reserve as its incurred amount. Two patterns are planted: a
hailstorm in the south region in July 2025, and a direct channel whose claims are denied about twice as
often as the agent or broker channels' claims.

## The star schema

| Model | Grain | Keys |
|---|---|---|
| `dim_policy` | policy | line of business, region, channel, term, annual premium |
| `dim_peril` | peril (cause of loss) | peril group |
| `fct_claims` | reported claim | policy, peril; loss, reported and closed dates; status flags, cycle days, incurred, paid |
| `fct_premium_monthly` | policy and month in force | earned days, earned premium (annual premium spread evenly over 365 days) |

dbt tests check keys, relationships and accepted values.

## The semantic layer

[`_semantic_models.yml`](dbt/models/semantic/_semantic_models.yml) joins both facts to `dim_policy` through
the `policy` entity, and [`_metrics.yml`](dbt/models/semantic/_metrics.yml) defines 12 metrics, three of
them headline ratios:

| Metric | Definition | Time basis | Whole book |
|---|---|---|---|
| `loss_ratio` | incurred losses / earned premium | month of loss and month earned | 53.2% |
| `claim_cycle_time_days` | report-to-close days / closed claims | month closed | 26.4 days |
| `approval_rate` | approved / (approved + denied) | month closed | 87.5% |

Each can be grouped by `metric_time`, `policy__line_of_business`, `policy__region` or `policy__channel`.
`metrics.py` runs queries from Python (`query`, `explain` for the SQL, `list_metrics` for the catalogue),
and after `python -m claims_self_service` the same queries work from the command line, inside `dbt/`:
`mf query --metrics approval_rate --group-by policy__channel`. Loss ratio cannot be cut by peril, because premium is not earned by peril: MetricFlow
refuses the query rather than return a wrong number, while incurred losses alone can be.

## What the first queries show

| Slice | Loss ratio | Cycle time (days) | Approval rate |
|---|---|---|---|
| Personal auto | 58.9% | 19.7 | 87.9% |
| Homeowners | 54.7% | 29.5 | 87.2% |
| Commercial property | 47.8% | 52.8 | 86.0% |
| Agent | 52.9% | 25.3 | 90.3% |
| Broker | 47.8% | 27.8 | 89.3% |
| Direct | 58.9% | 27.3 | 80.3% |

South homeowners losses in July 2025 come to 9.4 times that month's earned premium (82 claims, against 0 to
17 in every other month), which lifts the south region to the highest loss ratio, 64.8%. All the numbers
are in [results/summary.json](results/summary.json).

## Dashboard and handover

The [Claims self-service page](https://sky-five.github.io/ridgeline-analytics/claims-self-service/) has dropdowns for
line of business, region and channel. It does not compute any metric itself: `run.py` also writes the seven additive
metrics under the three ratios (earned premium, incurred losses, claims reported, closed claims, cycle days, approved
and decided claims) from MetricFlow by month, line, region and channel to
[results/metrics_monthly.csv](results/metrics_monthly.csv) (648 rows), and the page sums the selected rows and
divides. Because each headline metric is a ratio of sums, that gives the semantic layer's own answer for any
selection. `report.py` turns the two result files into six `reporting.claims_ss_*` tables. The page also charts the
hail month (82 south homeowners claims in July 2025) and the denial rate by channel and quarter closed: the direct
channel has the highest denial rate in all six quarters. The nightly smoke test opens it.

[HANDOVER.md](HANDOVER.md) is the one page for whoever takes this over: how to query a metric from the command line
or Python, how to add one, and what each headline metric is not fit for.

## Tests

`tests/claims_self_service/` builds the warehouse once (about 10 seconds) and recomputes each headline
metric in pandas straight from the simulated rows: loss ratio by line and for the hail month, cycle time
and approval rate by channel, closed claims by close month. It also checks the monthly premium rows add up
to each policy's days in force, that the loss-ratio-by-peril slice is refused, and that the committed
results are current. `test_report.py` checks the dashboard tables: the drill-down rows sum back to MetricFlow's
answer for every line, region, channel and month, the hail month and the direct-channel gap hold in that table, and
the page reads only tables and columns the export writes.
