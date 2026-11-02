"""Answer key for the semantic eval: every answer comes from a governed metric query.

    python -m semantic_eval.answer_key            # compute and write answer_key.json
    python -m semantic_eval.answer_key --check    # recompute and compare with the committed key

Needs a built warehouse (scripts/run_all.py).
"""
import argparse
import json
import math
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yml"
KEY = HERE / "answer_key.json"

TYPES = {"number", "ratio", "text"}
ANSWERS = {"value", "top", "bottom"}
FIELDS = {"id", "question", "category", "metric", "group_by", "where", "pick", "answer", "by", "type",
          "absolute", "tolerance", "period_end", "trap"}


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(questions: list[dict], dimensions: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """Problems with the question set. `dimensions` maps metric -> its group-by names, from MetricFlow."""
    errors, seen = [], set()
    for q in questions:
        qid = q.get("id", "?")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        if extra := set(q) - FIELDS:
            errors.append(f"{qid}: unknown fields {sorted(extra)}")
        for f in ("question", "category", "metric", "type", "trap"):
            if not q.get(f):
                errors.append(f"{qid}: missing {f}")
        if q.get("type") not in TYPES:
            errors.append(f"{qid}: type must be one of {sorted(TYPES)}")
        answer = q.get("answer", "value")
        if answer not in ANSWERS:
            errors.append(f"{qid}: answer must be one of {sorted(ANSWERS)}")
        group_by = q.get("group_by", [])
        if answer != "value":
            if q.get("by") not in group_by:
                errors.append(f"{qid}: `by` must be one of its group_by")
            if q.get("type") != "text":
                errors.append(f"{qid}: a top/bottom answer is a text answer")
        for dim in q.get("pick", {}):
            if dim not in group_by:
                errors.append(f"{qid}: picks on {dim}, which it does not group by")
        if dimensions is not None:
            metric = q.get("metric")
            if metric not in dimensions:
                errors.append(f"{qid}: no governed metric {metric!r}")
                continue
            for dim in group_by:
                if _base_dim(dim) not in dimensions[metric]:
                    errors.append(f"{qid}: {metric} has no dimension {dim}")
    return errors


def _base_dim(name: str) -> str:
    """metric_time__year -> metric_time__day; cohort_period__cohort_month__year -> cohort_period__cohort_month."""
    if name.startswith("metric_time__"):
        return "metric_time__day"
    parts = name.split("__")
    return "__".join(parts[:2]) if len(parts) > 2 else name


def pick_answer(q: dict, rows: list[dict]):
    """Reduce a metric query's rows to the one answer the question asks for."""
    for dim, prefix in (q.get("pick") or {}).items():
        rows = [r for r in rows if str(r[dim]).startswith(str(prefix))]
    rows = [r for r in rows if _present(r[q["metric"]])]
    if not rows:
        raise ValueError(f"{q['id']}: no rows left after pick")
    answer = q.get("answer", "value")
    if answer == "value":
        if len(rows) != 1:
            raise ValueError(f"{q['id']}: expected one row, got {len(rows)}")
        value = float(rows[0][q["metric"]])
        return abs(value) if q.get("absolute") else value
    best = (max if answer == "top" else min)(rows, key=lambda r: float(r[q["metric"]]))
    by = best[q["by"]]
    return by.strftime("%Y-%m") if hasattr(by, "strftime") else str(by)


def _present(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def compute(q: dict):
    from semantic import query

    df = query([q["metric"]], q.get("group_by"), q.get("where"))
    return pick_answer(q, df.to_dict("records"))


def build(questions: list[dict] | None = None) -> dict:
    from semantic import list_metrics, query

    questions = questions or load_questions()
    errors = validate(questions, {m.name: m.dimensions for m in list_metrics()})
    if errors:
        raise ValueError("invalid questions:\n" + "\n".join(errors))
    last_day = query(["mrr"], ["metric_time__day"], order_by=["-metric_time__day"], limit=1)
    as_of = str(last_day["metric_time__day"].iloc[0])[:10]
    return {"as_of": as_of, "built_on": date.today().isoformat(),
            "answers": {q["id"]: compute(q) for q in questions}}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="compare with the committed key instead of writing it")
    args = p.parse_args()
    key = build()
    if args.check:
        old = json.loads(KEY.read_text(encoding="utf-8"))
        diff = {k: (old["answers"].get(k), v) for k, v in key["answers"].items() if old["answers"].get(k) != v}
        for k, (was, now) in diff.items():
            print(f"{k}: {was} -> {now}")
        print(f"{len(key['answers']) - len(diff)}/{len(key['answers'])} unchanged (key as of {old['as_of']}, "
              f"warehouse as of {key['as_of']})")
        return
    KEY.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    for k, v in key["answers"].items():
        print(f"{k:<32} {v}")
    print(f"-> {KEY}")


if __name__ == "__main__":
    main()
