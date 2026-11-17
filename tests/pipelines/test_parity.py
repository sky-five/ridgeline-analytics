"""The incremental-vs-rebuild check: what it catches, what it ignores on purpose, and a real load chain."""
from datetime import date
from pathlib import Path

import duckdb
import pytest
import yaml

from pipelines.parity import compare
from pipelines.run import load
from scripts.run_all import loaded_as_of_path, prepare

ROOT = Path(__file__).resolve().parents[2]


def _db(path: Path, *sql: str) -> Path:
    with duckdb.connect(str(path)) as c:
        c.sql("create schema raw_x; create schema snapshots")
        c.sql("create table raw_x.t (id int, amount double, note varchar, _dlt_load_id varchar, _dlt_id varchar)")
        c.sql("insert into raw_x.t values (1, 10.5, 'a', 'load1', 'r1'), (2, 20.25, 'b', 'load1', 'r2')")
        c.sql("create table raw_x._dlt_loads (load_id varchar, status int)")
        for s in sql:
            c.sql(s)
    return path


def _problems(a: Path, b: Path) -> dict[str, str]:
    return {c.name: c.problem for c in compare(a, b) if c.problem}


def test_same_rows_match_whatever_the_order_and_load_ids(tmp_path):
    a = _db(tmp_path / "a.duckdb", "insert into raw_x._dlt_loads values ('load1', 0)")
    b = _db(tmp_path / "b.duckdb",
            "delete from raw_x.t",
            "insert into raw_x.t values (2, 20.25, 'b', 'other', 'q2'), (1, 10.5, 'a', 'other', 'q1')",
            "insert into raw_x._dlt_loads values ('x', 0), ('y', 0)")
    checks = compare(a, b)
    assert [c.name for c in checks] == ["raw_x.t"]  # _dlt_loads is bookkeeping, left out
    assert checks[0].problem is None and checks[0].rows_a == 2


@pytest.mark.parametrize(("change", "problem"), [
    ("insert into raw_x.t values (3, 1.0, 'c', 'l', 'r')", "row count 2 vs 3"),
    ("update raw_x.t set note = 'B' where id = 2", "same row count, different rows"),
    ("update raw_x.t set amount = 20.26 where id = 2", "same row count, different rows"),
    ("update raw_x.t set note = null where id = 1", "same row count, different rows"),
    ("alter table raw_x.t add column extra int", "columns differ: extra"),
])
def test_a_changed_table_is_reported(tmp_path, change, problem):
    a, b = _db(tmp_path / "a.duckdb"), _db(tmp_path / "b.duckdb", change)
    assert _problems(a, b) == {"raw_x.t": problem}


def test_a_duplicated_row_is_not_hidden_by_a_missing_one(tmp_path):
    # count stays 2 but the multiset differs: one row twice instead of two different rows
    a = _db(tmp_path / "a.duckdb")
    b = _db(tmp_path / "b.duckdb", "delete from raw_x.t where id = 2",
            "insert into raw_x.t values (1, 10.5, 'a', 'l', 'r')")
    assert _problems(a, b) == {"raw_x.t": "same row count, different rows"}


def test_a_table_on_one_side_only_is_reported(tmp_path):
    a = _db(tmp_path / "a.duckdb", "create table raw_x.new_table (id int)")
    b = _db(tmp_path / "b.duckdb")
    assert _problems(a, b) == {"raw_x.new_table": "only in the first warehouse"}
    assert _problems(b, a) == {"raw_x.new_table": "only in the second warehouse"}


def test_last_bit_float_noise_and_build_times_are_ignored(tmp_path):
    a = _db(tmp_path / "a.duckdb",
            "create schema reporting",
            "create table reporting.meta as select 0.1 + 0.2 as total, timestamp '2026-11-17 09:00' as built_at",
            "create table reporting.source_loads as select 1 as loads")
    b = _db(tmp_path / "b.duckdb",
            "create schema reporting",
            "create table reporting.meta as select 0.3 as total, timestamp '2026-11-17 09:05' as built_at",
            "create table reporting.source_loads as select 7 as loads")
    assert _problems(a, b) == {}


