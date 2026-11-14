"""The metric registry's MCP server, the analyst's answer check and the golden-question suite.

Builds the vehicle-sales warehouse once and copies it: the in-process tool tests use one file and the MCP
server subprocesses the others (truths are read from the replay copy while no server holds it), because
DuckDB lets only one process open a file for writing."""
import json
import shutil

import pytest

from metric_registry import agent
from metric_registry import agent_eval as ev
from metric_registry.agent_baseline import KeywordClient, dates, plan
from metric_registry.load import dbt_build, load
from metric_registry.tools import SemanticTools


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("metric_agent") / "metric_registry.duckdb"
    load(path)
    dbt_build(path)
    copies = []
    for name in ("served", "replayed"):  # same file name: MetricFlow's SQL names the catalog after it
        copy = path.parent / name / path.name
        copy.parent.mkdir()
        shutil.copy(path, copy)
        copies.append(copy)
    server_copy, replay_copy = copies
    return path, server_copy, replay_copy


@pytest.fixture(scope="module")
def tools(built):
    return SemanticTools(built[0])


@pytest.fixture(scope="module")
def mcp(built):
    with agent.McpTools(built[1]) as t:
        yield t


@pytest.fixture(scope="module")
def baseline(built, mcp):
    questions = ev.load_questions()
    truth = ev.truths(built[2], questions)
    answers = [agent.ask(q["question"], KeywordClient(), mcp).to_dict() for q in questions]
    return [ev.score_one(q, truth[q["id"]], a) for q, a in zip(questions, answers, strict=True)], answers


# --- the tools ---------------------------------------------------------------------------------


def test_list_metrics_shows_the_registry_and_the_filter_values(tools):
    out = tools.list_metrics()
    assert len(out["metrics"]) == 11
    assert {m["metric"] for m in out["metrics"]} == set(tools.reg["metrics"])
    assert out["dimension_values"]["vehicle__segment"] == ["ev", "sedan", "suv", "truck"]
    assert out["dimension_values"]["sale__is_quarter_end"] == [False, True]
    assert out["dates"] == {"first": "2025-01-01", "last": "2026-06-30"}


def test_explain_metric_returns_the_registry_entry(tools):
    out = tools.explain_metric("incentive_per_unit")
    assert out["computed_as"] == "incentive_spend / units_sold"
    assert out["version"] == 1 and out["owner"] == "Incentives team"
    assert out["source"] == "metric_registry/registry.yml#incentive_per_unit"
    assert "Incentive spend" in out["glossary"]
    assert "error" in tools.explain_metric("dealer_margin")


def test_query_returns_values_and_the_sql_that_made_them(tools):
    out = tools.query_metrics(["units_sold", "incentive_per_unit"], ["metric_time__quarter"],
                              {"vehicle__segment": "ev"}, "2026-01-01", "2026-06-30")
    assert [r["metric_time__quarter"] for r in out["rows"]] == ["2026-Q1", "2026-Q2"]
    assert out["metrics"]["units_sold"] == {"version": 1, "source": "metric_registry/registry.yml#units_sold"}
    sql = out["sql"]
    assert sql.lstrip().startswith("--") and "SELECT" in sql
    assert '"fct_sales"' in sql and '"dim_vehicle"' in sql and "'ev'" in sql and "2026-06-30" in sql
    total = tools.query_metrics(["units_sold"], filters={"vehicle__segment": "ev"},
                                start_date="2026-01-01", end_date="2026-06-30")
    assert total["rows"][0]["units_sold"] == sum(r["units_sold"] for r in out["rows"])


