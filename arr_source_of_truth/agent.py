"""An agent that answers ARR questions only through this folder's dbt models, and refuses the rest.

    python -m arr_source_of_truth.agent "What was closing ARR at the end of September 2026?"
    python -m arr_source_of_truth.agent --provider gemini "How many deals are duplicates?"

It gets four read-only tools over the ARR warehouse (warehouse/arr.duckdb), one per question shape:
the bridge for a month, the CRM-to-billing walk for a month or a range, deal counts by match status, and
a deal lookup. There is no SQL tool, so it can't pick its own definition of ARR. Every tool result names
the model it came from.

After the model answers, `check` holds the answer back (it becomes a refusal) unless:
- it cites at least one model, and only models a tool actually read in this conversation, and
- every number in the answer appears in a tool result (a sum or estimate of its own is not allowed).

The model client is analyst/llm.py's (Gemini's free tier, Claude, or the no-model baseline in
agent_baseline.py). Caps: MAX_TURNS model calls and MAX_TOKENS tokens per question.
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from analyst import llm
from analyst.prompt import parse_answer
from arr_source_of_truth.load import DEFAULT_DB

MAX_TURNS = 6
MAX_TOKENS = 60_000
MODELS = ("arr_bridge", "arr_booking_walk", "arr_deal_matches")

BRIDGE_COLS = ["opening", "new", "reactivation", "expansion", "contraction", "churn", "closing"]
WALK_COLS = ["crm_booked", "duplicates", "won_not_billed", "awaiting_billing", "amount_fixes", "timing",
             "missing_deals", "billing_sales_led", "seat_changes", "cancellations", "net_change"]
STATUSES = ("agrees", "annual_at_billed", "amount_differs", "duplicate", "won_not_billed", "awaiting_billing")

SYSTEM = """You answer questions about ARR (annual recurring revenue) for Ridgeline, a SaaS company selling \
software to roofing contractors. All data is synthetic. Billing is the source of truth for ARR; CRM deals are \
matched to the billing change each one should have started.

Use only the tools. Each result names the dbt model it came from:
- arr_bridge: opening, new, reactivation, expansion, contraction, churn and closing ARR, and paying customers, \
per month (USD).
- arr_booking_walk: per month, CRM booked ARR walked to billing ARR: duplicates, won not billed, awaiting \
billing, amount fixes, timing, missing deals, billing new + upgrades, seat changes, churn and cancellations, \
net change (USD; deductions are negative). The range tool gives totals over several months.
- arr_deal_matches: closed-won deals and how each agrees with billing (status), with booked and billed ARR.

Rules:
- Answer with a number or a status exactly as a tool returned it. Do not add, average, forecast or estimate.
- If the tools can't answer the question (other metrics, other data, forecasts, changes to data, anything \
not about these models), refuse. Do not guess.
- Months are YYYY-MM. Money is USD.

