"""Raw-vs-governed eval: the raw arm can't reach modelled tables, scoring is right, a recorded run replays."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

from semantic_eval import arms
from semantic_eval.run import RESULTS, replay, score, summarize

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def warehouse(tmp_path, monkeypatch):
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("create schema raw_app_db")
        c.execute("create table raw_app_db.accounts as select range::varchar as account_id, "
                  "'x' as _dlt_load_id, 'y' as _dlt_id from range(3)")
        c.execute("create table raw_app_db._dlt_loads as select 1 as load_id")
        c.execute("create schema raw_app_db_staging")
        c.execute("create table raw_app_db_staging.accounts as select 1 as account_id")
        c.execute("create table main.fct_mrr_daily as select 100 as mrr")
    monkeypatch.setenv("RIDGELINE_DUCKDB_PATH", str(path))
    monkeypatch.delenv("RIDGELINE_RAW_DUCKDB_PATH", raising=False)
    arms.close()
    yield path
    arms.close()


def test_raw_copy_holds_only_loaded_tables_without_dlt_columns(warehouse, tmp_path):
    copy = arms.build_raw_copy(warehouse, tmp_path / "raw.duckdb")
    with duckdb.connect(str(copy), read_only=True) as c:
        tables = c.execute("select schema_name || '.' || table_name from duckdb_tables()").fetchall()
        cols = c.execute("select column_name from information_schema.columns").fetchall()
    assert tables == [("raw_app_db.accounts",)]
    assert cols == [("account_id",)]


def test_raw_arm_lists_and_queries_raw_tables(warehouse):
    assert arms.list_raw_tables() == {"tables": [{"table": "raw_app_db.accounts", "columns": ["account_id VARCHAR"]}]}
    assert arms.run_raw_sql("select count(*) from raw_app_db.accounts")["rows"] == [[3]]


@pytest.mark.parametrize("sql", [
    "select * from fct_mrr_daily",
    "select * from main.fct_mrr_daily",
    "select * from query('select * from fct_mrr_daily')",
    "select * from raw_app_db_staging.accounts",
    "select * from raw_app_db._dlt_loads",
])
def test_raw_arm_cannot_reach_anything_else(warehouse, sql):
    assert "error" in arms.run_raw_sql(sql)


def test_raw_arm_is_read_only(warehouse):
    assert "only SELECT" in arms.run_raw_sql("drop table raw_app_db.accounts")["error"]


def test_each_arm_has_its_own_tools_and_answer_format():
    assert [f.__name__ for f in arms.TOOLS["raw"]] == ["list_raw_tables", "run_raw_sql"]
    assert [f.__name__ for f in arms.TOOLS["governed"]] == ["list_governed_metrics", "query_governed_metric"]
    for arm in arms.ARMS:
        assert '"answer"' in arms.SYSTEM[arm] and "never estimate" in arms.SYSTEM[arm]
    assert "query_metric" not in arms.SYSTEM["raw"] and "run_raw_sql" not in arms.SYSTEM["governed"]


def _rec(qid, arm, answer, truth, qtype="number", category="revenue", **kw):
    return {"id": qid, "arm": arm, "category": category, "type": qtype, "answer": answer, "truth": truth,
            "seconds": 10.0, "tool_calls": ["a", "b"], "cost_usd": 0.05, **kw}


@pytest.mark.parametrize("record, expected", [
    (_rec("a", "raw", 243419, 243419.0), True),
    (_rec("a", "raw", 7302570, 243419.0), False),  # summed daily MRR
    (_rec("a", "raw", -1200.0, 1200.0, absolute=True), True),
    (_rec("a", "raw", -1200.0, 1200.0), False),
    (_rec("a", "raw", "16.4%", 0.1638, qtype="ratio"), True),
    (_rec("a", "raw", "seo", "seo", qtype="text"), True),
    (_rec("a", "raw", None, 5.0), False),
    (_rec("a", "raw", "June 2026", "2026-06", qtype="text"), True),
    (_rec("a", "raw", "2026-06", "2026-06", qtype="text"), True),
    (_rec("a", "raw", "July 2026", "2026-06", qtype="text"), False),
    (_rec("a", "raw", "measurement_accuracy (3,028 tickets)", "measurement_accuracy", qtype="text"), True),
    (_rec("a", "raw", "Measurement report accuracy problems", "measurement_accuracy", qtype="text"), False),
])
def test_score(record, expected):
    assert score(record) is expected


def test_summarize_counts_each_arm_and_the_differences():
    recs = [_rec("a", "raw", 1, 1), _rec("a", "governed", 1, 1),
            _rec("b", "raw", 9, 1, category="funnel"), _rec("b", "governed", 1, 1, category="funnel"),
            _rec("c", "raw", 1, 1, category="funnel"), _rec("c", "governed", 9, 1, category="funnel")]
    for r in recs:
        r["correct"] = score(r)
    s = summarize(recs)
    assert s["arms"]["raw"]["correct"] == 2 and s["arms"]["governed"]["correct"] == 2
    assert s["arms"]["raw"]["by_category"] == {"funnel": [1, 2], "revenue": [1, 1]}
    assert s["arms"]["raw"]["cost_usd"] == 0.15 and s["arms"]["raw"]["median_tool_calls"] == 2.0
    assert s["only_governed_right"] == ["b"] and s["only_raw_right"] == ["c"]


RECORDED = sorted(RESULTS.glob("raw-vs-governed-*.json"))
CLAUDE_CODE_RUN = RESULTS / "raw-vs-governed-2026-11-03.json"


@pytest.mark.parametrize("path", RECORDED, ids=[p.stem for p in RECORDED])
def test_recorded_run_replays_to_the_same_scores(path):
    """Every committed run, complete or still being recorded on a free quota, rescores to what it stored."""
    stored = json.loads(path.read_text(encoding="utf-8"))
    rescored = replay(path)
    assert rescored["summary"] == stored["summary"]
    assert [r["correct"] for r in rescored["results"]] == [r["correct"] for r in stored["results"]]
    assert len({(r["id"], r["arm"]) for r in stored["results"]}) == len(stored["results"])


@pytest.mark.skipif(not CLAUDE_CODE_RUN.exists(), reason="no recorded run")
def test_claude_code_run_is_complete():
    stored = json.loads(CLAUDE_CODE_RUN.read_text(encoding="utf-8"))
    assert len(stored["results"]) == 50
    assert {(r["id"], r["arm"]) for r in stored["results"]} == {
        (q, a) for q in {r["id"] for r in stored["results"]} for a in arms.ARMS}


@pytest.mark.skipif(not RECORDED, reason="no recorded run")
def test_replay_cli_needs_no_warehouse(tmp_path):
    import subprocess

    env = {"PATH": "", "PYTHONPATH": str(ROOT), "RIDGELINE_DUCKDB_PATH": str(tmp_path / "missing.duckdb")}
    out = subprocess.run([sys.executable, "-m", "semantic_eval.run", "--replay", str(RECORDED[-1])],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    assert out.splitlines()[1].split() == ["arm", "correct", "cost", "median", "s", "tool", "calls"]
