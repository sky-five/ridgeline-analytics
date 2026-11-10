"""Raw tables vs governed metrics: the analyst answers each of the 25 questions twice, once per arm.

    python -m semantic_eval.run                          # both arms, all questions (Claude Code headless)
    python -m semantic_eval.run --arms raw --only cac_2025
    python -m semantic_eval.run --backend api --provider gemini --limit 20   # API agent, resumable
    python -m semantic_eval.run --replay semantic_eval/results/<file>.json   # rescore a committed run

A run needs a built warehouse, and a logged-in Claude Code (default backend) or an API key for the
provider (--backend api; see analyst/llm.py). API runs append to one results file per provider, model and
day and skip answers already recorded there, so a free daily quota can be spread over several runs; --limit
caps how many new answers one run records. A replay needs neither warehouse nor key: it rescores the
recorded answers against the recorded truth and prints the same table.
"""
import argparse
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from analyst.evals.score import correct
from analyst.prompt import parse_answer
from semantic_eval.answer_key import load_questions
from semantic_eval.arms import ARMS, SYSTEM, TOOLS

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def _text_match(answer, truth) -> bool:
    """The expected label appears in the answer as whole words ("measurement_accuracy (3,028 tickets)"), and
    a month written out ("June 2026") equals its key form ("2026-06")."""
    text = str(answer)
    m = re.fullmatch(r"\s*([A-Za-z]+)\.?\s+(\d{4})\s*", text)
    if m and m.group(1).lower() in MONTHS:
        text = f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    norm = lambda x: re.sub(r"[^a-z0-9.]+", "_", str(x).lower()).strip("_")  # noqa: E731
    return f"_{norm(truth)}_" in f"_{norm(text)}_"


def score(record: dict) -> bool:
    """Is the recorded answer right? Same tolerances as the first analyst eval; text answers as _text_match."""
    answer = record.get("answer")
    if record["type"] == "text":
        return answer is not None and record["truth"] is not None and _text_match(answer, record["truth"])
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


def record(q: dict, arm: str, truth_value, res: dict) -> dict:
    """One scored answer: the question, the truth, the parsed answer and what the backend reported."""
    ans = parse_answer(res["text"]) or {}
    rec = {"id": q["id"], "arm": arm, "category": q["category"], "question": q["question"],
           "type": q["type"], "absolute": q.get("absolute", False), "tolerance": q.get("tolerance"),
           "truth": truth_value, "answer": ans.get("answer"), "unit": ans.get("unit"),
           "definition": ans.get("definition"), "parsed": bool(ans), "trap": q["trap"], **res}
    rec["correct"] = score(rec)
    return rec


def _prepare(only: list[str] | None, raw: bool = True) -> tuple[list[dict], dict, str, Path, Path | None]:
    """Questions, their truths, the as-of date, and the warehouse plus a raw-only copy of it.

    On the governed arm alone (raw=False) no raw copy is made, so this also works on Snowflake
    (RIDGELINE_DBT_TARGET=snowflake), where the truths come from the Snowflake build.
    """
    from semantic_eval import arms as arm_tools

    questions = [q for q in load_questions() if not only or q["id"] in only]
    truths = {q["id"]: truth(q) for q in questions}
    warehouse = Path(os.environ.get("RIDGELINE_DUCKDB_PATH", HERE.parent / "warehouse" / "ridgeline.duckdb"))
    as_of = arm_tools.query_governed_metric(["mrr"], ["metric_time__day"], None, ["-metric_time__day"], 1)
    if "error" in as_of:
        raise RuntimeError(f"as-of date: {as_of['error']}")
    as_of = str(as_of["rows"][0][0])[:10]
    raw_copy = None
    if raw:
        raw_copy = arm_tools.build_raw_copy(warehouse, Path(tempfile.mkdtemp(prefix="ridgeline-raw-")) / "raw.duckdb")
    arm_tools.close()  # MCP servers (or the API backend's tools) reopen the files read-only
    return questions, truths, as_of, warehouse, raw_copy


def ask_api(question: str, arm: str, client) -> dict:
    """One answer from the provider-agnostic agent loop, with the arm's two tools, in this process."""
    from analyst.agent import MAX_TOKENS, MAX_TURNS
    from analyst.llm import run as run_agent

    t0 = time.time()
    r = run_agent(question, client, TOOLS[arm], SYSTEM[arm], MAX_TURNS, MAX_TOKENS)
    out = {"text": r.text, "turns": r.turns, "tool_calls": r.tool_calls, "tool_inputs": r.tool_inputs,
           "model": client.model, "provider": client.provider, "seconds": round(time.time() - t0, 1),
           "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": None}
    if r.stopped != "done":
        out["error"] = r.stopped
    return out


