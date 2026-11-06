"""The DAG's steps, alerts and last-good marker, tested without Airflow installed."""
import http.server
import json
import shlex
import threading
from datetime import date
from pathlib import Path

import duckdb
import pytest

from orchestration import alerts, steps
from orchestration.mark_good import mark_good

ROOT = Path(__file__).resolve().parents[2]
S = steps.Settings(root=ROOT, python=Path("/venv/bin/python"), warehouse=ROOT / "warehouse" / "ridgeline.duckdb",
                   dlt_dir=ROOT / ".dlt_pipelines")


def test_steps_run_in_pipeline_order_and_form_a_dag():
    ids = [s.task_id for s in steps.steps(S)]
    assert ids == ["load", "dbt_deps", "dbt_build", "report_refresh", "warehouse_tests", "source_freshness",
                   "mark_good"]
    seen = set()
    for s in steps.steps(S):  # every upstream is defined earlier: no cycles, no dangling edges
        assert set(s.upstream) <= seen, s.task_id
        seen.add(s.task_id)


def test_last_good_marker_waits_for_every_check():
    by_id = {s.task_id: s for s in steps.steps(S)}
    assert set(by_id["mark_good"].upstream) == {"warehouse_tests", "source_freshness"}
    assert by_id["report_refresh"].upstream == ("dbt_build",)


def test_as_of_is_the_day_before_the_logical_date():
    assert steps.as_of_for(date(2026, 11, 3)) == date(2026, 11, 2)
    assert steps.as_of_for(date(2026, 3, 1)) == date(2026, 2, 28)
    assert steps.AS_OF_TEMPLATE == "{{ macros.ds_add(ds, -1) }}"


def test_bash_line_round_trips_after_the_template_renders():
    # Jinja renders the template before bash parses the line; the result must split back into the argv
    # we would have built for that date directly.
    templated = {s.task_id: steps.bash_command(s, S) for s in steps.steps(S)}
    for s in steps.steps(S, as_of="2026-11-02"):
        line = templated[s.task_id].replace(steps.AS_OF_TEMPLATE, "2026-11-02")
        cd, cmd = line.split(" && ", 1)
        assert shlex.split(cd)[1] == str(ROOT if s.cwd == "." else ROOT / s.cwd)
        assert tuple(shlex.split(cmd)) == s.argv


def test_build_steps_use_the_same_vars_as_the_nightly_workflow():
    by_id = {s.task_id: s for s in steps.steps(S, as_of="2026-11-02")}
    assert by_id["dbt_build"].argv[-2:] == ("--vars", "{as_of_date: '2026-11-02'}")
    assert by_id["load"].argv[:4] == ("/venv/bin/python", "scripts/run_all.py", "--fresh", "--skip-dbt")
    assert by_id["dbt_build"].argv[0] == "/venv/bin/dbt"


def test_every_script_a_step_calls_exists():
    for s in steps.steps(S):
        for arg in s.argv:
            if arg.endswith(".py"):
                assert (ROOT / arg).is_file(), arg


def test_settings_default_to_the_repo_venv_and_warehouse():
    s = steps.Settings.from_env({})
    assert s.root == ROOT
    assert s.python == ROOT / ".venv" / "bin" / "python"
    assert s.warehouse == ROOT / "warehouse" / "ridgeline.duckdb"
    assert steps.step_env(s)["RIDGELINE_DUCKDB_PATH"] == str(s.warehouse)
    assert steps.Settings.from_env({"RIDGELINE_PYTHON": "/opt/py"}).dbt == Path("/opt/dbt")


class _TI:
    dag_id, task_id, run_id, try_number = "daily_build", "dbt_build", "scheduled__2026-11-03", 3


def test_alert_names_the_task_and_error():
    a = alerts.build_alert({"task_instance": _TI(), "exception": RuntimeError("dbt exited 1"),
                            "logical_date": date(2026, 11, 3)})
    assert a["dag_id"] == "daily_build" and a["task_id"] == "dbt_build" and a["try_number"] == 3
    assert a["run_id"] == "scheduled__2026-11-03" and a["logical_date"] == "2026-11-03"
    assert a["error"] == "RuntimeError: dbt exited 1"


def test_alerts_append_one_json_line_each(tmp_path):
    path = tmp_path / "alerts.jsonl"
    alerts.send({"task_id": "load"}, path=path, webhook="")
    alerts.send({"task_id": "dbt_build"}, path=path, webhook="")
    assert [json.loads(line)["task_id"] for line in path.read_text().splitlines()] == ["load", "dbt_build"]


def test_alert_is_posted_to_the_webhook(tmp_path):
    got = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    alerts.send({"task_id": "load"}, path=tmp_path / "a.jsonl", webhook=f"http://127.0.0.1:{srv.server_port}/")
    srv.server_close()
    assert got == [{"task_id": "load"}]


def test_a_broken_webhook_does_not_hide_the_failure(tmp_path, capsys):
    alerts.send({"task_id": "load"}, path=tmp_path / "a.jsonl", webhook="http://127.0.0.1:9/", timeout=1)
    assert "alert webhook failed" in capsys.readouterr().out
    assert (tmp_path / "a.jsonl").read_text().count("\n") == 1


def _warehouse(path, empty=(), skip=()):
    with duckdb.connect(str(path)) as con:
        con.sql("create schema reporting")
        for t in ("kpi_monthly", "metric_catalog", "source_loads"):
            if t in skip:
                continue
            con.sql(f"create table reporting.{t} as select 1 as x" + (" where false" if t in empty else ""))


def test_mark_good_writes_the_marker(tmp_path):
    _warehouse(tmp_path / "wh.duckdb")
    m = mark_good(tmp_path / "wh.duckdb", date(2026, 11, 2), tmp_path / "last_good.json")
    assert json.loads((tmp_path / "last_good.json").read_text()) == m
    assert m["as_of"] == "2026-11-02" and m["reporting_rows"]["kpi_monthly"] == 1


@pytest.mark.parametrize("kw, msg", [({"skip": ("source_loads",)}, "missing: source_loads"),
                                     ({"empty": ("kpi_monthly",)}, "empty: kpi_monthly")])
def test_mark_good_refuses_an_incomplete_build(tmp_path, kw, msg):
    _warehouse(tmp_path / "wh.duckdb", **kw)
    with pytest.raises(SystemExit, match=msg):
        mark_good(tmp_path / "wh.duckdb", date(2026, 11, 2), tmp_path / "last_good.json")
    assert not (tmp_path / "last_good.json").exists()
