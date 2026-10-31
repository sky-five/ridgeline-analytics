"""The "spreadsheet": the same numbers as the SQL models, computed a different way in plain Python.

The policy is shared on purpose (earned through a date = amount * elapsed days / period days,
truncated to the cent; ARR = 12 * month-end MRR per customer). The mechanics are not: revenue is
walked one day at a time instead of month overlaps, and ARR is a replay of contract changes instead
of an as-of join and window functions. If both agree to the cent, a bug would have to be made twice.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from revrec.billing import Billing, add_months


def _earned_through(amount: int, elapsed: int, total: int) -> int:
    q = abs(amount) * elapsed // total
    return q if amount >= 0 else -q


def _month(d: date) -> date:
    return d.replace(day=1)


def revenue_by_month(billing: Billing) -> dict[date, int]:
    out: dict[date, int] = defaultdict(int)
    for ln in billing.invoice_lines:
        total = (ln["period_end"] - ln["period_start"]).days
        d, elapsed, earned = ln["period_start"], 0, 0
        while d < ln["period_end"]:
            elapsed += 1
            now = _earned_through(ln["amount_cents"], elapsed, total)
            out[_month(d)] += now - earned
            earned, d = now, d + timedelta(days=1)
    return dict(out)


def closed_months(billing: Billing, as_of: date) -> list[date]:
    dates = [ln["period_start"] for ln in billing.invoice_lines] + [
        c["effective_on"] for c in billing.subscription_changes
    ]
    m, months = _month(min(dates)), []
    while m <= as_of:
        months.append(m)
        m = add_months(m, 1)
    return months


def deferred_closing(billing: Billing, as_of: date) -> dict[date, int]:
    revenue = revenue_by_month(billing)
    out, billed, earned = {}, 0, 0
    billed_by_month: dict[date, int] = defaultdict(int)
    for ln in billing.invoice_lines:
        billed_by_month[_month(ln["issued_on"])] += ln["amount_cents"]
    for m in closed_months(billing, as_of):
        billed += billed_by_month.get(m, 0)
        earned += revenue.get(m, 0)
        out[m] = billed - earned
    return out


def arr_bridge(billing: Billing, as_of: date) -> dict[date, dict[str, int]]:
    changes = sorted(billing.subscription_changes, key=lambda c: c["effective_on"])
    sub_mrr: dict[str, int] = {}
    sub_customer: dict[str, str] = {}
    prev: dict[str, int] = defaultdict(int)
    ever_paid: set[str] = set()
    out = {}
    i = 0
    for m in closed_months(billing, as_of):
        last_day = add_months(m, 1) - timedelta(days=1)
        while i < len(changes) and changes[i]["effective_on"] <= last_day:
            c = changes[i]
            sub_mrr[c["subscription_id"]] = c["mrr_cents"]
            sub_customer[c["subscription_id"]] = c["customer_id"]
            i += 1
        now: dict[str, int] = defaultdict(int)
        for sub, mrr in sub_mrr.items():
            now[sub_customer[sub]] += mrr

        row = dict.fromkeys(["new", "reactivation", "expansion", "contraction", "churn"], 0)
        for cust in set(now) | set(prev):
            before, after = prev[cust], now[cust]
            if before == after:
                continue
            if before == 0:
                kind = "reactivation" if cust in ever_paid else "new"
            elif after == 0:
                kind = "churn"
            else:
                kind = "expansion" if after > before else "contraction"
            row[kind] += 12 * (after - before)
        row["opening"] = 12 * sum(prev.values())
        row["closing"] = 12 * sum(now.values())
        out[m] = row

        ever_paid |= {c for c, v in now.items() if v > 0}
        prev = now
    return out
