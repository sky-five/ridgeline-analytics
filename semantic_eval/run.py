"""Raw tables vs governed metrics: the analyst answers each of the 25 questions twice, once per arm.

    python -m semantic_eval.run                          # both arms, all questions (Claude Code headless)
    python -m semantic_eval.run --arms raw --only cac_2025
    python -m semantic_eval.run --replay semantic_eval/results/<file>.json   # rescore a committed run

A run needs a built warehouse and a logged-in Claude Code. A replay needs neither: it rescores the
recorded answers against the recorded truth and prints the same table.
"""
import argparse
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from analyst.evals.score import correct
from analyst.prompt import parse_answer
from semantic_eval.answer_key import load_questions
from semantic_eval.arms import ARMS, SYSTEM, TOOLS

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def score(record: dict) -> bool:
    """Is the recorded answer right? Same tolerances as the first analyst eval."""
    answer = record.get("answer")
    if record.get("absolute") and isinstance(answer, int | float) and not isinstance(answer, bool):
        answer = abs(answer)  # "how much did we lose" can fairly be answered as a negative movement
    return correct(record["type"], answer, record["truth"], record.get("tolerance"))


def summarize(records: list[dict]) -> dict:
    by_arm = {}
    for arm in ARMS:
        rs = [r for r in records if r["arm"] == arm]
        if not rs:
            continue
        cats = sorted({r["category"] for r in rs})
        by_arm[arm] = {
            "correct": sum(r["correct"] for r in rs), "total": len(rs),
            "by_category": {c: [sum(r["correct"] for r in rs if r["category"] == c),
                                sum(r["category"] == c for r in rs)] for c in cats},
            "errors": sum(bool(r.get("error")) for r in rs),
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rs), 2),
            "median_seconds": _median([r["seconds"] for r in rs]),
            "median_tool_calls": _median([len(r.get("tool_calls") or []) for r in rs]),
        }
    ok = {(r["id"], r["arm"]): r["correct"] for r in records}
    ids = sorted({r["id"] for r in records})
    both = [i for i in ids if (i, "raw") in ok and (i, "governed") in ok]
    return {"arms": by_arm,
            "only_governed_right": [i for i in both if ok[i, "governed"] and not ok[i, "raw"]],
            "only_raw_right": [i for i in both if ok[i, "raw"] and not ok[i, "governed"]]}


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    mid = len(xs) // 2
    return float(xs[mid]) if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def replay(path: Path) -> dict:
    """Rescore a recorded run. Nothing is asked again and no warehouse is opened."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in report["results"]:
        r["correct"] = score(r)
    report["summary"] = summarize(report["results"])
    return report


def truth(q: dict) -> float | str:
    """The answer key's answer, through the read-only path (MetricFlow compiles, the SQL guard runs it).

    semantic.query would hold a write lock on the warehouse for the whole run and lock out the arms' servers.
    """
    from semantic_eval import arms as arm_tools
    from semantic_eval.answer_key import pick_answer

    res = arm_tools.query_governed_metric([q["metric"]], q.get("group_by"), q.get("where"))
    if "error" in res:
        raise RuntimeError(f"{q['id']}: {res['error']}")
    rows = [dict(zip(res["columns"], row, strict=True)) for row in res["rows"]]
    for row in rows:
        for col in q.get("group_by") or []:
            if col.startswith("metric_time") or "cohort_month" in col:
                row[col] = datetime.fromisoformat(str(row[col]))
    return pick_answer(q, rows)


def run(arms: list[str], only: list[str] | None, model: str | None, workers: int) -> dict:
    from analyst.evals.run import ask_claude_code
    from semantic_eval import arms as arm_tools

    questions = [q for q in load_questions() if not only or q["id"] in only]
    truths = {q["id"]: truth(q) for q in questions}
    warehouse = Path(os.environ.get("RIDGELINE_DUCKDB_PATH", HERE.parent / "warehouse" / "ridgeline.duckdb"))
    as_of = arm_tools.query_governed_metric(["mrr"], ["metric_time__day"], None, ["-metric_time__day"], 1)
    as_of = str(as_of["rows"][0][0])[:10]
    raw_copy = arm_tools.build_raw_copy(warehouse, Path(tempfile.mkdtemp(prefix="ridgeline-raw-")) / "raw.duckdb")
    arm_tools.close()  # the MCP servers open the files in their own processes
    env = {"RIDGELINE_DUCKDB_PATH": str(warehouse), "RIDGELINE_RAW_DUCKDB_PATH": str(raw_copy)}

    def one(job):
        q, arm = job
        res = ask_claude_code(q["question"], model, server=["-m", "semantic_eval.server", arm],
                              tool_names=[f.__name__ for f in TOOLS[arm]], system=SYSTEM[arm], env=env)
        ans = parse_answer(res["text"]) or {}
        record = {"id": q["id"], "arm": arm, "category": q["category"], "question": q["question"],
                  "type": q["type"], "absolute": q.get("absolute", False), "tolerance": q.get("tolerance"),
                  "truth": truths[q["id"]], "answer": ans.get("answer"), "unit": ans.get("unit"),
                  "definition": ans.get("definition"), "parsed": bool(ans), "trap": q["trap"], **res}
        record["correct"] = score(record)
        return record

    jobs = [(q, arm) for q in questions for arm in arms]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    return {"ran_at": datetime.now().isoformat(timespec="seconds"), "as_of": as_of, "backend": "claude-code",
            "model": next((r["model"] for r in results if r.get("model")), model or "default"),
            "summary": summarize(results), "results": results}


def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"as of {report['as_of']}, model {report['model']}")
    print(f"{'arm':<10} {'correct':>9} {'cost':>8} {'median s':>9} {'tool calls':>11}")
    for arm, a in s["arms"].items():
        print(f"{arm:<10} {a['correct']:>4}/{a['total']:<4} {a['cost_usd']:>8.2f} {a['median_seconds']:>9.1f} "
              f"{a['median_tool_calls']:>11.1f}")
    cats = sorted({c for a in s["arms"].values() for c in a["by_category"]})
    for c in cats:
        cells = "  ".join(f"{arm} {a['by_category'].get(c, [0, 0])[0]}/{a['by_category'].get(c, [0, 0])[1]}"
                          for arm, a in s["arms"].items())
        print(f"  {c:<22} {cells}")
    print(f"only governed right: {', '.join(s['only_governed_right']) or '-'}")
    print(f"only raw right:      {', '.join(s['only_raw_right']) or '-'}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", nargs="*", choices=ARMS, default=list(ARMS))
    p.add_argument("--only", nargs="*", help="question ids")
    p.add_argument("--model", default=None, help="Claude Code model alias or id; default: its default")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--replay", type=Path, help="rescore a recorded run instead of running")
    args = p.parse_args()

    if args.replay:
        print_report(replay(args.replay))
        return
    report = run(args.arms, args.only, args.model, args.workers)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"raw-vs-governed-{report['ran_at'][:10]}.json"
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print_report(report)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
