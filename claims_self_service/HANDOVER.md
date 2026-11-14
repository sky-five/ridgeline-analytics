# Handover: claims self-service metrics

One page for the person who takes this over. The data is simulated; the workflow is the part that carries over.

## Query a metric

Build once, then ask the semantic layer, never the tables directly:

```bash
python -m claims_self_service            # simulate, load DuckDB, dbt build, write results/
cd claims_self_service/dbt
mf list metrics                          # the 12 metrics and their dimensions
mf query --metrics loss_ratio --group-by policy__region
mf query --metrics approval_rate --group-by metric_time__quarter,policy__channel
mf query --metrics loss_ratio --group-by metric_time__month \
  --where "{{ Dimension('policy__line_of_business') }} = 'homeowners'"
mf query --metrics loss_ratio --group-by policy__region --explain   # the SQL it runs
```

From Python: `claims_self_service.metrics.query(["loss_ratio"], ["policy__channel"])` returns a DataFrame,
`explain(...)` the SQL, `list_metrics()` the catalogue.

Every metric can be grouped by `metric_time` (day to year), `policy__line_of_business`, `policy__region` and
`policy__channel`. The incurred, paid and claim-count metrics can also be grouped by `peril__peril_group`.

The [dashboard page](https://sky-five.github.io/ridgeline-analytics/claims-self-service/) drills down by summing the
additive metrics in `results/metrics_monthly.csv` and dividing. That only works because every headline metric is a
ratio of sums; a test checks the sums give MetricFlow's own answer for every line, region, channel and month.

## Add a metric

1. If it needs a new number per row, add a column to the mart (`dbt/models/marts/`) and a measure on the semantic
   model in `dbt/models/semantic/_semantic_models.yml`. Give it the right `agg_time_dimension`: loss date for
   anything about what happened, closed date for anything about how claims were handled.
2. Define the metric in `dbt/models/semantic/_metrics.yml` with a label and a description that says what is in it,
   what is left out, and which date it counts on.
3. Rebuild (`python -m claims_self_service`) and run `mf validate-configs` in `dbt/`.
4. Add a test in `tests/claims_self_service/` that recomputes it in pandas from the simulated rows.
5. If the page should show it, add its additive parts to `CUBE_METRICS` in `run.py` and a column to the page.

Do not compute a ratio in a dashboard tool from other ratios (an average of monthly loss ratios is not the loss
ratio). Add it here and sum its parts.

## What each metric is not fit for

- `loss_ratio`: recent months. Losses count by loss date and claims are reported weeks later, so the last few
  months read low until they fill in. Not cut by peril either: premium is not earned by peril, and MetricFlow
  refuses `loss_ratio` by `peril__peril_group` rather than return a wrong number. Open claims count at their case
  reserve, so it moves when reserves are revised.
- `claim_cycle_time_days`: anything about open claims. It averages closed claims only, so a growing backlog of slow
  claims makes it look better, not worse. Read it with the count of open claims.
- `approval_rate`: withdrawn claims, which are left out, and open claims. It is by close month, so a month with few
  decisions (early 2025 had under 50) swings widely. A gap between channels says where to look, not why.
- The simple metrics (`earned_premium`, `incurred_losses`, ...) are fine to add up across any slice; the three ratios
  are not.
