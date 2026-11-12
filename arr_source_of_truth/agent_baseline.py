"""A no-model baseline for the ARR agent: a fixed phrase table plays the model's part.

It speaks the same client protocol as a real model (analyst/llm.py): on the first turn it picks one tool
call from the question's words, on the second it copies one field of the result into the answer block. A
question with no known phrase, or one asking for a forecast or a change to data, is refused. It runs in CI
with no key, and it is what a model has to beat on the same eval.
"""
from __future__ import annotations

import json
import re

from analyst.llm import Reply, ToolCall

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
MONTH_RE = re.compile(r"\b(\d{4})-(\d{2})\b|\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{4})\b")

REFUSE_WORDS = ("forecast", "predict", "will ", "next year", "delete", "update ", "remove", "change the",
                "fix the", "should we", "why ")

# phrase -> (tool, field); the longest phrase found wins
BRIDGE = {"closing arr": "closing_arr", "arr at the end": "closing_arr", "ending arr": "closing_arr",
          "opening arr": "opening_arr", "new arr": "new_arr", "new customers add": "new_arr",
          "expansion": "expansion_arr", "contraction": "contraction_arr", "churned arr": "churn_arr",
          "arr churned": "churn_arr", "churn": "churn_arr", "reactivation": "reactivation_arr",
          "paying customers": "paying_customers"}
WALK = {"crm booked": "crm_booked", "booked in the crm": "crm_booked", "crm book": "crm_booked",
        "duplicates": "duplicates", "won, not billed": "won_not_billed", "won not billed": "won_not_billed",
        "awaiting billing": "awaiting_billing", "amount fixes": "amount_fixes", "timing": "timing",
        "missing deals": "missing_deals", "seat changes": "seat_changes", "net change": "net_change",
        "cancellations": "cancellations", "billing started": "billing_sales_led",
        "billing new and upgrades": "billing_sales_led"}
STATUS = {"duplicate": "duplicate", "won but never billed": "won_not_billed", "won, not billed": "won_not_billed",
          "won not billed": "won_not_billed", "never billed": "won_not_billed", "awaiting billing": "awaiting_billing",
          "agree": "agrees", "annual": "annual_at_billed", "amount differ": "amount_differs",
          "different amount": "amount_differs"}


def months_in(q: str) -> list[str]:
    """Months in a question as YYYY-MM, in the order written ("September 2026", "sep 2026", "2026-09")."""
    out = []
    for y1, m1, mon, y2 in MONTH_RE.findall(q.lower()):
        if y1:
            out.append(f"{y1}-{m1}")
        else:
            out.append(f"{y2}-{next(i for name, i in MONTHS.items() if name.startswith(mon)):02d}")
    return out


def _longest(q: str, table: dict) -> str | None:
    hits = [p for p in table if p in q]
    return table[max(hits, key=len)] if hits else None


def plan(question: str) -> tuple[str, dict, str] | None:
    """(tool, arguments, field to read) for a question, or None to refuse."""
    q = " " + question.lower() + " "
    if any(w in q for w in REFUSE_WORDS):
        return None
    if m := re.search(r"\bopp_\d+\b", q):
        return "find_deals", {"deal_id": m.group()}, "status"
    months = months_in(q)
    if "how many" in q and "deal" in q and (status := _longest(q, STATUS)):
        args = {"close_month": months[0]} if len(months) == 1 else {}
        return "deal_status_counts", args, f"status:{status}"
    if len(months) >= 2 and (field := _longest(q, WALK)):
        return "arr_walk_range", {"first_month": months[0], "last_month": months[-1]}, field
    if len(months) == 1:
        field = _longest(q, WALK)
        bfield = _longest(q, BRIDGE)
        if field and (not bfield or len(max((p for p in WALK if p in q), key=len))
                      >= len(max((p for p in BRIDGE if p in q), key=len))):
            return "arr_walk", {"month": months[0]}, field
        if bfield:
            return "arr_bridge", {"month": months[0]}, bfield
    return None


def _block(answer, unit: str, models: list[str], refused: bool, note: str) -> str:
    return "```json\n" + json.dumps({"answer": answer, "unit": unit, "models": models, "refused": refused,
                                     "note": note}) + "\n```"


class KeywordClient:
    provider, model = "none", "keyword-baseline"

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        question = messages[0]["content"]
        p = plan(question)
        if p is None:
            return Reply(_block(None, "text", [], True, "no ARR model answers this"), [])
        tool, args, field = p
        if messages[-1]["role"] == "user":
            return Reply("", [ToolCall("call_0", tool, args)], stop="tool_use")
        result = json.loads(messages[-1]["content"])
        if "error" in result:
            return Reply(_block(None, "text", [], True, result["error"]), [])
        if field == "status":
            deals = result["deals"]
            if not deals:
                return Reply(_block(None, "text", [], True, "no such deal"), [])
            return Reply(_block(deals[0]["status"], "text", [result["model"]], False, "match status"), [])
        if field.startswith("status:"):
            row = [s for s in result["statuses"] if s["status"] == field[7:]]
            return Reply(_block(row[0]["deals"] if row else 0, "count", [result["model"]], False, field[7:]), [])
        unit = "count" if field == "paying_customers" else "usd"
        return Reply(_block(result[field], unit, [result["model"]], False, field), [])
