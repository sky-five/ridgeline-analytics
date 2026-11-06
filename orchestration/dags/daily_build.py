"""Nightly build as an Airflow DAG: load -> dbt build -> report refresh -> checks -> mark good.

Each run for logical date D builds the warehouse as of D - 1. Retries with exponential backoff on every
task; a task that still fails after its retries writes an alert (orchestration/alerts.py) and the run
stops before mark_good, so the last good build stays the one a publisher ships.

Backfill (needs a running scheduler and API server; see orchestration/README.md):
    airflow backfill create --dag-id daily_build --from-date 2026-10-01 --to-date 2026-10-07
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, for `orchestration`

from orchestration import alerts, steps  # noqa: E402

SETTINGS = steps.Settings.from_env()

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=30),
    "on_failure_callback": alerts.on_failure,
}

with DAG(
    dag_id="daily_build",
    description="Simulate and load the day, dbt build, refresh reporting tables, check, mark good",
    schedule="0 9 * * *",  # same time as the nightly GitHub workflow
    start_date=datetime(2026, 10, 1),
    catchup=False,  # history comes from explicit backfills, not from turning the DAG on
    max_active_runs=1,  # every run rebuilds the same DuckDB file
    default_args=default_args,
    tags=["ridgeline", "nightly"],
    doc_md=__doc__,
) as dag:
    tasks = {}
    for step in steps.steps(SETTINGS):
        tasks[step.task_id] = BashOperator(
            task_id=step.task_id,
            bash_command=steps.bash_command(step, SETTINGS),
            env=steps.step_env(SETTINGS),
            append_env=True,
            doc_md=step.doc,
        )
        for up in step.upstream:
            tasks[up] >> tasks[step.task_id]
