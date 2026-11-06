"""DAG integrity: the file imports in Airflow and wires the steps as declared. Skipped without Airflow
(it lives in its own virtualenv; the orchestration workflow runs these)."""
import shlex
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

from orchestration import alerts, steps  # noqa: E402

DAGS = Path(__file__).resolve().parents[2] / "orchestration" / "dags"


@pytest.fixture(scope="module")
def bag():
    return DagBag(dag_folder=str(DAGS))


@pytest.fixture(scope="module")
def dag(bag):
    return bag.get_dag("daily_build")


def test_dag_files_import_without_errors(bag):
    assert bag.import_errors == {}
    assert list(bag.dag_ids) == ["daily_build"]


def test_tasks_and_edges_match_the_steps(dag):
    want = steps.steps(steps.Settings.from_env())
    assert sorted(dag.task_ids) == sorted(s.task_id for s in want)
    for s in want:
        assert dag.get_task(s.task_id).upstream_task_ids == set(s.upstream), s.task_id


def test_every_task_retries_with_backoff_and_alerts(dag):
    for t in dag.tasks:
        assert t.retries == 2
        assert t.retry_exponential_backoff
        assert t.retry_delay == timedelta(minutes=1)
        assert t.execution_timeout == timedelta(minutes=30)
        assert alerts.on_failure in (t.on_failure_callback if isinstance(t.on_failure_callback, list)
                                     else [t.on_failure_callback])


def test_schedule_and_backfill_settings(dag):
    assert dag.schedule == "0 9 * * *"
    assert dag.catchup is False
    assert dag.max_active_runs == 1


def test_bash_commands_render_the_as_of_date(dag):
    from airflow.sdk.execution_time import macros

    env = dag.get_template_env()

    def argv(task_id, ds):
        line = env.from_string(dag.get_task(task_id).bash_command).render(ds=ds, macros=macros)
        return shlex.split(line.split(" && ", 1)[1])

    assert argv("dbt_build", "2026-11-03")[-2:] == ["--vars", "{as_of_date: '2026-11-02'}"]
    load = argv("load", "2026-03-01")
    assert load[load.index("--as-of") + 1] == "2026-02-28"
