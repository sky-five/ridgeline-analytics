"""Governed answers on two warehouses: the 25 eval questions through MetricFlow on Snowflake and on DuckDB.

    RIDGELINE_DBT_TARGET=snowflake python -m semantic_eval.cross_target snapshot --out sf.json
    python -m semantic_eval.cross_target compare sf.json --out semantic_eval/results/snowflake-vs-duckdb.json

`snapshot` answers every question on the current dbt target (the semantic manifest must be from a
parse for that target). `compare` answers them again on the current target (DuckDB) and checks each
pair. Same questions, same metric definitions, same reduce step (answer_key.pick_answer); only the
engine differs. Exit code 1 if any answer differs.

    python -m semantic_eval.cross_target runs sf-run.json duckdb-run.json --out report.json

`runs` pairs two recorded governed-arm runs of the same model (semantic_eval.run --backend api
--arms governed), one per warehouse: is each answer right on its own warehouse, and did the model
give the same answer on both? Model answers vary from run to run, so this reports, it never fails.
"""
import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Snowflake divides fixed-point numbers to 6 decimal places and DuckDB in doubles, so a ratio can
# differ around the 7th decimal. Anything bigger is a real difference.
REL_TOL = 1e-6
ABS_TOL = 1e-6


def target() -> str:
    return os.environ.get("RIDGELINE_DBT_TARGET", "duckdb")


def snapshot() -> dict:
    from semantic_eval.answer_key import build

    key = build()
    return {"target": target(), "as_of": key["as_of"], "answers": key["answers"]}


def same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)


def compare(left: dict, right: dict) -> dict:
    """Pair up two snapshots question by question."""
    rows = []
    for qid in sorted(set(left["answers"]) | set(right["answers"])):
        a, b = left["answers"].get(qid), right["answers"].get(qid)
        row = {"id": qid, left["target"]: a, right["target"]: b, "match": same(a, b)}
        if isinstance(a, int | float) and isinstance(b, int | float):
            row["abs_diff"] = abs(float(a) - float(b))
        rows.append(row)
    matched = sum(r["match"] for r in rows)
    return {
        "targets": [left["target"], right["target"]],
        "as_of": {left["target"]: left["as_of"], right["target"]: right["as_of"]},
        "same_as_of": left["as_of"] == right["as_of"],
        "matched": matched,
        "total": len(rows),
        "max_abs_diff": max((r.get("abs_diff", 0.0) for r in rows), default=0.0),
        "tolerance": {"rel": REL_TOL, "abs": ABS_TOL},
        "rows": rows,
    }


def compare_runs(left: dict, right: dict, arm: str = "governed") -> dict:
    """Pair two recorded runs (same model, one per warehouse) question by question."""
    def by_id(run):
        return {r["id"]: r for r in run["results"] if r["arm"] == arm}

    a, b = by_id(left), by_id(right)
    ta, tb = left.get("target", "duckdb"), right.get("target", "duckdb")
    rows = []
    for qid in sorted(set(a) | set(b)):
        ra, rb = a.get(qid), b.get(qid)
        rows.append({"id": qid,
                     f"{ta}_answer": ra and ra["answer"], f"{tb}_answer": rb and rb["answer"],
                     f"{ta}_correct": bool(ra and ra["correct"]), f"{tb}_correct": bool(rb and rb["correct"]),
                     "truth_match": bool(ra and rb) and same(ra["truth"], rb["truth"]),
                     "same_answer": bool(ra and rb) and _same_answer(ra["answer"], rb["answer"])})
    return {
        "arm": arm, "targets": [ta, tb],
        "models": {ta: left.get("model"), tb: right.get("model")},
        "as_of": {ta: left.get("as_of"), tb: right.get("as_of")},
        "same_as_of": left.get("as_of") == right.get("as_of"),
        "total": len(rows),
        "correct": {ta: sum(r[f"{ta}_correct"] for r in rows), tb: sum(r[f"{tb}_correct"] for r in rows)},
        "truths_match": sum(r["truth_match"] for r in rows),
        "same_answer": sum(r["same_answer"] for r in rows),
        "right_on_one_only": [r["id"] for r in rows if r[f"{ta}_correct"] != r[f"{tb}_correct"]],
        "rows": rows,
    }


def _same_answer(a, b) -> bool:
    try:
        return same(float(a), float(b))
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def runs_markdown(report: dict) -> str:
    a, b = report["targets"]
    c = report["correct"]
    lines = [f"### {report['arm'].capitalize()} arm, {report['models'][a]}: {a} vs {b}", "",
             f"Correct: {c[a]} / {report['total']} on {a}, {c[b]} / {report['total']} on {b}. "
             f"Same answer on both: {report['same_answer']} / {report['total']}. "
             f"Answer key equal on both: {report['truths_match']} / {report['total']}.", "",
             f"| Question | {a} | {b} | |", "|---|---|---|---|"]
    for r in report["rows"]:
        mark = lambda ok: "right" if ok else "wrong"  # noqa: E731
        lines.append(f"| {r['id']} | {_fmt(r[f'{a}_answer'])} ({mark(r[f'{a}_correct'])}) | "
                     f"{_fmt(r[f'{b}_answer'])} ({mark(r[f'{b}_correct'])}) | "
                     f"{'same' if r['same_answer'] else 'differs'} |")
    return "\n".join(lines) + "\n"


def ok(report: dict) -> bool:
    return report["same_as_of"] and report["matched"] == report["total"] and report["total"] > 0


def markdown(report: dict) -> str:
    a, b = report["targets"]
    lines = [f"### Governed answers: {a} vs {b}", "",
             f"{report['matched']} / {report['total']} match (data as of {report['as_of'][a]} on {a}, "
             f"{report['as_of'][b]} on {b}; largest numeric difference {report['max_abs_diff']:.2g})", "",
             f"| Question | {a} | {b} | |", "|---|---|---|---|"]
    for r in report["rows"]:
        lines.append(f"| {r['id']} | {_fmt(r[a])} | {_fmt(r[b])} | {'match' if r['match'] else 'DIFF'} |")
    return "\n".join(lines) + "\n"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="answer every question on the current dbt target")
    s.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare", help="answer on the current target and compare with a snapshot")
    c.add_argument("snapshot", type=Path)
    c.add_argument("--out", type=Path)
    r = sub.add_parser("runs", help="pair two recorded governed-arm runs, one per warehouse")
    r.add_argument("left", type=Path)
    r.add_argument("right", type=Path)
    r.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "runs":
        left, right = (json.loads(f.read_text(encoding="utf-8")) for f in (args.left, args.right))
        report = compare_runs(left, right)
        text = runs_markdown(report)
        print(text)
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as f:
                f.write(text)
        if args.out:
            args.out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
        return 0

    if args.cmd == "snapshot":
        snap = snapshot()
        args.out.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
        print(f"{len(snap['answers'])} answers on {snap['target']} (as of {snap['as_of']}) -> {args.out}")
        return 0

    other = json.loads(args.snapshot.read_text(encoding="utf-8"))
    report = compare(other, snapshot())
    report["run_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    if run := os.environ.get("GITHUB_RUN_ID"):
        repo = f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}"
        report["run"] = f"{repo}/actions/runs/{run}"
    text = markdown(report)
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0 if ok(report) else 1


if __name__ == "__main__":
    sys.exit(main())
