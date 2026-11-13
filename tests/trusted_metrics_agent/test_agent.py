"""The agent reaches the metrics only through the MCP server, the check stops ungrounded answers, and the
30-question eval scores and replays."""
import json
from collections import Counter

import pytest

from analyst.llm import Reply, ToolCall
from trusted_metrics_agent import agent_eval
from trusted_metrics_agent.agent import McpTools, ask, check, plain_schema
from trusted_metrics_agent.agent_baseline import KeywordClient, plan
from trusted_metrics_agent.metrics import Catalog

SRC = "trusted_metrics_agent/metrics.yml#"


def block(**kw) -> str:
    body = {"answer": None, "unit": "text", "sources": [], "declined": False, "refused": False, "note": ""} | kw
    return f"Here you go.\n```json\n{json.dumps(body)}\n```"


class Scripted:
    """Plays the model: makes the given tool calls on turn 1, then replies with `final(results)`."""
    provider, model = "test", "scripted"

    def __init__(self, calls, final):
        self.calls, self.final, self.seen_tools = calls, final, None

    def complete(self, system, messages, tools):
        self.seen_tools = tools
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not results:
            return Reply("", [ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(self.calls)], stop="tool_use")
        return Reply(self.final(results), [])


@pytest.fixture(scope="module")
def manager(db):
    with McpTools("people_manager", db) as tools:
        yield tools


# ---- the tools are the server's

def test_tools_come_from_the_server_with_no_role_input(manager):
    assert sorted(manager.specs) == ["describe_metric", "list_metrics", "query_metric"]
    q = manager.specs["query_metric"]["parameters"]
    assert q["required"] == ["metric", "start_month"]
    assert set(q["properties"]) == {"metric", "start_month", "end_month", "group_by", "filters"}
    assert "role" not in json.dumps(q)
    assert "withheld" in manager.specs["query_metric"]["description"]


def test_plain_schema_flattens_optional_inputs():
    s = {"type": "object", "title": "x", "required": ["a"], "properties": {
        "a": {"type": "string", "title": "A"},
        "b": {"anyOf": [{"type": "array", "items": {"type": "string", "title": "i"}}, {"type": "null"}],
              "default": None},
        "c": {"anyOf": [{"type": "object", "additionalProperties": {"type": "string"}}, {"type": "null"}]}}}
    assert plain_schema(s) == {"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string"}, "b": {"type": "array", "items": {"type": "string"}}, "c": {"type": "object"}}}


def test_ask_goes_through_the_server_and_the_model_sees_its_specs(manager):
    client = Scripted(
        [("query_metric", {"metric": "attrition_rate_12m", "start_month": "2026-09",
                           "filters": {"department": "Sales"}})],
        lambda r: block(answer=r[0]["rows"][0]["value"], unit="share", sources=[r[0]["source"]]))
    a = ask("Attrition in Sales, September 2026?", client, manager)
    assert [t["name"] for t in client.seen_tools] == list(manager.specs)
    assert a.role == "people_manager" and a.tool_calls[0]["name"] == "query_metric"
    assert a.delivered == {"answer": 0.2097, "unit": "share", "sources": [SRC + "attrition_rate_12m"],
                           "declined": False, "refused": False, "note": ""}


def test_the_role_holds_whatever_the_model_asks_for(manager):
    leak = Scripted([("query_metric", {"metric": "payroll_cost", "start_month": "2026-09"}),
                     ("query_metric", {"metric": "avg_base_salary", "start_month": "2026-09", "role": "hr_partner"})],
                    lambda r: block(answer=2420797.03, unit="usd", sources=[SRC + "payroll_cost"]))
    a = ask("Payroll cost in September 2026?", leak, manager)
    assert "cannot see payroll_cost" in a.tool_results[0]["declined"]
    assert "cannot see avg_base_salary" in a.tool_results[1]["declined"]  # a role argument is ignored
    assert a.delivered is None and "no query returned it" in a.held_back
    assert "2420797" not in json.dumps(a.tool_results)


# ---- the check

def _result(metric="headcount", value=335):
    return {"source": SRC + metric, "rows": [{"month": "2026-09", "value": value}], "unit": "people"}


