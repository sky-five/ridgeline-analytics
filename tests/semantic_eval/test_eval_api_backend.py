"""The API backend of the raw-vs-governed eval: resumable recording, --limit, errors retried, replayable."""
import json

import pytest

from semantic_eval import run as eval_run

QUESTIONS = [
    {"id": "q1", "category": "revenue", "question": "MRR now?", "type": "number", "trap": "none"},
    {"id": "q2", "category": "funnel", "question": "Top channel?", "type": "text", "trap": "none"},
]
TRUTHS = {"q1": 100.0, "q2": "seo"}


class FakeClient:
    provider, model = "fake", "fake-1"


def prepare(only):
    return QUESTIONS, TRUTHS, "2026-11-01", "w.duckdb", "raw.duckdb"


def answering(fail=()):
    asked = []

    def ask(question, arm, client):
        asked.append((question, arm))
        if (question, arm) in fail:
            raise RuntimeError("429 quota")
        q = next(q for q in QUESTIONS if q["question"] == question)
        value = json.dumps(TRUTHS[q["id"]]) if arm == "governed" else "null"
        return {"text": f'```json\n{{"answer": {value}, "unit": "usd", "definition": "d"}}\n```', "turns": 2,
                "tool_calls": [], "model": "fake-1", "provider": "fake", "seconds": 0.1}
    return ask, asked


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RIDGELINE_DUCKDB_PATH", "x")
    monkeypatch.setenv("RIDGELINE_RAW_DUCKDB_PATH", "y")


def test_limit_then_resume_records_each_answer_once(tmp_path):
    out = tmp_path / "run.json"
    ask, asked = answering()
    first = eval_run.run_api(["raw", "governed"], None, FakeClient(), out, limit=3, ask=ask, prepare=prepare)
    assert len(asked) == 3 and first["remaining"] == 1
    ask, asked = answering()
    second = eval_run.run_api(["raw", "governed"], None, FakeClient(), out, ask=ask, prepare=prepare)
    assert asked == [("Top channel?", "governed")] and second["remaining"] == 0
    saved = json.loads(out.read_text())
    assert saved["provider"] == "fake" and saved["model"] == "fake-1" and saved["as_of"] == "2026-11-01"
    assert saved["summary"]["arms"]["governed"]["correct"] == 2 and saved["summary"]["arms"]["raw"]["correct"] == 0


def test_provider_failure_keeps_earlier_answers_and_resumes_there(tmp_path):
    out = tmp_path / "run.json"
    ask, _ = answering(fail={("MRR now?", "governed")})
    report = eval_run.run_api(["raw", "governed"], None, FakeClient(), out, ask=ask, prepare=prepare)
    assert [(r["id"], r["arm"]) for r in report["results"]] == [("q1", "raw")] and report["remaining"] == 3
    ask, asked = answering()
    eval_run.run_api(["raw", "governed"], None, FakeClient(), out, ask=ask, prepare=prepare)
    assert asked[0] == ("MRR now?", "governed") and len(asked) == 3


def test_answers_that_ended_in_an_error_are_asked_again():
    done = [{"id": "q1", "arm": "raw", "error": "turn_cap"}, {"id": "q1", "arm": "governed"}]
    todo = eval_run.pending(QUESTIONS, ["raw", "governed"], done)
    assert [(q["id"], arm) for q, arm in todo] == [("q1", "raw"), ("q2", "raw"), ("q2", "governed")]


def test_a_file_from_another_as_of_date_is_not_mixed_in(tmp_path):
    out = tmp_path / "run.json"
    out.write_text(json.dumps({"as_of": "2026-10-01", "results": []}))
    with pytest.raises(SystemExit, match="as of 2026-10-01"):
        eval_run.run_api(["raw"], None, FakeClient(), out, ask=answering()[0], prepare=prepare)


def test_a_recorded_api_run_replays_to_the_same_scores(tmp_path):
    out = tmp_path / "run.json"
    eval_run.run_api(["raw", "governed"], None, FakeClient(), out, ask=answering()[0], prepare=prepare)
    replayed = eval_run.replay(out)
    assert replayed["summary"] == json.loads(out.read_text())["summary"]


def test_ask_api_reports_tokens_provider_and_cap_errors():
    from analyst.llm import Reply, ToolCall

    class Looping(FakeClient):
        def complete(self, system, messages, tools):
            assert [t["name"] for t in tools] == ["list_governed_metrics", "query_governed_metric"]
            return Reply("", [ToolCall("c", "nope", {})], 5, 1, "tool_use")

    res = eval_run.ask_api("q", "governed", Looping())
    assert res["error"] == "turn_cap" and res["turns"] == 12 and res["input_tokens"] == 60
    assert (res["provider"], res["model"]) == ("fake", "fake-1")
