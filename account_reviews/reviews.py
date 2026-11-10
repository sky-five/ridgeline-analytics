"""Pick the accounts to review and shape their tables. Pure pandas, so the shaping is unit-tested without a
warehouse; `build` does the warehouse and MetricFlow reads."""
from datetime import date
from pathlib import Path

import pandas as pd

from account_reviews.narrative import checked_draft

N_ACCOUNTS = 25  # the largest paying accounts by current MRR
MONTHS = 12  # complete months shown on each review

# governed metrics read per account per month; mrr at month end is the running sum of net_new_mrr
MONTHLY_METRICS = ["net_new_mrr", "tickets", "measurement_orders", "redo_orders", "leads", "won_leads",
                   "closed_leads"]
COUNT_COLUMNS = MONTHLY_METRICS[1:]


def pick_accounts(health: pd.DataFrame, n: int = N_ACCOUNTS) -> pd.DataFrame:
    """The n paying accounts with the most MRR now; ties go to the lower account id so the pick is stable."""
    return (health.sort_values(["mrr", "account_id"], ascending=[False, True])
            .head(n).reset_index(drop=True))


def last_complete_month(as_of: date) -> date:
    first = as_of.replace(day=1)
    return (pd.Timestamp(first) - pd.offsets.MonthBegin(1)).date()


def monthly_series(metrics: pd.DataFrame, accounts: list[str], last_month: date,
                   months: int = MONTHS) -> pd.DataFrame:
    """One row per account per month for the `months` complete months ending at last_month.

    `metrics` has columns account, month and MONTHLY_METRICS over the account's whole history (months with no
    activity may be missing). Missing months count as zero; mrr is the running sum of net_new_mrr from the
    first month on record, so it is the account's MRR at the end of each month.
    """
    m = metrics.copy()
    m["month"] = pd.to_datetime(m["month"]).dt.date
    m = m[m["account"].isin(accounts) & (m["month"] <= last_month)]
    first = min(m["month"].min(), _shift(last_month, -(months - 1))) if len(m) else _shift(last_month, -(months - 1))
    grid = pd.MultiIndex.from_product(
        [accounts, [d.date() for d in pd.date_range(first, last_month, freq="MS")]], names=["account", "month"])
    full = (m.set_index(["account", "month"])[MONTHLY_METRICS].reindex(grid)
            .fillna(0).reset_index())
    full["mrr"] = full.groupby("account")["net_new_mrr"].cumsum()
    keep = full[full["month"] > _shift(last_month, -months)].copy()
    for c in COUNT_COLUMNS:
        keep[c] = keep[c].astype(int)
    return keep.rename(columns={"account": "account_id"})[
        ["account_id", "month", "mrr", *MONTHLY_METRICS]].reset_index(drop=True)


def talking_points(header: pd.Series, series: pd.DataFrame) -> list[str]:
    """Plain, checkable lines for the top of a review, each built from numbers on the same page."""
    s = series.sort_values("month")
    start, end = float(s["mrr"].iloc[0]), float(s["mrr"].iloc[-1])
    points = []
    if end > start:
        points.append(f"MRR grew from ${start:,.0f} to ${end:,.0f} over the last {len(s)} months.")
    elif end < start:
        points.append(f"MRR fell from ${start:,.0f} to ${end:,.0f} over the last {len(s)} months.")
    else:
        points.append(f"MRR held at ${end:,.0f} over the last {len(s)} months.")
    closed, won = int(s["closed_leads"].sum()), int(s["won_leads"].sum())
    if closed:
        points.append(f"Closed {closed:,} homeowner leads and won {won:,} ({won / closed:.0%}).")
    orders, redos = int(s["measurement_orders"].sum()), int(s["redo_orders"].sum())
    if orders:
        points.append(f"Ordered {orders:,} measurement reports; asked for {redos:,} redo(s).")
    points.append(f"Opened {int(s['tickets'].sum()):,} support ticket(s).")
    points.append(f"Health score {int(header['health_score'])} ({header['risk_band'].replace('_', ' ')}).")
    return points


def review_tables(health: pd.DataFrame, metrics: pd.DataFrame, as_of: date,
                  n: int = N_ACCOUNTS) -> dict[str, pd.DataFrame]:
    """The reporting tables: account_review (header, talking points, checked summary) and account_review_monthly."""
    header = pick_accounts(health, n)
    header.insert(0, "rank", range(1, len(header) + 1))
    series = monthly_series(metrics, header["account_id"].tolist(), last_complete_month(as_of))
    by_account = dict(tuple(series.groupby("account_id")))
    header["talking_points"] = [" ".join(talking_points(row, by_account[row["account_id"]]))
                                for _, row in header.iterrows()]
    # the written summary; checked_draft raises if any number in it is not in the series or the header
    drafts = [checked_draft(row, by_account[row["account_id"]]) for _, row in header.iterrows()]
    header["summary"] = [text for text, _ in drafts]
    header["summary_numbers_checked"] = [n for _, n in drafts]
    header["as_of"] = as_of
    return {"account_review": header, "account_review_monthly": series}


def _shift(month: date, k: int) -> date:
    return (pd.Timestamp(month) + pd.DateOffset(months=k)).date()


def build(warehouse: Path) -> dict[str, pd.DataFrame]:
    """Read the health mart and the governed metrics from a built warehouse and shape the review tables."""
    import duckdb

    from semantic import query

    with duckdb.connect(str(warehouse)) as con:
        health = con.sql("""
            select h.account_id, h.company_name, d.region, d.crew_size, h.current_plan as plan,
                   h.mrr::double as mrr, d.signup_at::date as signup_date, h.health_score, h.risk_band,
                   h.logins_30d, h.proposals_30d, h.tickets_90d, h.redo_90d
            from main.fct_account_health h join main.dim_accounts d using (account_id)
        """).df()
        as_of = con.sql("select max(date_day)::date from main.fct_mrr_daily").fetchone()[0]
    picked = pick_accounts(health)["account_id"].tolist()
    ids = ", ".join(f"'{a}'" for a in picked)
    metrics = query(MONTHLY_METRICS, ["account", "metric_time__month"],
                    [f"{{{{ Entity('account') }}}} in ({ids})"])
    metrics = metrics.rename(columns={"metric_time__month": "month"})
    return review_tables(health, metrics, as_of)
