"""Governed arm on Snowflake: the one-SELECT check, the Snowflake path of the tool, governed-only
recording on a non-DuckDB target, pairing two runs, and the recording workflow."""
import json
from pathlib import Path

import pytest
import yaml

import semantic
from analyst import sql_guard
from semantic_eval import arms, cross_target
from semantic_eval import run as eval_run

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "record-eval-snowflake.yml"


@pytest.mark.parametrize("sql", [
    "select 1",
    "with t as (select 1 as x) select x from t",
    "select a from t union all select b from u",
    "SELECT DATE_TRUNC('month', ds) AS m, SUM(x) FROM analytics.f GROUP BY 1;",
])
def test_snowflake_check_lets_one_query_through(sql):
    assert sql_guard.check_snowflake_sql(sql) == sql.strip().rstrip(";").strip()


@pytest.mark.parametrize("sql, message", [
    ("drop table analytics.fct_mrr_daily", "only SELECT"),
    ("insert into t values (1)", "only SELECT"),
    ("select 1; drop table t", "one statement only"),
    ("", "empty query"),
])
def test_snowflake_check_refuses_everything_else(sql, message):
    with pytest.raises(sql_guard.UnsafeSQL, match=message):
        sql_guard.check_snowflake_sql(sql)


@pytest.fixture()
def on_snowflake(monkeypatch):
    ran = []
    monkeypatch.setenv("RIDGELINE_DBT_TARGET", "snowflake")
    monkeypatch.setattr(semantic, "explain", lambda *a, **k: "select ds, mrr from analytics.fct_mrr_daily")

    def run_compiled(sql):
        ran.append(sql)
        return ["metric_time__day", "mrr"], [["2026-11-09", 243419]] * 205
    monkeypatch.setattr(semantic, "run_compiled", run_compiled)
    return ran


def test_governed_tool_runs_the_compiled_query_on_snowflake_capped(on_snowflake):
    res = arms.query_governed_metric(["mrr"], ["metric_time__day"])
    assert on_snowflake == ["select ds, mrr from analytics.fct_mrr_daily"]
    assert res["columns"] == ["metric_time__day", "mrr"] and res["rows"][0] == ["2026-11-09", 243419]
    assert res["row_count"] == sql_guard.MAX_ROWS and res["truncated"]


def test_governed_tool_on_snowflake_never_runs_unsafe_sql(on_snowflake, monkeypatch):
    monkeypatch.setattr(semantic, "explain", lambda *a, **k: "select 1; drop table analytics.fct_mrr_daily")
    assert "one statement only" in arms.query_governed_metric(["mrr"])["error"]
    assert on_snowflake == []


class FakeClient:
    provider, model = "fake", "fake-1"


def _ask(question, arm, client):
    return {"text": '```json\n{"answer": 100.0, "unit": "usd", "definition": "d"}\n```', "turns": 2,
            "tool_calls": [], "model": "fake-1", "provider": "fake", "seconds": 0.1}


def test_governed_only_run_makes_no_raw_copy_and_records_the_target(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDGELINE_DBT_TARGET", "snowflake")
    monkeypatch.delenv("RIDGELINE_RAW_DUCKDB_PATH", raising=False)
    calls = []

    def prepare(only, raw=True):
        calls.append(raw)
        q = {"id": "q1", "category": "revenue", "question": "MRR now?", "type": "number", "trap": "none"}
        return [q], {"q1": 100.0}, "2026-11-09", "w.duckdb", None

    out = tmp_path / "sf.json"
    report = eval_run.run_api(["governed"], None, FakeClient(), out, ask=_ask, prepare=prepare)
    assert calls == [False] and report["remaining"] == 0
    assert "RIDGELINE_RAW_DUCKDB_PATH" not in __import__("os").environ
    saved = json.loads(out.read_text())
    assert saved["target"] == "snowflake" and saved["summary"]["arms"]["governed"]["correct"] == 1

    monkeypatch.setenv("RIDGELINE_DBT_TARGET", "duckdb")  # resuming the same file on another warehouse
    with pytest.raises(SystemExit, match="recorded on snowflake"):
        eval_run.run_api(["governed"], None, FakeClient(), out, ask=_ask, prepare=prepare)


def _run(target, answers, truths, as_of="2026-11-09"):
    results = [{"id": q, "arm": "governed", "answer": a, "truth": truths[q],
                "correct": cross_target._same_answer(a, truths[q])} for q, a in answers.items()]
    results.append({"id": "x", "arm": "raw", "answer": 1, "truth": 2, "correct": False})  # ignored
    return {"target": target, "model": "m", "as_of": as_of, "results": results}


def test_compare_runs_counts_right_answers_and_agreement():
    truths = {"a": 10.0, "b": "seo", "c": 0.5}
    sf = _run("snowflake", {"a": 10.0, "b": "SEO", "c": 0.4}, truths)
    dk = _run("duckdb", {"a": 10.0000000001, "b": "paid", "c": 0.4}, truths)
    report = cross_target.compare_runs(sf, dk)
    assert report["targets"] == ["snowflake", "duckdb"] and report["same_as_of"] and report["total"] == 3
    assert report["correct"] == {"snowflake": 2, "duckdb": 1}
    assert report["same_answer"] == 2 and report["truths_match"] == 3
    assert report["right_on_one_only"] == ["b"]
    text = cross_target.runs_markdown(report)
    assert "2 / 3 on snowflake, 1 / 3 on duckdb" in text and "Same answer on both: 2 / 3" in text


def test_compare_runs_cli_writes_the_report(tmp_path):
    truths = {"a": 1.0}
    left, right = tmp_path / "l.json", tmp_path / "r.json"
    left.write_text(json.dumps(_run("snowflake", {"a": 1.0}, truths)))
    right.write_text(json.dumps(_run("duckdb", {"a": 2.0}, truths)))
    assert cross_target.main(["runs", str(left), str(right), "--out", str(tmp_path / "o.json")]) == 0
    assert json.loads((tmp_path / "o.json").read_text())["right_on_one_only"] == ["a"]


def test_workflow_records_snowflake_first_then_duckdb_on_one_day():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = wf[True] if True in wf else wf["on"]
    assert set(on) == {"workflow_dispatch"} and wf["concurrency"]["group"] == "snowflake"
    names = [s.get("name", s.get("uses")) for s in wf["jobs"]["record"]["steps"]]
    assert names.index("dbt build on Snowflake") < names.index("Record governed arm on Snowflake") \
        < names.index("Load + dbt build (DuckDB)") < names.index("Record governed arm on DuckDB")
    steps = {s.get("name"): s for s in wf["jobs"]["record"]["steps"]}
    assert steps["Record governed arm on Snowflake"]["env"]["RIDGELINE_DBT_TARGET"] == "snowflake"
    for name in ("Record governed arm on Snowflake", "Record governed arm on DuckDB"):
        assert "--arms governed" in steps[name]["run"] and '--model "$MODEL"' in steps[name]["run"]
    assert '--as-of "$AS_OF"' in steps["Load + dbt build (DuckDB)"]["run"]
    with_key = [n for n, s in steps.items() if "GEMINI_API_KEY" in str(s.get("env", {}))]
    assert with_key == ["Check the secrets", "Record governed arm on Snowflake", "Record governed arm on DuckDB"]
