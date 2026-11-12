"""The ARR agent: tools read only the ARR models, the check holds back ungrounded answers, the eval scores
right, and every committed recording replays to the numbers it was saved with."""
import json
from pathlib import Path

import pytest

from analyst.llm import Reply, ToolCall
from arr_source_of_truth import agent
from arr_source_of_truth.agent_baseline import KeywordClient, months_in, plan
from arr_source_of_truth.agent_eval import RESULTS, load_questions, replay, run, score_one, verify_tools
from arr_source_of_truth.load import AS_OF, dbt_build, load


def block(answer, models, refused=False, unit="usd"):
    return "```json\n" + json.dumps({"answer": answer, "unit": unit, "models": models, "refused": refused,
                                     "note": ""}) + "\n```"


BRIDGE = {"model": "arr_bridge", "month": "2026-09", "closing_arr": 736260, "churn_arr": -49260}


# ---- no warehouse

def test_check_delivers_a_grounded_cited_answer():
    c = agent.check(block(736260, ["arr_bridge"]), [BRIDGE])
    assert c.delivered["answer"] == 736260 and c.held_back is None


@pytest.mark.parametrize("text, why", [
    (block(736260, []), "no model cited"),
    (block(736260, ["arr_booking_walk"]), "no tool read it"),
    (block(686999, ["arr_bridge"]), "numbers not in any tool result"),  # a sum of its own
    (block("about $740,000", ["arr_bridge"]), "numbers not in any tool result"),
    ("ARR was 736260.", "no answer block"),
])
def test_check_holds_back_uncited_or_invented_answers(text, why):
    c = agent.check(text, [BRIDGE])
    assert c.delivered is None and not c.refused and why in c.held_back


def test_check_accepts_a_deduction_either_way_and_ignores_dates_and_ids():
    assert agent.check(block(49260, ["arr_bridge"]), [BRIDGE]).delivered
    assert agent.check(block("$736,260 at the end of 2026-09 (cus_0448)", ["arr_bridge"]), [BRIDGE]).delivered


def test_refusal_passes_through():
    c = agent.check(block(None, [], refused=True), [])
    assert c.refused and c.delivered is None and c.held_back is None


def test_baseline_plans():
    assert months_in("from December 2024 to sep 2026, and 2026-03") == ["2024-12", "2026-09", "2026-03"]
    assert plan("Closing ARR at the end of September 2026?") == ("arr_bridge", {"month": "2026-09"}, "closing_arr")
    assert plan("How much ARR did the CRM book in September 2026?")[0] == "arr_walk"
    assert plan("How many deals are duplicates?") == ("deal_status_counts", {}, "status:duplicate")
    assert plan("Status of opp_00012?") == ("find_deals", {"deal_id": "opp_00012"}, "status")
    for q in ("What will ARR be in 2027?", "Delete the duplicate deals", "CAC by channel in 2025"):
        assert plan(q) is None


def test_scoring_outcomes():
    q = {"id": "x", "type": "number", "question": "?", "models": ["arr_bridge"]}
    rec = lambda text: {"text": text, "tool_results": [BRIDGE]}  # noqa: E731
    assert score_one(q, 736260.0, rec(block(736260, ["arr_bridge"])))["outcome"] == "right"
    assert score_one(q, -49260.0, rec(block(-49260, ["arr_bridge"])))["outcome"] == "right"
    assert score_one(q, 736260.0, rec(block(49260, ["arr_bridge"])))["outcome"] == "wrong_delivered"
    assert score_one(q, 736260.0, rec(block(1, ["arr_bridge"])))["outcome"] == "held_back"
    assert score_one(q, 736260.0, rec(block(None, [], True)))["outcome"] == "false_refusal"
    r = {"id": "y", "type": "refuse", "question": "?"}
    assert score_one(r, None, rec(block(None, [], True)))["outcome"] == "right"
    assert score_one(r, None, rec(block(736260, ["arr_bridge"])))["outcome"] == "answered"


