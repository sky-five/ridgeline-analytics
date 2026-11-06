# Orchestration with Airflow (learning project, simulated data)

A learning project on simulated data: the nightly build (simulate and load, dbt build, refresh the reporting
tables, check) written as one Airflow 3 DAG. The GitHub Actions nightly workflow still builds and publishes the
site; this DAG runs next to it in CI and does not replace it.

```
load ─▶ dbt_deps ─▶ dbt_build ─▶ report_refresh ─┬─▶ warehouse_tests ──┬─▶ mark_good
                                                  └─▶ source_freshness ─┘
```

| Task | What it runs |
|---|---|
| `load` | `scripts/run_all.py --fresh --skip-dbt`: simulate the day and load every source with dlt into a fresh DuckDB file |
| `dbt_deps`, `dbt_build` | `dbt deps`, then `dbt build` (models, snapshots, seeds and dbt tests in dependency order) |
| `report_refresh` | `scripts/export_reporting.py`: the `reporting.*` tables the Evidence site reads, from the governed metrics |
| `warehouse_tests` | `pytest -m warehouse`: governed metrics agree with the marts and the reporting tables |
| `source_freshness` | `dbt source freshness`: every source was loaded by this run |
| `mark_good` | `orchestration/mark_good.py`: checks the reporting tables are there and not empty, then writes `warehouse/last_good.json` |

| File | What it does |
|---|---|
| `steps.py` | The steps as plain data (command, folder, upstream tasks). No Airflow import, so it is tested anywhere. |
| `dags/daily_build.py` | Turns each step into a `BashOperator` and wires the edges. |
| `alerts.py` | Failure callback: one JSON line per failed task in `warehouse/alerts.jsonl`, and a POST to `RIDGELINE_ALERT_WEBHOOK` if set. |
| `mark_good.py` | The last-good-build marker. A publisher ships only the build it names, so a failed night keeps the last good one. |

## Dates, retries and alerts

- The run for logical date D builds the warehouse as of D - 1 (`{{ macros.ds_add(ds, -1) }}`), the same "yesterday"
  the nightly workflow uses. The same as-of date always gives the same rows.
- Every task retries twice with exponential backoff (from 1 minute, capped at 10) and has a 30-minute timeout. A task that still
  fails calls `alerts.on_failure`; the run stops there and `mark_good` never runs.
- `max_active_runs=1` because every run rebuilds the same DuckDB file. `catchup=False`: history comes from an explicit
  backfill, not from switching the DAG on.

## Run it

Airflow's pinned dependencies clash with dbt's, so Airflow gets its own virtualenv and every task calls the
project's interpreter (`.venv/bin/python`, or `RIDGELINE_PYTHON`).

```bash
uv venv --python 3.12 .airflow-venv
uv pip install --python .airflow-venv "apache-airflow==3.3.2" \
  -c https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
export AIRFLOW_HOME=$PWD/.airflow AIRFLOW__CORE__DAGS_FOLDER=$PWD/orchestration/dags AIRFLOW__CORE__LOAD_EXAMPLES=False
.airflow-venv/bin/airflow db migrate
.airflow-venv/bin/airflow dags test daily_build 2026-11-03     # one full run, as of 2026-11-02
```

On a Linux laptop that run takes a little over a minute once the simulated history is cached; `dbt build` passes
133 nodes and the warehouse tests pass.

## Backfill

To rebuild a range of days, create a backfill. Each logical date runs at 09:00 UTC and builds as of the day before:

```bash
airflow backfill create --dag-id daily_build --from-date 2026-10-01 --to-date 2026-10-08 --dry-run   # list the runs
airflow backfill create --dag-id daily_build --from-date 2026-10-01 --to-date 2026-10-08             # queue them
```

The second command only queues runs; a scheduler, API server and DAG processor (`airflow standalone` locally) execute
them one at a time. CI runs the dry run only.

## Tests

- `tests/orchestration/test_steps.py` (main CI, no Airflow): step order, no dangling edges, the rendered as-of date and
  shell quoting, alerts to file and webhook (a broken webhook does not hide the failure), and the marker refusing an
  incomplete build.
- `tests/orchestration/test_dag.py` (orchestration workflow, skipped without Airflow): the DAG file imports with no
  errors, its edges match `steps.py`, every task has the retries, timeout and failure callback, and the commands
  render the right as-of date.
- [`.github/workflows/orchestration.yml`](../.github/workflows/orchestration.yml) runs those, then `airflow dags test`
  as of yesterday (it must write `last_good.json` for that date with no alerts), then the backfill dry run.