def pending(questions: list[dict], arms: list[str], done: list[dict]) -> list[tuple[dict, str]]:
    """(question, arm) pairs not yet recorded without an error, in question order, arms interleaved."""
    have = {(r["id"], r["arm"]) for r in done if not r.get("error")}
    return [(q, arm) for q in questions for arm in arms if (q["id"], arm) not in have]


def run_api(arms: list[str], only: list[str] | None, client, out: Path, limit: int | None = None,
            ask=ask_api, prepare=_prepare) -> dict:
    """Record answers through an API client into `out`, resuming from what is already there.

    The file is rewritten after every answer, so a run stopped by a quota or a timeout keeps its work.
    An answer that ended in an error (cap hit, provider error) is asked again on the next run.
    """
    from semantic import target

    questions, truths, as_of, warehouse, raw_copy = prepare(only, raw="raw" in arms)
    os.environ["RIDGELINE_DUCKDB_PATH"] = str(warehouse)
    if raw_copy is not None:
        os.environ["RIDGELINE_RAW_DUCKDB_PATH"] = str(raw_copy)
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"results": []}
    if report.get("as_of", as_of) != as_of:
        raise SystemExit(f"{out} was recorded as of {report['as_of']}, the warehouse is as of {as_of}: "
                         "use a new --out file or rebuild the warehouse for that date")
    if report.get("target", target()) != target():
        raise SystemExit(f"{out} was recorded on {report['target']}, this run is on {target()}: use a new --out file")
    report.update({"as_of": as_of, "backend": "api", "provider": client.provider, "model": client.model,
                   "target": target()})
    todo = pending(questions, arms, report["results"])[:limit]
    for q, arm in todo:
        try:
            res = ask(q["question"], arm, client)
        except Exception as e:  # quota exhausted or provider down: keep what we have, resume next run
            print(f"stopped at {q['id']}/{arm}: {type(e).__name__}: {e}")
            break
        report["results"] = [r for r in report["results"] if (r["id"], r["arm"]) != (q["id"], arm)]
        report["results"].append(record(q, arm, truths[q["id"]], res))
        report["ran_at"] = datetime.now().isoformat(timespec="seconds")
        report["summary"] = summarize(report["results"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    report["remaining"] = len(pending(questions, arms, report["results"]))
    report["summary"] = summarize(report["results"])
    return report


def run(arms: list[str], only: list[str] | None, model: str | None, workers: int) -> dict:
    from analyst.evals.run import ask_claude_code

    questions, truths, as_of, warehouse, raw_copy = _prepare(only)
    env = {"RIDGELINE_DUCKDB_PATH": str(warehouse), "RIDGELINE_RAW_DUCKDB_PATH": str(raw_copy)}

    def one(job):
        q, arm = job
        res = ask_claude_code(q["question"], model, server=["-m", "semantic_eval.server", arm],
                              tool_names=[f.__name__ for f in TOOLS[arm]], system=SYSTEM[arm], env=env)
        return record(q, arm, truths[q["id"]], res)

    jobs = [(q, arm) for q in questions for arm in arms]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    return {"ran_at": datetime.now().isoformat(timespec="seconds"), "as_of": as_of, "backend": "claude-code",
            "model": next((r["model"] for r in results if r.get("model")), model or "default"),
            "summary": summarize(results), "results": results}


def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"as of {report['as_of']}, provider {report.get('provider', 'anthropic')}, model {report['model']}")
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
    p.add_argument("--backend", choices=["claude-code", "api"], default="claude-code")
    p.add_argument("--provider", default="gemini", help="api backend: anthropic or gemini (analyst/llm.py)")
    p.add_argument("--model", default=None, help="model alias or id; default: the backend's default")
    p.add_argument("--workers", type=int, default=4, help="claude-code backend only")
    p.add_argument("--limit", type=int, default=None, help="api backend: record at most this many new answers")
    p.add_argument("--pace", type=float, default=0.0,
                   help="api backend: minimum seconds between model requests (e.g. 6 for 10 requests/minute)")
    p.add_argument("--out", type=Path, help="api backend: results file to write and resume from")
    p.add_argument("--replay", type=Path, help="rescore a recorded run instead of running")
    args = p.parse_args()

    if args.replay:
        print_report(replay(args.replay))
        return
    if args.backend == "api":
        from analyst.llm import make_client

        kw = {"min_interval_seconds": args.pace} if args.provider != "anthropic" else {}
        client = make_client(args.provider, args.model, **kw)
        slug = re.sub(r"[^a-z0-9.]+", "-", client.model.lower()).strip("-")
        out = args.out or RESULTS / f"raw-vs-governed-{client.provider}-{slug}-{datetime.now():%Y-%m-%d}.json"
        report = run_api(args.arms, args.only, client, out, args.limit)
        print_report(report)
        print(f"-> {out} ({report['remaining']} answers still to record)")
        return
    report = run(args.arms, args.only, args.model, args.workers)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"raw-vs-governed-{report['ran_at'][:10]}.json"
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print_report(report)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