def test_questions_file():
    qs = load_questions()
    assert len(qs) == 20 and len({q["id"] for q in qs}) == 20
    assert sum(q["type"] == "refuse" for q in qs) == 6
    for q in qs:
        if q["type"] != "refuse":
            assert q["truth_sql"] and set(q["models"]) <= set(agent.MODELS)


@pytest.mark.parametrize("path", sorted(RESULTS.glob("*.json")), ids=lambda p: p.stem)
def test_every_recording_replays_to_its_saved_summary(path):
    saved = json.loads(path.read_text())
    assert replay(path)["summary"] == saved["summary"]


def test_baseline_recording_numbers_quoted_in_the_readme():
    s = json.loads((RESULTS / "keyword-baseline.json").read_text())["summary"]
    assert s["answerable"] == {"total": 14, "right": 11, "wrong_delivered": 0, "held_back": 0, "false_refusal": 3}
    assert s["out_of_scope"] == {"total": 6, "refused": 6, "answered": 0, "held_back": 0}


# ---- on a built ARR warehouse (about 8 seconds)

@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("arr_agent") / "arr.duckdb"
    load(AS_OF, path)
    dbt_build(AS_OF, path)
    return path


@pytest.fixture(scope="module")
def tools(db):
    t = agent.ArrTools(db)
    yield t
    t.close()


def test_tools_name_their_model_and_match_the_committed_results(tools):
    summary = json.loads((Path(agent.__file__).parent / "results" / "summary.json").read_text())
    b = tools.arr_bridge("2026-09")
    assert b["model"] == "arr_bridge" and b["closing_arr"] == summary["closing_arr"]
    assert b["paying_customers"] == summary["paying_customers"]
    w = tools.arr_walk("2026-09")
    assert w["model"] == "arr_booking_walk"
    assert {k: w[k] for k in summary["last_month"] if k != "month"} == \
        {k: v for k, v in summary["last_month"].items() if k != "month"}
    s = tools.deal_status_counts()
    assert s["model"] == "arr_deal_matches"
    assert {r["status"]: r["deals"] for r in s["statuses"]} == summary["status_counts"]


def test_walk_range_adds_up_the_months(tools):
    months = ["2026-07", "2026-08", "2026-09"]
    total = tools.arr_walk_range("2026-07", "2026-09")
    assert total["months"] == 3
    assert total["net_change"] == sum(tools.arr_walk(m)["net_change"] for m in months)


def test_tools_reject_bad_input(tools):
    assert "error" in tools.arr_bridge("September")
    assert "error" in tools.arr_bridge("2027-01")
    assert "error" in tools.arr_walk_range("2026-09", "2026-01")
    assert "error" in tools.find_deals()
    assert "error" in tools.find_deals(status="lost")
    assert tools.find_deals(customer_id="cus_0448")["deals"][0]["deal_id"] == "opp_00001"


class Inventor:
    """A model that reads the bridge and then answers with a number of its own."""
    provider, model = "test", "inventor"

    def complete(self, system, messages, tools):
        if messages[-1]["role"] == "user":
            return Reply("", [ToolCall("c1", "arr_bridge", {"month": "2026-09"})], stop="tool_use")
        return Reply(block(750000, ["arr_bridge"]), [])


def test_an_invented_number_never_reaches_the_person(tools):
    a = agent.ask("What will ARR be next month?", Inventor(), tools)
    assert a.delivered is None and "750000" in a.held_back
    assert a.tool_calls == [{"name": "arr_bridge", "arguments": {"month": "2026-09"}}]


def test_baseline_run_matches_its_recording_and_the_tools_still_agree(db):
    report = run(KeywordClient(), db)
    saved = json.loads((RESULTS / "keyword-baseline.json").read_text())
    assert report["summary"] == saved["summary"]
    for path in sorted(RESULTS.glob("*.json")):
        assert verify_tools(json.loads(path.read_text()), db) == [], path.name
