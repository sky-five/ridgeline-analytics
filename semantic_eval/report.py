"""Turn the recorded raw-vs-governed runs into tables for the "Raw tables vs governed metrics" page.

Reads every `results/raw-vs-governed*.json` (one file per recorded run, any model) and returns three frames:

- eval_scores      one row per run and arm: correct out of total, errors, median tool calls and seconds, cost
- eval_categories  one row per run, arm and question area: correct out of total
- eval_questions   one row per run and question: both arms' answers next to the truth, the trap the question
                   was written to catch, and what the raw arm actually ran

No model calls and no warehouse: the page shows what was recorded, so the numbers only change when a new run
is committed.
"""
import json
from pathlib import Path

import pandas as pd

RESULTS = Path(__file__).resolve().parent / "results"
PATTERN = "raw-vs-governed*.json"

# Raw-arm misses that name the right thing in the run's own words, so they are wrong only on form: the scorer
# wants the governed label or the full month. Judged by reading each reply; the README counts them the same way.
FORM_ONLY = {
    ("claude-sonnet-5-5", "best_speed_bucket"): "Named the under-5-minute bucket in its own words, not as lt_5m.",
    ("claude-sonnet-5-5", "top_ticket_theme_2025"): "Described measurement accuracy problems, not the label.",
    ("gemini-3.5-flash-lite", "best_net_new_month_2026"): "Said June without the year.",
    ("gemini-3.5-flash-lite", "best_speed_bucket"): "Said 0-5 minutes, not lt_5m.",
}


def run_label(run: dict) -> str:
    """Who answered: the harness or provider, and the model."""
    if run.get("backend") == "claude-code":
        return f"Claude Code, {run['model']}"
    return f"{run.get('provider', run.get('backend', '?')).title()} API, {run['model']}"


def fmt_answer(value, kind: str | None, unit: str | None) -> str:
    """An answer the way a reader expects it: $243,419, 31.3%, 552, 4.5 min, or the text itself."""
    if value is None or value == "":
        return "no answer"
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if kind == "ratio" and abs(value) <= 1.5:
        return f"{value:.1%}"
    if unit == "usd":
        return f"${value:,.0f}" if abs(value) >= 100 else f"${value:,.2f}"
    if unit == "minutes":
        return f"{value:,.1f} min"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def _last_input(record: dict, tool: str) -> str:
    """The last call the arm made to `tool`: SQL text for raw, the MetricFlow query for governed."""
    calls = [i for name, i in zip(record.get("tool_calls", []), record.get("tool_inputs", []), strict=True)
             if name == tool]
    if not calls:
        return ""
    last = calls[-1]
    if "sql" in last:
        return last["sql"].strip()
    return json.dumps(last, sort_keys=True)


def load_runs(results_dir: Path = RESULTS) -> list[dict]:
    """Recorded runs, oldest first. Files of another shape (e.g. the Snowflake parity check) are skipped."""
    runs = []
    for path in sorted(results_dir.glob(PATTERN)):
        run = json.loads(path.read_text(encoding="utf-8"))
        if "results" in run and "summary" in run:
            runs.append({**run, "file": path.name})
    return sorted(runs, key=lambda r: r["ran_at"])


def tables(results_dir: Path = RESULTS) -> dict[str, pd.DataFrame]:
    runs = load_runs(results_dir)
    if not runs:
        return {}
    scores, categories, questions = [], [], []
    for order, run in enumerate(runs, start=1):
        label = run_label(run)
        common = {"run_order": order, "run": label, "model": run["model"], "as_of": run["as_of"],
                  "ran_on": run["ran_at"][:10], "file": run["file"]}
        for arm, s in run["summary"]["arms"].items():
            on_form = sum(model == run["model"] for model, _ in FORM_ONLY) if arm == "raw" else 0
            scores.append({**common, "arm": arm, "correct": s["correct"], "total": s["total"],
                           "correct_on_substance": s["correct"] + on_form,
                           "accuracy": s["correct"] / s["total"], "errors": s["errors"],
                           "median_tool_calls": s["median_tool_calls"], "median_seconds": s["median_seconds"],
                           "cost_usd": s["cost_usd"]})
            for area, (right, n) in s["by_category"].items():
                categories.append({"run_order": order, "run": label, "arm": arm,
                                   "category": area.replace("_", " ").capitalize(), "correct": right, "total": n})

        by_q: dict[str, dict] = {}
        for r in run["results"]:
            by_q.setdefault(r["id"], {})[r["arm"]] = r
        for n, (qid, arms) in enumerate(by_q.items(), start=1):
            raw, gov = arms.get("raw", {}), arms.get("governed", {})
            first = raw or gov
            kind, unit = first.get("type"), first.get("unit")
            raw_ok, gov_ok = bool(raw.get("correct")), bool(gov.get("correct"))
            questions.append({
                "run_order": order, "run": label, "n": n, "id": qid, "question": first["question"],
                "category": first["category"].replace("_", " ").capitalize(), "trap": first.get("trap") or "",
                "truth": fmt_answer(first.get("truth"), kind, unit),
                "raw_answer": fmt_answer(raw.get("answer"), kind, unit), "raw_correct": raw_ok,
                "raw_definition": raw.get("definition") or "", "raw_sql": _last_input(raw, "run_raw_sql"),
                "raw_tool_calls": len(raw.get("tool_calls", [])), "raw_error": raw.get("error") or "",
                "governed_answer": fmt_answer(gov.get("answer"), kind, unit), "governed_correct": gov_ok,
                "governed_query": _last_input(gov, "query_governed_metric"),
                "form_only_note": FORM_ONLY.get((run["model"], qid), "") if not raw_ok else "",
                "outcome": ("both right" if raw_ok and gov_ok else "only governed right" if gov_ok
                            else "only raw right" if raw_ok else "both wrong"),
            })
    return {"eval_scores": pd.DataFrame(scores), "eval_categories": pd.DataFrame(categories),
            "eval_questions": pd.DataFrame(questions)}
