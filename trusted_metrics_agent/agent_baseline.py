"""A no-model baseline for the trusted-metrics agent: a fixed phrase table plays the model's part.

It speaks the same client protocol as a real model (analyst/llm.py): on the first turn it picks one
query_metric call from the question's words (metric, month, and any department, location or level named),
on the second it copies the value into the answer block, or declines when the server declined. A question
with no known phrase, or one asking for a forecast, a reason, a person or a change to data, is refused. It
runs in CI with no key, and it is what a model has to beat on the same eval.
"""
from __future__ import annotations

import json
import re

from analyst.llm import Reply, ToolCall
from arr_source_of_truth.agent_baseline import months_in

REFUSE_WORDS = ("forecast", "predict", "will ", "next year", "delete", "update ", "remove", "change the",
                "why ", "should we", "emp_", "employee id", "named ", "market rate", "competitor")

# phrase -> metric; the longest phrase found wins, and "how many people" only when nothing else is named
GENERIC = {"how many people": "headcount", "employ": "headcount", "staff": "headcount"}
METRICS = {"headcount": "headcount",
           "hires": "hires", "hired": "hires", "joined": "hires",
           "leavers": "terminations", "left": "terminations", "terminations": "terminations",
           "resigned": "voluntary_terminations", "voluntary": "voluntary_terminations",
           "attrition": "attrition_rate_12m", "turnover": "attrition_rate_12m",
           "tenure": "avg_tenure_months", "payroll": "payroll_cost", "pay cost": "payroll_cost",
           "overtime": "overtime_share", "salary": "avg_base_salary", "salaries": "avg_base_salary"}
DEPARTMENTS = ("customer support", "engineering", "field operations", "finance", "people", "sales")
LOCATIONS = ("alberta", "british columbia", "ontario", "remote")


def plan(question: str) -> dict | None:
    """query_metric arguments for a question, or None to refuse."""
    q = " " + question.lower() + " "
    if any(w in q for w in REFUSE_WORDS):
        return None
    table = METRICS
    hits = [p for p in METRICS if re.search(rf"\b{p}\b", q)]
    if not hits:
        table, hits = GENERIC, [p for p in GENERIC if p in q]
    months = months_in(q)
    if not hits or not months:
        return None
    args = {"metric": table[max(hits, key=len)], "start_month": months[0]}
    filters = {}
    named = r"\b(in|left|joined|for) {}\b|\b{} (team|department)\b"
    if dept := next((d for d in DEPARTMENTS if re.search(named.format(d, d), q)), None):
        filters["department"] = dept.title()
    if loc := next((x for x in LOCATIONS if re.search(rf"\b(in|from) {x}\b", q)), None):
        filters["location"] = loc.title()
    if m := re.search(r"\blevel (\d)\b", q):
        filters["job_level"] = m.group(1)
    if filters:
        args["filters"] = filters
    return args


class KeywordClient:
    provider, model = "baseline", "keyword-baseline"

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not results:
            args = plan(messages[0]["content"])
            if args is None:
                return Reply(_block(None, refused=True, note="no governed metric for this question"), [])
            return Reply("", [ToolCall("call_0", "query_metric", args)], stop="tool_use")
        res = results[-1]
        if "declined" in res:
            return Reply(_block(None, declined=True, note=res["declined"]), [])
        rows = res.get("rows") or []
        if "error" in res or len(rows) != 1 or rows[0].get("value") is None:
            return Reply(_block(None, refused=True, note=res.get("error") or "no single value"), [])
        return Reply(_block(rows[0]["value"], unit=res["unit"], sources=[res["source"]]), [])


def _block(answer, unit="text", sources=(), declined=False, refused=False, note="") -> str:
    body = {"answer": answer, "unit": unit, "sources": list(sources), "declined": declined, "refused": refused,
            "note": note}
    return f"```json\n{json.dumps(body)}\n```"
