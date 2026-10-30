"""Run the 20 analyst questions and score them.

    python -m analyst.evals.run --backend claude-code        # Claude Code headless + the MCP server
    python -m analyst.evals.run --backend api                # Claude API agent (needs credentials)

Writes analyst/evals/results/<backend>-<date>.json and prints a table. Truth is computed from the warehouse
at run time, so build it first (scripts/run_all.py).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from analyst import tools
from analyst.evals.score import correct, grounded
from analyst.prompt import SYSTEM, parse_answer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
QUESTIONS = HERE / "questions.yml"
TOOL_NAMES = [f.__name__ for f in tools.ALL]


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def truth_for(q: dict):
    if q["type"] == "unanswerable":
        return None
    if "truth_sql" in q:
        res = tools.run_sql(q["truth_sql"])
        if "error" in res:
            raise RuntimeError(f"{q['id']}: {res['error']}")
        return res["rows"][0][0] if res["rows"] else None
    if "truth_metric" in q:
        res = tools.query_metric([q["truth_metric"]])
        if "error" in res:
            raise RuntimeError(f"{q['id']}: {res['error']}")
        return res["rows"][0][-1]
    if "truth_lineage_sources" in q:
        nodes = tools.get_lineage(q["truth_lineage_sources"])["nodes"]
        return sorted(n["name"] for n in nodes if n["layer"] == "source")
    raise ValueError(f"{q['id']}: no truth defined")


# ---- backends: each returns {"text", "turns", "tool_calls", "seconds", "cost_usd"?, "error"?}

def ask_claude_code(question: str, model: str | None, timeout: int = 600) -> dict:
    exe = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        raise SystemExit("Claude Code not found: put `claude` on PATH or set CLAUDE_BIN")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {"ridgeline": {
            "command": sys.executable, "args": ["-m", "analyst.server"], "cwd": str(ROOT),
            "env": {"PYTHONPATH": str(ROOT)}}}}), encoding="utf-8")
        cmd = [exe, "-p", question, "--output-format", "stream-json", "--verbose",
               "--mcp-config", str(cfg), "--strict-mcp-config", "--tools", "",
               "--allowedTools", ",".join(f"mcp__ridgeline__{t}" for t in TOOL_NAMES),
               "--system-prompt", SYSTEM, "--no-session-persistence", "--setting-sources", ""]
        if model:
            cmd += ["--model", model]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"text": "", "turns": 0, "tool_calls": [], "seconds": timeout, "error": "timeout"}
    calls, final = [], {}
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            down = [m for m in ev.get("mcp_servers", []) if m.get("status") != "connected"]
            if down:
                raise SystemExit(f"MCP server did not start: {down}")
        if ev.get("type") == "assistant":
            calls += [b["name"].removeprefix("mcp__ridgeline__") for b in ev["message"].get("content", [])
                      if b.get("type") == "tool_use"]
        elif ev.get("type") == "result":
            final = ev
    if "not logged in" in (final.get("result") or "").lower():
        raise SystemExit("Claude Code is not logged in: run `claude auth login` once, then rerun the eval")
    out = {"text": final.get("result", ""), "turns": final.get("num_turns", 0), "tool_calls": calls,
           "seconds": round(time.time() - t0, 1), "cost_usd": final.get("total_cost_usd")}
    if not final or final.get("is_error"):
        out["error"] = (final.get("subtype") or proc.stderr[-500:] or "no result").strip()
    return out


def ask_api(question: str, model: str | None) -> dict:
    from analyst.agent import MODEL, ask

    t0 = time.time()
    r = ask(question, model=model or MODEL)
    out = {"text": r.text, "turns": r.turns, "tool_calls": r.tool_calls, "seconds": round(time.time() - t0, 1),
           "tokens": r.input_tokens + r.output_tokens}
    if r.stopped != "done":
        out["error"] = r.stopped
    return out


def run(backend: str, model: str | None, only: list[str] | None, workers: int) -> dict:
    questions = [q for q in load_questions() if not only or q["id"] in only]
    truths = {q["id"]: truth_for(q) for q in questions}
    tools.close()  # the MCP servers open the warehouse in their own processes
    ask = ask_claude_code if backend == "claude-code" else ask_api

    def one(q):
        res = ask(q["question"], model)
        ans = parse_answer(res["text"])
        value = ans.get("answer") if ans else None
        return {
            "id": q["id"], "question": q["question"], "type": q["type"], "truth": truths[q["id"]],
            "answer": value, "parsed": ans is not None,
            "correct": ans is not None and correct(q["type"], value, truths[q["id"]], q.get("tolerance")),
            "grounded": ans is not None and grounded(q["models"], ans.get("models")),
            "cited_models": (ans or {}).get("models"), "metric": (ans or {}).get("metric"),
            "sql": (ans or {}).get("sql"), "note": (ans or {}).get("note"), **res,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, questions))
    return {"backend": backend, "model": model or "default", "ran_at": datetime.now().isoformat(timespec="seconds"),
            "as_of": tools.run_sql("select max(date_day) from fct_mrr_daily")["rows"][0][0],
            "correct": sum(r["correct"] for r in results), "grounded": sum(r["grounded"] for r in results),
            "total": len(results), "results": results}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["claude-code", "api"], default="claude-code")
    p.add_argument("--model", default=None, help="model id or alias; default: the backend's default")
    p.add_argument("--only", nargs="*", help="question ids")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    report = run(args.backend, args.model, args.only, args.workers)
    out = HERE / "results" / f"{args.backend}-{report['ran_at'][:10]}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    for r in report["results"]:
        mark = "PASS" if r["correct"] else "FAIL"
        print(f"{mark} {'G' if r['grounded'] else '-'} {r['id']:<24} truth={r['truth']!s:<28.28} "
              f"answer={r['answer']!s:<28.28} {r['turns']:>2} turns {r['seconds']:>5}s {r.get('error', '')}")
    print(f"\n{report['correct']}/{report['total']} correct, {report['grounded']}/{report['total']} grounded -> {out}")


if __name__ == "__main__":
    main()
