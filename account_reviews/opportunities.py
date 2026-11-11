"""Opportunities: paying accounts whose measurement orders are falling or whose lead close rate dipped.

Each account's last 3 complete months are compared with the 3 months before. Two flags, each with a floor so a
quiet account can't trip it on a handful of rows:

- orders falling: at least MIN_ORDERS measurement orders in the earlier 3 months, and the last 3 months are down
  by ORDER_DROP or more.
- close rate dip: at least MIN_CLOSED closed leads in each window, and won / closed fell by RATE_DROP_PTS points
  or more.

Pure pandas, so the rules are unit-tested without a warehouse; `build` does the MetricFlow read.
"""
from datetime import date

import pandas as pd

WINDOW = 3  # months in each side of the comparison
MIN_ORDERS = 6  # earlier-window orders needed before a fall counts
ORDER_DROP = 0.40  # last window at least 40% below the earlier one
MIN_CLOSED = 8  # closed leads needed in each window before a close-rate dip counts
RATE_DROP_PTS = 0.15  # close rate down 15 points or more

METRICS = ["measurement_orders", "won_leads", "closed_leads"]


def _shift(month: date, k: int) -> date:
    return (pd.Timestamp(month) + pd.DateOffset(months=k)).date()


def window_totals(metrics: pd.DataFrame, last_month: date, window: int = WINDOW) -> pd.DataFrame:
    """Per account, METRICS summed over the earlier window (`*_before`) and the last window (`*_after`).

    `metrics` has columns account, month and METRICS; missing months count as zero, months outside the two
    windows are ignored.
    """
    m = metrics.copy()
    m["month"] = pd.to_datetime(m["month"]).dt.date
    after_start, before_start = _shift(last_month, -(window - 1)), _shift(last_month, -(2 * window - 1))
    m = m[(m["month"] >= before_start) & (m["month"] <= last_month)]
    m["side"] = ["after" if d >= after_start else "before" for d in m["month"]]
    sums = m.groupby(["account", "side"])[METRICS].sum().unstack("side", fill_value=0)
    sums.columns = [f"{metric}_{side}" for metric, side in sums.columns]
    for metric in METRICS:
        for side in ("before", "after"):
            col = f"{metric}_{side}"
            if col not in sums:
                sums[col] = 0
            sums[col] = sums[col].astype(int)
    out = sums.reset_index().rename(columns={"account": "account_id"})
    out["before_start"], out["after_start"], out["last_month"] = before_start, after_start, last_month
    return out


def flag(totals: pd.DataFrame) -> pd.DataFrame:
    """Add the two flags, the change behind each, and a plain reason line; keep only flagged accounts."""
    t = totals.copy()
    ob, oa = t["measurement_orders_before"], t["measurement_orders_after"]
    t["orders_change"] = (oa - ob) / ob.where(ob > 0)
    t["orders_falling"] = (ob >= MIN_ORDERS) & (t["orders_change"] <= -ORDER_DROP)

    cb, ca = t["closed_leads_before"], t["closed_leads_after"]
    t["close_rate_before"] = t["won_leads_before"] / cb.where(cb > 0)
    t["close_rate_after"] = t["won_leads_after"] / ca.where(ca > 0)
    t["close_rate_change"] = t["close_rate_after"] - t["close_rate_before"]
    # round before comparing so a dip shown as "15 points" on the page is the one that counts
    t["close_rate_dip"] = ((cb >= MIN_CLOSED) & (ca >= MIN_CLOSED)
                           & (t["close_rate_change"].round(4) <= -RATE_DROP_PTS))

    t = t[t["orders_falling"] | t["close_rate_dip"]].copy()
    t["reason"] = [reason(r) for _, r in t.iterrows()]
    t["flags"] = t["orders_falling"].astype(int) + t["close_rate_dip"].astype(int)
    return t


def reason(r: pd.Series) -> str:
    """One line per flag, built only from the window totals on the same row."""
    parts = []
    if r["orders_falling"]:
        parts.append(f"Measurement orders fell from {int(r['measurement_orders_before'])} to "
                     f"{int(r['measurement_orders_after'])} ({r['orders_change']:.0%}).")
    if r["close_rate_dip"]:
        parts.append(f"Lead close rate fell from {r['close_rate_before']:.0%} "
                     f"({int(r['won_leads_before'])} of {int(r['closed_leads_before'])}) to "
                     f"{r['close_rate_after']:.0%} ({int(r['won_leads_after'])} of {int(r['closed_leads_after'])}).")
    return " ".join(parts)


def opportunities(health: pd.DataFrame, metrics: pd.DataFrame, as_of: date,
                  reviewed: list[str] | None = None) -> pd.DataFrame:
    """The opportunities table: flagged paying accounts, both flags first, then by MRR (ties by account id).

    `health` has account_id, company_name, region, plan, mrr, health_score, risk_band. `reviewed` are the
    accounts that have a review page; their rows link to it.
    """
    from account_reviews.reviews import last_complete_month

    paying = health[health["mrr"] > 0]
    totals = window_totals(metrics[metrics["account"].isin(paying["account_id"])], last_complete_month(as_of))
    flagged = flag(totals).merge(paying, on="account_id", how="inner")
    flagged = flagged.sort_values(["flags", "mrr", "account_id"], ascending=[False, False, True])
    reviewed = set(reviewed or [])
    flagged["review_link"] = [f"/account-reviews/{a}" if a in reviewed else None for a in flagged["account_id"]]
    flagged.insert(0, "rank", range(1, len(flagged) + 1))
    flagged["as_of"] = as_of
    return flagged.reset_index(drop=True)


def build(health: pd.DataFrame, as_of: date, reviewed: list[str]) -> pd.DataFrame:
    """Read the governed metrics for the two windows (all accounts, by month) and flag."""
    from account_reviews.reviews import last_complete_month
    from semantic import query

    start = _shift(last_complete_month(as_of), -(2 * WINDOW - 1))
    metrics = query(METRICS, ["account", "metric_time__month"],
                    [f"{{{{ TimeDimension('metric_time', 'month') }}}} >= '{start}'"])
    metrics = metrics.rename(columns={"metric_time__month": "month"})
    return opportunities(health, metrics, as_of, reviewed)
