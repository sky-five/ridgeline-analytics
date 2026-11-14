"""The metric-registry analyst's answer-quality suite: 20 golden questions, 16 answerable and 4 not.

    python -m metric_registry.agent_eval                                  # keyword baseline, no key
    python -m metric_registry.agent_eval --provider gemini --record       # a model, saved to results/
    python -m metric_registry.agent_eval --replay results/<file>.json     # rescore a saved run, no key

Every question is asked on the seeded build as of 2026-06-30 through the MCP server. An answerable
question passes when the check delivered the answer, the value equals the truth (from SQL straight on the
dbt tables, not through MetricFlow), it cites the expected metric, and its lineage (the SQL MetricFlow ran)
reads the expected tables and the dimensions the question cuts by. A refuse question passes when the agent
refused. "Wrong, delivered" is the outcome that matters most: a wrong number that reached the person asking.

A replay needs no key: with --db it reruns every recorded tool call against a fresh build and stops if any
result differs from the recording; then it reruns the check and the scoring on the recorded replies.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml

from metric_registry import agent
from metric_registry.simulate import AS_OF

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yml"
RESULTS = HERE / "results"


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))


def truths(db: Path, questions: list[dict]) -> dict[str, float | None]:
    """Each answerable question's truth, straight from the dbt tables."""
    out: dict[str, float | None] = {}
    with duckdb.connect(str(db), read_only=True) as con:
        for q in questions:
            out[q["id"]] = None if q["type"] == "refuse" else float(con.execute(q["truth_sql"]).fetchone()[0])
    return out


def same_value(answer, truth: float, kind: str) -> bool:
    """Dollars and counts to the cent or rounded to a whole number; shares to 4 places or as a percent."""
    if isinstance(answer, bool):
        return False
    if isinstance(answer, str):
        try:
            answer = float(answer.replace(",", "").replace("$", "").replace("%", "").strip())
        except ValueError:
            return False
    if not isinstance(answer, int | float):
        return False
    if kind == "share":
        return abs(answer - truth) <= 5e-5 or abs(answer / 100 - truth) <= 5e-5
    return abs(answer - truth) <= 0.01 or round(truth) == answer


def lineage_ok(q: dict, delivered: dict) -> tuple[bool, str | None]:
    """The cited query's SQL reads every expected table and names every dimension the question cuts by."""
    sqls = [x["sql"] for x in delivered.get("lineage") or [] if q["metric"] in x["metrics"]]
    if not sqls:
        return False, f"no query of {q['metric']} behind the answer"
    for sql in sqls:
        tables = [t for t in q["tables"] if f'"{t}"' not in sql]
        needs = [n if isinstance(n, list) else [n] for n in q.get("sql_has", [])]
        missing = [" or ".join(n) for n in needs if not any(x in sql for x in n)]
        if not tables and not missing:
            return True, None
    return False, "lineage misses " + ", ".join(tables + missing)


def score_one(q: dict, truth, rec: dict) -> dict:
    """Outcome of one answer. Answerable: right, wrong_delivered, held_back, refused. Refuse: right
    (refused), answered, held_back."""
    c = agent.check(rec["text"], rec["tool_results"])
    why = c.held_back
    if q["type"] == "refuse":
        outcome = "right" if c.refused else ("held_back" if c.delivered is None else "answered")
    elif c.delivered is None:
        outcome = "refused" if c.refused else "held_back"
    else:
        ok_value = same_value(c.delivered.get("answer"), truth, q["type"])
        ok_metric = q["metric"] in c.delivered.get("metrics", [])
        ok_lineage, why_lineage = lineage_ok(q, c.delivered) if ok_metric else (False, None)
        outcome = "right" if ok_value and ok_metric and ok_lineage else "wrong_delivered"
        if outcome != "right":
            why = "; ".join(w for w in ["value" if not ok_value else None,
                                        f"cites {c.delivered.get('metrics')}" if not ok_metric else None,
                                        why_lineage] if w)
    sql = [x["sql"] for x in (c.delivered or {}).get("lineage", [])]
    return {"id": q["id"], "type": q["type"], "question": q["question"], "truth": truth,
            "delivered": None if c.delivered is None else {k: v for k, v in c.delivered.items() if k != "lineage"},
            "refused": c.refused, "why": why, "outcome": outcome, "passed": outcome == "right", "lineage": sql}


def summarize(scored: list[dict]) -> dict:
    ans = [s for s in scored if s["type"] != "refuse"]
    ref = [s for s in scored if s["type"] == "refuse"]
    count = lambda rows, o: sum(s["outcome"] == o for s in rows)  # noqa: E731
    return {"questions": len(scored), "passed": sum(s["passed"] for s in scored),
            "answerable": {"total": len(ans), "right": count(ans, "right"),
                           "wrong_delivered": count(ans, "wrong_delivered"), "held_back": count(ans, "held_back"),
                           "refused": count(ans, "refused"),
                           "with_lineage": sum(bool(s["lineage"]) for s in ans)},
            "out_of_scope": {"total": len(ref), "refused": count(ref, "right"), "answered": count(ref, "answered"),
                             "held_back": count(ref, "held_back")}}


def run(client, db: Path, questions: list[dict] | None = None) -> dict:
    """Ask every question through the MCP server, score it, and return the whole record (what --record
    writes)."""
    questions = questions or load_questions()
    truth = truths(db, questions)
    with agent.McpTools(db) as tools:
        answers = [agent.ask(q["question"], client, tools).to_dict() for q in questions]
    scored = [score_one(q, truth[q["id"]], a) for q, a in zip(questions, answers, strict=True)]
    return {"provider": client.provider, "model": client.model, "as_of": AS_OF.isoformat(),
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
            "summary": summarize(scored),
            "results": [{**s, "answer": a} for s, a in zip(scored, answers, strict=True)]}


def verify_tools(report: dict, db: Path) -> list[str]:
    """Rerun every recorded tool call through the server; the ids whose results differ from the recording."""
    bad = []
    with agent.McpTools(db) as tools:
        for r in report["results"]:
            a = r["answer"]
            fresh = [tools.call(c["name"], c["arguments"]) for c in a["tool_calls"]]
            if json.loads(json.dumps(fresh, default=str)) != a["tool_results"]:
                bad.append(r["id"])
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
    lines = [f"{report['provider']} / {report['model']}, vehicle sales as of {report['as_of']}: "
             f"{s['passed']} of {s['questions']} passed",
             f"  answerable    {a['right']:>2} of {a['total']} right, {a['wrong_delivered']} wrong delivered, "
             f"{a['held_back']} held back by the check, {a['refused']} refused; {a['with_lineage']} with SQL lineage",
             f"  out of scope  {o['refused']:>2} of {o['total']} refused, {o['answered']} answered, "
             f"{o['held_back']} held back by the check"]
    for r in report["results"]:
        if not r["passed"]:
            lines.append(f"  - {r['id']}: {r['outcome']}" + (f" ({r['why']})" if r["why"] else ""))
    return "\n".join(lines)
