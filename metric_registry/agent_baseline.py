"""A no-model baseline for the metric-registry analyst: a fixed phrase table plays the model's part.

It speaks the same client protocol as a real model (analyst/llm.py): on the first turn it picks one metric,
its filters and dates from the question's words and calls query_metrics; on the second it copies the value
into the answer block. A question with no known phrase, or one asking for a forecast or a change to data,
is refused. It runs in CI with no key, and it is what a model has to beat on the same golden questions.
"""
from __future__ import annotations

import calendar
import json
import re

from analyst.llm import Reply, ToolCall

REFUSE_WORDS = ("forecast", "predict", " will ", "next quarter", "next year", "change ", "delete", "update ",
                "set the", "salesperson", "profit", "margin", " why ")

# phrase -> metric; the longest phrase found wins
METRICS = {"incentive per unit": "incentive_per_unit", "spend per unit": "incentive_per_unit",
           "average transaction price": "average_transaction_price", "share of msrp": "incentive_share_of_msrp",
           "had at least one incentive": "incentive_penetration", "penetration": "incentive_penetration",
           "with an incentive": "incentivised_units", "customer cash": "customer_cash",
           "incentive spend": "incentive_spend", "spend on": "program_spend", "spent on": "program_spend",
           "revenue": "revenue", "msrp value": "msrp_value", "vehicles were sold": "units_sold",
           "vehicles sold": "units_sold", "were sold": "units_sold", "were leased": "units_sold",
           "were financed": "units_sold", "units": "units_sold"}

FILTERS = {"electric": ("vehicle__segment", "ev"), " ev ": ("vehicle__segment", "ev"),
           "sedan": ("vehicle__segment", "sedan"), "suv": ("vehicle__segment", "suv"),
           "truck": ("vehicle__segment", "truck"),
           **{f"{r} region": ("dealer__region", r) for r in ("north", "south", "east", "west")},
           "leased": ("sale__finance_type", "lease"), "financed": ("sale__finance_type", "finance"),
           "paid cash": ("sale__finance_type", "cash"),
           "last ten days of a quarter": ("sale__is_quarter_end", "true"),
           "quarter end": ("sale__is_quarter_end", "true"),
           "returning customer": ("sale__is_returning_customer", "true"),
           "apr subvention": ("program__program_type", "apr_subvention"),
           "lease support": ("program__program_type", "lease_support"),
           "loyalty": ("program__program_type", "loyalty"), "cash rebate": ("program__program_type", "cash_rebate")}

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}


def dates(q: str) -> tuple[str | None, str | None]:
    """(start, end) for "Q1 2026", "June 2026" or "in 2025"; (None, None) when the question has no period."""
    if m := re.search(r"\bq([1-4])\s+(\d{4})\b", q):
        quarter, year = int(m.group(1)), int(m.group(2))
        first, last = 3 * quarter - 2, 3 * quarter
        return f"{year}-{first:02d}-01", f"{year}-{last:02d}-{calendar.monthrange(year, last)[1]}"
    if m := re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", q):
        month, year = MONTHS[m.group(1)], int(m.group(2))
        return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"
    if m := re.search(r"\bin (\d{4})\b", q):
        return f"{m.group(1)}-01-01", f"{m.group(1)}-12-31"
    return None, None


def plan(question: str) -> dict | None:
    """query_metrics arguments for a question, or None to refuse."""
    q = " " + re.sub(r"[?.,]", " ", question.lower()) + " "
    if any(w in q for w in REFUSE_WORDS):
        return None
    hits = [p for p in METRICS if p in q]
    if not hits:
        return None
    metric = METRICS[max(hits, key=len)]
    filters = {}
    for phrase in sorted(FILTERS, key=len, reverse=True):
        if phrase in q:
            dim, value = FILTERS[phrase]
            filters.setdefault(dim, value)
    start, end = dates(q)
    args = {"metrics": [metric]}
    if filters:
        args["filters"] = filters
    if start:
        args |= {"start_date": start, "end_date": end}
    return args


def _block(answer, unit: str, metrics: list[str], refused: bool, note: str) -> str:
    return "```json\n" + json.dumps({"answer": answer, "unit": unit, "metrics": metrics, "refused": refused,
                                     "note": note}) + "\n```"


class KeywordClient:
    provider, model = "none", "keyword-baseline"

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        args = plan(messages[0]["content"])
        if args is None:
            return Reply(_block(None, "text", [], True, "no governed metric answers this"), [])
        if messages[-1]["role"] == "user":
            return Reply("", [ToolCall("call_0", "query_metrics", args)], stop="tool_use")
        result = json.loads(messages[-1]["content"])
        if "error" in result or len(result.get("rows", [])) != 1:
            return Reply(_block(None, "text", [], True, result.get("error", "not one row")), [])
        metric = args["metrics"][0]
        value = result["rows"][0][metric]
        unit = "share" if metric in ("incentive_share_of_msrp", "incentive_penetration") else \
            "count" if metric in ("units_sold", "incentivised_units") else "usd"
        return Reply(_block(value, unit, [metric], False, metric), [])