End your reply with one fenced json block, and nothing after it:
```json
{"answer": <number or text exactly as a tool returned it, or null when you refuse>,
 "unit": "<usd | count | text>",
 "models": ["<every model the answer came from>"],
 "refused": <true or false>,
 "note": "<one short sentence>"}
```"""

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _usd(cents) -> int | float:
    d = int(cents) / 100
    return int(d) if d == int(d) else d


class ArrTools:
    """The agent's tools: plain methods returning JSON-ready dicts, read-only on the ARR warehouse."""

    def __init__(self, db: Path = DEFAULT_DB):
        self.con = duckdb.connect(str(db), read_only=True)

    def close(self) -> None:
        self.con.close()

    def _months(self) -> list[str]:
        return [m for (m,) in self.con.execute(
            "select strftime(month_start, '%Y-%m') from arr_bridge order by month_start").fetchall()]

    def _bad_month(self, month: str) -> dict | None:
        months = self._months()
        if not MONTH.match(str(month)):
            return {"error": f"month must be YYYY-MM, got {month!r}"}
        if month not in months:
            return {"error": f"no closed month {month}; months available: {months[0]} to {months[-1]}"}
        return None

    def arr_bridge(self, month: str) -> dict:
        """Opening, new, reactivation, expansion, contraction, churn and closing ARR (USD) and paying
        customers at the end of one month.

        Args:
            month: Month as YYYY-MM, e.g. 2026-09.
        """
        if err := self._bad_month(month):
            return err
        row = self.con.execute(
            f"select {', '.join(c + '_arr_cents' for c in BRIDGE_COLS)}, paying_customers from arr_bridge "
            "where strftime(month_start, '%Y-%m') = ?", [month]).fetchone()
        out = {f"{c}_arr": _usd(v) for c, v in zip(BRIDGE_COLS, row, strict=False)}
        return {"model": "arr_bridge", "month": month, **out, "paying_customers": int(row[-1])}

    def arr_walk(self, month: str) -> dict:
        """The CRM-to-billing ARR walk for one month (USD): CRM booked, then each step to billing, then
        seat changes and churn to the net change in ARR.

        Args:
            month: Month as YYYY-MM, e.g. 2026-09.
        """
        if err := self._bad_month(month):
            return err
        row = self.con.execute(
            f"select {', '.join(c + '_cents' for c in WALK_COLS)} from arr_booking_walk "
            "where strftime(month_start, '%Y-%m') = ?", [month]).fetchone()
        return {"model": "arr_booking_walk", "month": month,
                **{c: _usd(v) for c, v in zip(WALK_COLS, row, strict=True)}}

    def arr_walk_range(self, first_month: str, last_month: str) -> dict:
        """Each walk step summed over a range of months, both ends included (USD).

        Args:
            first_month: First month as YYYY-MM.
            last_month: Last month as YYYY-MM.
        """
        for m in (first_month, last_month):
            if err := self._bad_month(m):
                return err
        if first_month > last_month:
            return {"error": "first_month is after last_month"}
        row = self.con.execute(
            f"select count(*), {', '.join(f'sum({c}_cents)' for c in WALK_COLS)} from arr_booking_walk "
            "where strftime(month_start, '%Y-%m') between ? and ?", [first_month, last_month]).fetchone()
        return {"model": "arr_booking_walk", "first_month": first_month, "last_month": last_month,
                "months": int(row[0]), **{c: _usd(v) for c, v in zip(WALK_COLS, row[1:], strict=True)}}

    def deal_status_counts(self, close_month: str | None = None) -> dict:
        """Closed-won deals per match status, with booked and billed ARR (USD). All deals, or the deals
        closed in one month. Statuses: agrees, annual_at_billed, amount_differs, duplicate, won_not_billed,
        awaiting_billing.

        Args:
            close_month: Month the deals closed, YYYY-MM; leave out for all deals.
        """
        where, params = "", []
        if close_month is not None:
            if err := self._bad_month(close_month):
                return err
            where, params = "where strftime(close_month, '%Y-%m') = ?", [close_month]
        rows = self.con.execute(
            f"select status, count(*), sum(booked_arr_cents), coalesce(sum(billed_arr_cents), 0) "
            f"from arr_deal_matches {where} group by status order by status", params).fetchall()
        return {"model": "arr_deal_matches", "close_month": close_month,
                "total_deals": sum(r[1] for r in rows),
                "statuses": [{"status": s, "deals": int(n), "booked_arr": _usd(b), "billed_arr": _usd(bb)}
                             for s, n, b, bb in rows]}

    def find_deals(self, deal_id: str | None = None, customer_id: str | None = None,
                   status: str | None = None, limit: int = 20) -> dict:
        """Closed-won deals with their match status, booked and billed ARR (USD) and billing start date.
        Filter by deal, customer or status (at least one).

        Args:
            deal_id: e.g. opp_00001.
            customer_id: e.g. cus_0448.
            status: One of agrees, annual_at_billed, amount_differs, duplicate, won_not_billed, awaiting_billing.
            limit: Most rows to return (at most 50).
        """
        filters = {"deal_id": deal_id, "customer_id": customer_id, "status": status}
        filters = {k: v for k, v in filters.items() if v is not None}
        if not filters:
            return {"error": "give deal_id, customer_id or status"}
        if status is not None and status not in STATUSES:
            return {"error": f"unknown status {status!r}; one of {', '.join(STATUSES)}"}
        where = " and ".join(f"{k} = ?" for k in filters)
        n = max(1, min(int(limit), 50))
        rows = self.con.execute(
            "select deal_id, customer_id, deal_type, strftime(close_date, '%Y-%m-%d'), booked_arr_cents, "
            "strftime(effective_on, '%Y-%m-%d'), billed_arr_cents, status from arr_deal_matches "
            f"where {where} order by close_date, deal_id", list(filters.values())).fetchall()
        deals = [{"deal_id": d, "customer_id": c, "deal_type": t, "close_date": cd, "booked_arr": _usd(b),
                  "billing_started": e, "billed_arr": None if bb is None else _usd(bb), "status": s}
                 for d, c, t, cd, b, e, bb, s in rows[:n]]
        return {"model": "arr_deal_matches", "matching_deals": len(rows), "deals": deals}

    def all(self) -> list:
        return [self.arr_bridge, self.arr_walk, self.arr_walk_range, self.deal_status_counts, self.find_deals]