@pytest.mark.parametrize("args, message", [
    ({"metrics": []}, "at least one metric"),
    ({"metrics": ["dealer_margin"]}, "unknown metric"),
    ({"metrics": ["program_spend"], "group_by": ["sale__finance_type"]}, "cannot group"),
    ({"metrics": ["units_sold"], "filters": {"vehicle__segment": "van"}}, "has no value"),
    ({"metrics": ["units_sold"], "filters": {"vehicle__segment": "ev'; drop table fct_sales; --"}}, "has no value"),
    ({"metrics": ["units_sold"], "filters": {"program__program_type": "loyalty"}}, "cannot filter"),
    ({"metrics": ["units_sold"], "start_date": "2026-02-30"}, "no such day"),
    ({"metrics": ["units_sold"], "end_date": "June 2026"}, "YYYY-MM-DD"),
])
def test_query_rejects_what_the_registry_does_not_hold(tools, args, message):
    assert message in tools.query_metrics(**args)["error"]


def test_boolean_filters_take_true_as_text(tools):
    as_text = tools.query_metrics(["units_sold"], filters={"sale__is_quarter_end": "true"})
    as_bool = tools.query_metrics(["units_sold"], filters={"sale__is_quarter_end": True})
    assert as_text["rows"] == as_bool["rows"] and "sale__is_quarter_end = true" in as_text["sql"]


# --- the MCP server ----------------------------------------------------------------------------


def test_server_lists_three_read_only_tools(mcp):
    assert sorted(mcp.specs) == ["explain_metric", "list_metrics", "query_metrics"]
    assert mcp.specs["query_metrics"]["parameters"]["required"] == ["metrics"]


def test_server_answers_like_the_tools_in_process(mcp, tools):
    args = {"metrics": ["revenue"], "filters": {"dealer__region": "west"}}
    assert mcp.call("query_metrics", args) == json.loads(json.dumps(tools.query_metrics(**args)))
    assert "error" in mcp.call("run_sql", {"sql": "select 1"})


# --- the check ---------------------------------------------------------------------------------


def _reply(answer, metrics, refused=False):
    return "```json\n" + json.dumps({"answer": answer, "unit": "usd", "metrics": metrics, "refused": refused,
                                     "note": ""}) + "\n```"


RESULT = {"metrics": {"incentive_per_unit": {"version": 1, "source": "x"}}, "rows": [
    {"vehicle__segment": "ev", "incentive_per_unit": 6434.2034}, {"vehicle__segment": "suv",
                                                                  "incentive_per_unit": 1436.0},
], "sql": "SELECT 1234567 FROM fct_sales"}


def test_check_delivers_a_cited_tool_value_with_its_lineage():
    c = agent.check(_reply(6434.2034, ["incentive_per_unit"]), [RESULT])
    assert c.delivered["answer"] == 6434.2034
    assert c.delivered["lineage"] == [{"metrics": ["incentive_per_unit"], "sql": RESULT["sql"]}]
    assert agent.check(_reply("$6,434", ["incentive_per_unit"]), [RESULT]).delivered is not None


@pytest.mark.parametrize("answer, metrics, why", [
    (6500, ["incentive_per_unit"], "numbers not in any tool result"),
    (1234567, ["incentive_per_unit"], "numbers not in any tool result"),  # a number from the SQL is not a value
    (6434.2034, ["incentive_spend"], "but no query returned it"),
    (6434.2034, [], "no metric cited"),
])
def test_check_holds_back_unsupported_answers(answer, metrics, why):
    c = agent.check(_reply(answer, metrics), [RESULT])
    assert c.delivered is None and why in c.held_back


def test_check_takes_a_share_as_a_percent_and_a_refusal_as_a_refusal():
    share = {"metrics": {"incentive_penetration": {}}, "rows": [{"incentive_penetration": 0.7012}], "sql": ""}
    assert agent.check(_reply("70.12%", ["incentive_penetration"]), [share]).delivered is not None
    c = agent.check(_reply(None, [], refused=True), [])
    assert c.refused and c.delivered is None
    assert agent.check("I think about 6,000.", [RESULT]).held_back == "no answer block"


# --- the golden questions ----------------------------------------------------------------------


def test_golden_questions_are_well_formed(tools):
    qs = ev.load_questions()
    assert len(qs) == 20 and len({q["id"] for q in qs}) == 20
    assert sum(q["type"] == "refuse" for q in qs) == 4
    for q in qs:
        if q["type"] != "refuse":
            assert q["metric"] in tools.reg["metrics"] and q["tables"] and "truth_sql" in q