def test_snapshots_compare_current_rows_and_count_history(tmp_path):
    snap = "create table snapshots.snap (id int, status varchar, dbt_valid_to timestamp)"
    a = _db(tmp_path / "a.duckdb", snap,
            "insert into snapshots.snap values (1, 'trial', timestamp '2026-10-03'), (1, 'active', null)")
    b = _db(tmp_path / "b.duckdb", snap, "insert into snapshots.snap values (1, 'active', null)")
    (check,) = [c for c in compare(a, b) if c.name == "snapshots.snap"]
    assert check.problem is None and (check.history_a, check.history_b) == (1, 0)

    c = _db(tmp_path / "c.duckdb", snap, "insert into snapshots.snap values (1, 'churned', null)")
    assert _problems(a, c) == {"snapshots.snap": "same row count, different rows"}


def test_increments_land_on_the_same_raw_tables_as_one_full_load(tmp_path):
    inc, full = tmp_path / "inc.duckdb", tmp_path / "full.duckdb"
    loaded = [sum(load(day, duckdb_path=str(inc), pipelines_dir=str(tmp_path / "dlt_inc")).values())
              for day in (date(2024, 3, 31), date(2024, 4, 1), date(2024, 4, 29))]
    assert all(n > 0 for n in loaded) and loaded[1] < loaded[0]  # the next day is a small increment
    load(date(2024, 4, 29), duckdb_path=str(full), pipelines_dir=str(tmp_path / "dlt_full"))
    checks = compare(inc, full)
    assert len(checks) == 11  # every raw table of the six source systems
    assert [c.name for c in checks if c.problem] == []
    assert sum(c.rows_a for c in checks) > 10_000


def test_prepare_starts_over_without_a_usable_warehouse(tmp_path):
    wh, dlt_dir = tmp_path / "ridgeline.duckdb", tmp_path / "dlt"
    dlt_dir.mkdir()
    (dlt_dir / "state.json").write_text("{}")
    assert prepare(wh, dlt_dir, date(2026, 10, 1), fresh=False) == "full"
    assert not dlt_dir.exists()  # cursors without their warehouse would load nothing


def test_prepare_builds_on_the_last_load_and_refuses_to_go_back(tmp_path):
    wh, dlt_dir = tmp_path / "ridgeline.duckdb", tmp_path / "dlt"
    wh.write_bytes(b"x")
    dlt_dir.mkdir()
    loaded_as_of_path(wh).write_text("2026-10-01\n")
    assert prepare(wh, dlt_dir, date(2026, 10, 1), fresh=False) == "incremental"
    assert prepare(wh, dlt_dir, date(2026, 10, 2), fresh=False) == "incremental"
    with pytest.raises(SystemExit, match="--fresh"):
        prepare(wh, dlt_dir, date(2026, 9, 30), fresh=False)
    assert wh.exists() and dlt_dir.exists()
    assert prepare(wh, dlt_dir, date(2026, 9, 30), fresh=True) == "full"
    assert not wh.exists() and not dlt_dir.exists() and not loaded_as_of_path(wh).exists()


def test_nightly_loads_incrementally_and_checks_a_rebuild_weekly():
    wf = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    steps = wf["jobs"]["build"]["steps"]
    names = [s.get("name", s.get("uses", "")) for s in steps]
    restore = steps[names.index("Restore warehouse and pipeline state")]
    save = steps[names.index("Save warehouse and pipeline state for tomorrow")]
    build = steps[names.index("Load (incremental) + dbt build")]
    check = steps[names.index("Weekly check, a rebuild from scratch gives the same warehouse")]

    assert restore["uses"].startswith("actions/cache/restore") and save["uses"].startswith("actions/cache/save")
    assert restore["with"]["path"] == save["with"]["path"]
    # saved under the key restore computed before the build (__pycache__ would change a hash taken later)
    assert save["with"]["key"] == "${{ steps.warehouse.outputs.cache-primary-key }}"
    assert "requirements.txt" in restore["with"]["key"] and "pipelines/*.py" in restore["with"]["key"]
    assert "--fresh" not in build["run"]
    assert "--fresh" in check["run"] and "warehouse_full" in check["run"] and "pipelines.parity" in check["run"]
    assert "cache-matched-key" in check["if"] and "weekday == '7'" in check["if"]
    # the check runs before the state is saved and before deploy (which needs the whole build job)
    assert names.index("Restore warehouse and pipeline state") < names.index("Load (incremental) + dbt build")
    assert names.index("Weekly check, a rebuild from scratch gives the same warehouse") < names.index(
        "Save warehouse and pipeline state for tomorrow")
    assert wf["jobs"]["deploy"]["needs"] == "build"
    dispatch = wf.get("on", wf.get(True))["workflow_dispatch"]
    assert dispatch["inputs"]["full_check"]["type"] == "boolean"