# ---- the check between the model's answer and the person asking

_NUM = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")


def _numbers(value) -> set[float]:
    """Numbers in a tool result or an answer, as absolute values (a deduction can be said either way).
    Dates (2026-09, 2026-09-30) and ids (opp_00001, cus_0448) are not numbers."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int | float):
        return {abs(float(value))}
    if isinstance(value, dict):
        return set().union(*(_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    text = re.sub(r"\b\d{4}-\d{2}(-\d{2})?\b|\b\w+_\d+\b", " ", str(value))
    return {abs(float(m.replace("$", "").replace(",", ""))) for m in _NUM.findall(text)}


@dataclass
class Checked:
    delivered: dict | None  # what the person sees: the parsed answer, or None when refused or held back
    refused: bool
    held_back: str | None  # why the check stopped an answer, if it did


def check(text: str, tool_results: list[dict]) -> Checked:
    """Deliver the answer only if it cites models a tool read and every number came from a tool."""
    ans = parse_answer(text)
    if ans is None:
        return Checked(None, False, "no answer block")
    if ans.get("refused") or ans.get("answer") is None:
        return Checked(None, True, None)
    read = {r.get("model") for r in tool_results if "model" in r}
    cited = ans.get("models") or []
    if not cited:
        return Checked(None, False, "no model cited")
    if not set(cited) <= read:
        return Checked(None, False, f"cites {sorted(set(cited) - read)} but no tool read it")
    seen = _numbers(tool_results)
    made_up = sorted(n for n in _numbers(ans["answer"]) if n not in seen)
    if made_up:
        return Checked(None, False, f"numbers not in any tool result: {made_up}")
    return Checked(ans, False, None)


@dataclass
class Answer:
    question: str
    text: str
    delivered: dict | None
    refused: bool
    held_back: str | None
    tool_calls: list[dict]
    tool_results: list[dict]
    turns: int
    input_tokens: int
    output_tokens: int
    stopped: str

    def to_dict(self) -> dict:
        return asdict(self)


def ask(question: str, client: llm.Client, tools: ArrTools) -> Answer:
    """One question through the loop, then the check."""
    results: list[dict] = []
    fns = tools.all()

    def logged(fn):
        def wrapper(**kw):
            out = fn(**kw)
            results.append(out)
            return out
        wrapper.__name__, wrapper.__doc__, wrapper.__wrapped__ = fn.__name__, fn.__doc__, fn
        wrapper.__signature__ = inspect.signature(fn)
        wrapper.__annotations__ = fn.__annotations__
        return wrapper

    r = llm.run(question, client, [logged(f) for f in fns], SYSTEM, MAX_TURNS, MAX_TOKENS)
    c = check(r.text, results)
    calls = [{"name": n, "arguments": a} for n, a in zip(r.tool_calls, r.tool_inputs, strict=True)]
    return Answer(question, r.text, c.delivered, c.refused, c.held_back, calls, results, r.turns,
                  r.input_tokens, r.output_tokens, r.stopped)


def render(a: Answer) -> str:
    if a.delivered is not None:
        d = a.delivered
        return f"{d['answer']} {d.get('unit') or ''}".rstrip() + f"  (source: {', '.join(d['models'])})"
    if a.refused:
        return "Refused: the ARR models don't answer that."
    return f"Held back: {a.held_back}."


def main() -> None:
    from arr_source_of_truth.agent_baseline import KeywordClient

    p = argparse.ArgumentParser(prog="python -m arr_source_of_truth.agent")
    p.add_argument("question", nargs="+")
    p.add_argument("--provider", choices=["baseline", *sorted(llm.PROVIDERS)], default="baseline")
    p.add_argument("--model", default=None)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--json", action="store_true", help="print the whole record")
    args = p.parse_args()
    client = KeywordClient() if args.provider == "baseline" else llm.make_client(args.provider, args.model)
    tools = ArrTools(args.db)
    try:
        a = ask(" ".join(args.question), client, tools)
    finally:
        tools.close()
    print(json.dumps(a.to_dict(), indent=2, default=str) if args.json else render(a))
    sys.exit(0 if a.delivered is not None else 1)


if __name__ == "__main__":
    main()