def test_scoring_needs_the_right_value_metric_and_lineage():
    q = {"id": "x", "type": "number", "question": "", "metric": "incentive_per_unit",
         "tables": ["fct_sales", "dim_vehicle"], "sql_has": ["vehicle__segment"]}
    good = {"metrics": {"incentive_per_unit": {}}, "rows": [{"incentive_per_unit": 6434.2034}],
            "sql": 'FROM "fct_sales" JOIN "dim_vehicle" WHERE vehicle__segment = \'ev\''}
    rec = {"text": _reply(6434.2034, ["incentive_per_unit"]), "tool_results": [good]}
    assert ev.score_one(q, 6434.20339, rec)["outcome"] == "right"
    assert ev.score_one(q, 6000.0, rec)["outcome"] == "wrong_delivered"
    no_dim = {**good, "sql": 'FROM "fct_sales" JOIN "dim_vehicle"'}
    s = ev.score_one(q, 6434.20339, {**rec, "tool_results": [no_dim]})
    assert s["outcome"] == "wrong_delivered" and "vehicle__segment" in s["why"]


def test_every_truth_matches_what_metricflow_serves(built, tools):
    """The truths come from SQL on the dbt tables; each one equals the governed metric's MetricFlow value
    for the same slice, so the golden answers and the semantic layer agree."""
    qs = [q for q in ev.load_questions() if q["type"] != "refuse"]
    truth = ev.truths(built[2], qs)
    for q in qs:
        args = plan(q["question"]) or {}
        args["metrics"] = [q["metric"]]
        row = tools.query_metrics(**args)["rows"]
        assert len(row) == 1, q["id"]
        assert ev.same_value(row[0][q["metric"]], truth[q["id"]], q["type"]), q["id"]


def test_baseline_scores_as_committed(baseline):
    scored, _ = baseline
    committed = ev.replay(ev.RESULTS / "keyword-baseline.json")
    assert ev.summarize(scored) == committed["summary"]
    assert committed["summary"]["passed"] == 17
    assert {s["id"] for s in scored if not s["passed"]} == {"ev_incentive_per_unit", "share_of_msrp_total",
                                                           "msrp_value_2025"}


@pytest.mark.parametrize("path", sorted(ev.RESULTS.glob("*.json")), ids=lambda p: p.stem)
def test_recordings_replay_with_no_key(path, built):
    report = ev.replay(path)
    saved = json.loads(path.read_text())
    assert report["summary"] == saved["summary"]
    assert ev.verify_tools(report, built[2]) == []


def test_baseline_reads_periods():
    assert dates("what was incentive spend in q1 2026 ") == ("2026-01-01", "2026-03-31")
    assert dates("sold in june 2026 ") == ("2026-06-01", "2026-06-30")
    assert dates("sold in 2025 ") == ("2025-01-01", "2025-12-31")
    assert plan("How many vehicles will we sell next quarter?") is None


def test_recorded_gemini_run_holds_the_quoted_scores():
    report = ev.replay(ev.RESULTS / "gemini-3.5-flash-lite.json")
    s = report["summary"]
    assert (s["passed"], s["answerable"]["wrong_delivered"], s["out_of_scope"]["refused"]) == (20, 0, 4)
    assert s["answerable"]["with_lineage"] == 16


def test_electric_vehicles_may_be_cut_by_segment_or_flag():
    q = next(q for q in ev.load_questions() if q["id"] == "ev_incentive_per_unit")
    for sql in ('"fct_sales" "dim_vehicle" vehicle__segment', '"fct_sales" "dim_vehicle" vehicle__is_electric'):
        assert ev.lineage_ok(q, {"lineage": [{"metrics": ["incentive_per_unit"], "sql": sql}]})[0]
    no_cut = {"lineage": [{"metrics": ["incentive_per_unit"], "sql": '"fct_sales" "dim_vehicle"'}]}
    assert not ev.lineage_ok(q, no_cut)[0]
