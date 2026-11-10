# Metric contract

A governed metric should not change its numbers quietly. A one-line edit to a measure, a staging model or a
join under it can move MRR or a close rate, and the dbt build and the usual tests still pass. This folder
turns that into a CI failure unless the change is declared.

## How it works

- Every metric in `dbt/models/semantic/_metrics.yml` has a version: `config: {meta: {version: 1}}`.
- `contract.json` records each metric's version and its values on one fixed snapshot: the warehouse built as
  of **2026-06-30**. Metrics with a time dimension are recorded by month (30 months); the three cohort
  metrics (`nrr_12m`, `retained_mrr`, `cohort_start_mrr`) as one total. 27 metrics in all.
- The `metric-contract` job in `.github/workflows/ci.yml` builds that snapshot on every PR and push to main
  (the simulated history is seeded, so the same date always gives the same rows) and runs the check.

The check fails when:

| Case | Message starts with |
|---|---|
| A value moved and the version did not | `value changed on the 2026-06-30 snapshot without a version bump` |
| The version went up but the contract was not updated | `bumped to v2 but the contract still has v1` |
| The version went down | `version went down` |
| A metric was added or removed | `new metric not in the contract` / `no longer defined` |
| `contract.json` values were edited by hand at the same version (compared with the base branch) | `contract values edited without a version bump` |

Values are compared to 6 decimals with a relative tolerance of 1e-9, so float noise is not a change.

## Making a change on purpose

```bash
python scripts/run_all.py --fresh --as-of 2026-06-30   # build the snapshot
# edit the metric, then bump its config.meta.version in dbt/models/semantic/_metrics.yml
python -m metric_contract --update                     # records bumped and new metrics only
python -m metric_contract                              # OK 27 governed metrics match their contract
```

`--update` refuses to re-record a metric whose values moved at the same version, so the only way to new
numbers is a version bump, and the PR diff shows the new values next to it.

## Demo

[PR #1](https://github.com/sky-five/ridgeline-analytics/pull/1) changes one line: expansion MRR now adds
reactivated MRR. The build and the other tests pass; the `metric-contract` job fails on `expansion_mrr`,
which moved in 24 of its 30 months (`2024-07: 545 -> 794; 2024-08: 595 -> 1,442; ...`). The PR stays open
as the example.

## Tests

`tests/metric_contract/test_contract.py`: 13 unit tests on small hand-made contracts (silent change, float
noise, bump then update, refused update, version going down, new and removed metrics, hand-edited contract,
missing version) and one warehouse test that the 2026-06-30 build matches the committed contract.
