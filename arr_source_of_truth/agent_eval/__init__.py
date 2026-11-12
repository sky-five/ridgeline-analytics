"""The ARR agent's eval: 20 questions, 14 the ARR models answer and 6 they don't.

    python -m arr_source_of_truth.agent_eval                                   # keyword baseline, no key
    python -m arr_source_of_truth.agent_eval --provider gemini --record        # a model, saved to results/
    python -m arr_source_of_truth.agent_eval --replay results/<file>.json      # rescore a saved run

Each question is asked on the ARR warehouse as of 2026-09-30. An answer counts as right when the check
delivered it, the number (or status) equals the truth and it cites a model the question allows. A refusal
question is right when the agent refused. The number that matters most is "wrong, delivered": a wrong
number that reached the person asking.

A replay needs no key: it reruns every recorded tool call against a fresh build and stops if any result
differs from the recording, then reruns the check and the scoring on the recorded replies.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml

from analyst.evals.score import correct
from arr_source_of_truth import agent
from arr_source_of_truth.load import AS_OF

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yml"
RESULTS = HERE / "results"


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))


def truths(db: Path, questions: list[dict]) -> dict[str, float | str | None]:
    """Each answerable question's truth, straight from the models."""
    out: dict[str, float | str | None] = {}
    with duckdb.connect(str(db), read_only=True) as con:
        for q in questions:
            if q["type"] == "refuse":
                out[q["id"]] = None
                continue
            (v,) = con.execute(q["truth_sql"]).fetchone()
            out[q["id"]] = float(v) if q["type"] == "number" else str(v)
    return out


def score_one(q: dict, truth, rec: dict) -> dict:
    """Outcome of one answer: right, wrong_delivered, held_back, false_refusal (or refused / answered for
    refusal questions)."""
    checked = agent.check(rec["text"], rec["tool_results"])
    delivered, refused = checked.delivered, checked.refused
    if q["type"] == "refuse":
        outcome = "right" if refused else ("held_back" if delivered is None else "answered")
    elif delivered is None:
        outcome = "false_refusal" if refused else "held_back"
    else:
        value = delivered.get("answer")
        if q["type"] == "number" and isinstance(value, int | float) and not isinstance(value, bool):
            value = abs(value)
        ok_value = correct(q["type"], value, abs(truth) if q["type"] == "number" else truth, 0.0)
        ok_model = bool(set(delivered.get("models") or []) & set(q["models"]))
        outcome = "right" if ok_value and ok_model else "wrong_delivered"
    return {"id": q["id"], "type": q["type"], "question": q["question"], "truth": truth,
            "delivered": delivered, "refused": refused, "held_back": checked.held_back, "outcome": outcome}


def summarize(scored: list[dict]) -> dict:
    ans = [s for s in scored if s["type"] != "refuse"]
    ref = [s for s in scored if s["type"] == "refuse"]
    count = lambda rows, o: sum(s["outcome"] == o for s in rows)  # noqa: E731
    return {"questions": len(scored),
            "answerable": {"total": len(ans), "right": count(ans, "right"),
                           "wrong_delivered": count(ans, "wrong_delivered"), "held_back": count(ans, "held_back"),
                           "false_refusal": count(ans, "false_refusal")},
            "out_of_scope": {"total": len(ref), "refused": count(ref, "right"), "answered": count(ref, "answered"),
                             "held_back": count(ref, "held_back")}}


def run(client, db: Path, questions: list[dict] | None = None) -> dict:
    """Ask every question, score it, and return the whole record (the file --record writes)."""
    questions = questions or load_questions()
    truth = truths(db, questions)
    tools = agent.ArrTools(db)
    try:
        answers = [agent.ask(q["question"], client, tools).to_dict() for q in questions]
    finally:
        tools.close()
    scored = [score_one(q, truth[q["id"]], a) for q, a in zip(questions, answers, strict=True)]
    return {"provider": client.provider, "model": client.model, "as_of": AS_OF.isoformat(),
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
            "summary": summarize(scored),
            "results": [{**s, "answer": a} for s, a in zip(scored, answers, strict=True)]}


def verify_tools(report: dict, db: Path) -> list[str]:
    """Rerun every recorded tool call; return the ids whose results differ from the recording."""
    tools = agent.ArrTools(db)
    fns = {f.__name__: f for f in tools.all()}
    bad = []
    try:
        for r in report["results"]:
            a = r["answer"]
            fresh = [fns[c["name"]](**c["arguments"]) if c["name"] in fns else None for c in a["tool_calls"]]
            if json.loads(json.dumps(fresh, default=str)) != a["tool_results"]:
                bad.append(r["id"])
    finally:
        tools.close()
    return bad


def replay(path: Path, questions: list[dict] | None = None) -> dict:
    """Rescore a saved run from its recorded replies and tool results; asks nothing."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in questions or load_questions()}
    scored = [score_one(by_id[r["id"]], r["truth"], r["answer"]) for r in report["results"]]
    report["summary"] = summarize(scored)
    report["results"] = [{**s, "answer": r["answer"]} for s, r in zip(scored, report["results"], strict=True)]
    return report


def table(report: dict) -> str:
    s = report["summary"]
    a, o = s["answerable"], s["out_of_scope"]
    lines = [f"{report['provider']} / {report['model']}, ARR warehouse as of {report['as_of']}",
             f"  answerable    {a['right']:>2} of {a['total']} right, {a['wrong_delivered']} wrong delivered, "
             f"{a['held_back']} held back by the check, {a['false_refusal']} refused",
             f"  out of scope  {o['refused']:>2} of {o['total']} refused, {o['answered']} answered, "
             f"{o['held_back']} held back by the check"]
    for r in report["results"]:
        if r["outcome"] != "right":
            lines.append(f"  - {r['id']}: {r['outcome']}" + (f" ({r['held_back']})" if r["held_back"] else ""))
    return "\n".join(lines)