def test_check_delivers_only_grounded_answers():
    rs = [_result(), _result("attrition_rate_12m", 0.1909)]
    assert check(block(answer=335, sources=[SRC + "headcount"]), rs).delivered["answer"] == 335
    assert check(block(answer="19.09%", sources=[SRC + "attrition_rate_12m"]), rs).delivered  # share as percent
    assert "not in any tool result: [336.0]" in check(block(answer=336, sources=[SRC + "headcount"]), rs).held_back
    assert "no definition cited" in check(block(answer=335), rs).held_back
    assert "no query returned it" in check(block(answer=335, sources=[SRC + "hires"]), rs).held_back
    assert check("335 people", rs).held_back == "no answer block"


def test_a_declined_result_is_not_a_source():
    declined = [{"declined": "role all_staff cannot see payroll_cost", "role": "all_staff"}]
    c = check(block(answer=1, sources=[SRC + "payroll_cost"]), declined)
    assert c.delivered is None and c.held_back
    assert check(block(declined=True), declined).declined
    assert check(block(refused=True), []).refused


# ---- the eval

def test_questions_are_30_and_each_answerable_one_is_open_to_its_role():
    qs = agent_eval.load_questions()
    assert len(qs) == 30 and len({q["id"] for q in qs}) == 30
    assert Counter(q["type"] for q in qs) == {"number": 16, "text": 2, "decline": 6, "refuse": 6}
    roles = Catalog.load().roles
    for q in qs:
        if q["type"] in ("number", "text"):
            t = q["truth"]
            assert t["metric"] in roles[q["role"]]["metrics"], q["id"]
            assert set(t.get("filters", {})) | {t.get("group_by")} - {None} <= set(roles[q["role"]]["group_by"])


def test_truths_come_from_the_governed_metrics(db):
    t = agent_eval.truths(db, agent_eval.load_questions())
    assert t["headcount_sep"] == 335 and t["attrition_sales_sep"] == 0.2097
    assert t["highest_attrition_dept_sep"] == "Field Operations" and t["payroll_sep"] == 2420797.03
    assert t["refuse_forecast"] is None


def test_same_value_is_exact_but_takes_a_share_as_a_percent():
    assert agent_eval.same_value(0.2097, 0.2097, "share") and agent_eval.same_value("20.97%", 0.2097, "share")
    assert agent_eval.same_value("2,420,797.03", 2420797.03, "usd")
    assert not agent_eval.same_value(0.21, 0.2097, "share") and not agent_eval.same_value(True, 1, "people")


def test_baseline_run_scores_and_its_recording_replays(db):
    report = agent_eval.run(KeywordClient(), db)
    s = report["summary"]
    assert s["answerable"] == {"total": 18, "right": 15, "wrong_delivered": 3, "held_back": 0, "declined": 0,
                               "refused": 0}
    assert s["not_for_role"] == {"total": 6, "right": 5, "refused": 1, "held_back": 0, "leaked": 0}
    assert s["out_of_scope"] == {"total": 6, "right": 6, "declined": 0, "held_back": 0, "leaked": 0}
    saved = agent_eval.replay(agent_eval.RESULTS / "keyword-baseline.json")
    assert saved["summary"] == s
    assert agent_eval.verify_tools(saved, db) == []


def test_baseline_plans():
    assert plan("How many people left Field Operations in August 2026?") == {
        "metric": "terminations", "start_month": "2026-08", "filters": {"department": "Field Operations"}}
    assert plan("Forecast our headcount for the end of 2027.") is None
    assert plan("What was the average base salary for level 3 at the end of September 2026?")["filters"] == {
        "job_level": "3"}


def test_the_gemini_recording_is_complete_and_holds_the_quoted_scores(db):
    """The README quotes this run; it replays with no key and its tool results match a fresh server."""
    saved = agent_eval.replay(agent_eval.RESULTS / "gemini-3.5-flash-lite.json")
    assert (saved["provider"], saved["model"], saved["as_of"]) == ("gemini", "gemini-3.5-flash-lite", "2026-09-30")
    assert [r["id"] for r in saved["results"]] == [q["id"] for q in agent_eval.load_questions()]
    s = saved["summary"]
    assert s["answerable"]["right"] == 18 and s["not_for_role"]["right"] == 6
    assert s["out_of_scope"] == {"total": 6, "right": 5, "declined": 1, "held_back": 0, "leaked": 0}
    assert s["tool_calls"] == 53
    assert agent_eval.verify_tools(saved, db) == []
