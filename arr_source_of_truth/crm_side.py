"""The CRM side: closed-won deals as a sales team would log them, made from the billing pack.

Billing (saas-world-sim's billing pack) is the record of what customers pay. Sales logs a closed-won deal
for every new subscription and every plan upgrade, a few days before billing starts it. Seat changes
happen in the product and never reach the CRM. On top of that, a few mistakes are planted on purpose,
each with a label so the reconciliation can be scored against data it never saw:

- missing_deal         a new subscription or upgrade that no one logged in the CRM
- annual_at_billed     an annual plan booked at what the customer pays (10 months) instead of its ARR (12)
- amount_typo          a booked amount off by 10-30%, rounded to $100
- duplicate            the same deal logged twice, a few days apart
- won_not_billed       an expansion marked won that billing never started

The deals are generated once from the full billing history with a fixed seed, then cut at the as-of date
by close date, so the same date always gives the same rows and an earlier date is a prefix of a later one.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from pipelines.engine import billing_as_of

SEED = 1606
HORIZON = date(2027, 12, 31)

P_MISSING, P_ANNUAL_AT_BILLED, P_TYPO, P_DUPLICATE, P_NOT_BILLED = 0.03, 0.25, 0.03, 0.02, 0.02

DEAL_COLUMNS = ["deal_id", "customer_id", "deal_type", "close_date", "booked_arr_cents"]


def _annual_subscriptions(lines: pd.DataFrame) -> set[str]:
    subs = lines[lines["kind"] == "subscription"]
    long = subs[(pd.to_datetime(subs["period_end"]) - pd.to_datetime(subs["period_start"])).dt.days > 40]
    return set(long["subscription_id"])


@lru_cache(maxsize=2)
def _full_history(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All deals to HORIZON, and their labels (deal_id or billing change -> planted defect)."""
    billing = billing_as_of(HORIZON)
    changes = billing["subscription_changes"].sort_values(["effective_on", "subscription_id"], kind="stable")
    annual = _annual_subscriptions(billing["invoice_lines"])
    rng = np.random.default_rng(seed)

    deals, labels, prev_mrr, seen_customer = [], [], {}, set()

    def add(customer, kind, close, cents, defect=None, change=None):
        deals.append({"customer_id": customer, "deal_type": kind, "close_date": close,
                      "booked_arr_cents": int(cents), "_defect": defect, "_change": change})

    for c in changes.itertuples(index=False):
        before = prev_mrr.get(c.subscription_id, 0)
        prev_mrr[c.subscription_id] = c.mrr_cents
        returning = c.customer_id in seen_customer
        seen_customer.add(c.customer_id)
        if c.reason not in ("new", "upgrade"):
            continue
        change_key = f"{c.subscription_id}@{c.effective_on}"
        delta = c.mrr_cents - before
        kind = "expansion" if c.reason == "upgrade" else ("win_back" if returning else "new_business")
        close = c.effective_on - timedelta(days=int(rng.integers(0, 15)))
        u = rng.random(4)
        if u[0] < P_MISSING:
            labels.append({"key": change_key, "defect": "missing_deal"})
            continue
        booked, defect = 12 * delta, None
        if c.reason == "new" and c.subscription_id in annual and u[1] < P_ANNUAL_AT_BILLED:
            booked, defect = 10 * delta, "annual_at_billed"
        elif u[2] < P_TYPO:
            factor = 1 + rng.choice([-1, 1]) * rng.uniform(0.10, 0.30)
            booked = round(12 * delta * factor / 10_000) * 10_000 or 10_000
            while booked in (12 * delta, 10 * delta):  # a typo must not look right, or like the annual mistake
                booked += 10_000
            defect = "amount_typo"
        add(c.customer_id, kind, close, booked, defect, change_key)
        if u[3] < P_DUPLICATE:
            add(c.customer_id, kind, close + timedelta(days=int(rng.integers(1, 8))), booked, "duplicate")
        if c.reason == "new" and rng.random() < P_NOT_BILLED:
            later = close + timedelta(days=int(rng.integers(40, 200)))
            add(c.customer_id, "expansion", later, round(12 * delta * rng.uniform(0.3, 1.0) / 10_000) * 10_000
                or 10_000, "won_not_billed")

    df = pd.DataFrame(deals).sort_values(["close_date", "customer_id"], kind="stable").reset_index(drop=True)
    df = df[df["close_date"] <= HORIZON].reset_index(drop=True)
    df["deal_id"] = [f"opp_{i:05d}" for i in range(1, len(df) + 1)]
    deal_labels = df[["deal_id", "_defect", "_change", "close_date"]].rename(
        columns={"_defect": "defect", "_change": "billing_change"})
    missing = pd.DataFrame(labels).rename(columns={"key": "billing_change"})
    return df[DEAL_COLUMNS], pd.concat([deal_labels, missing], ignore_index=True)


def won_deals_as_of(as_of: date, seed: int = SEED) -> pd.DataFrame:
    """Closed-won deals a CRM export would show at the end of `as_of`."""
    deals, _ = _full_history(seed)
    return deals[deals["close_date"] <= as_of].reset_index(drop=True)


def labels(seed: int = SEED) -> pd.DataFrame:
    """Planted defects: one row per deal (defect may be empty) plus one row per missing deal.

    `billing_change` is `<subscription_id>@<effective_on>` for deals that came from a billing change.
    Never loaded into the warehouse."""
    return _full_history(seed)[1].copy()
