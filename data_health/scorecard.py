"""Table health scorecard: is each source table fresh, about as big as usual, and no emptier than usual?

Every table is judged against its own last 28 days, so a quiet CRM table and a busy event feed are each held
to their own normal. Three checks per table, each graded green, amber or red:

- freshness: hours from the table's last row (updated_at) to the end of the day, against the longest gap
  between rows in the last 28 days (at least 24 h). Over that gap is amber, over three times it is red.
- volume: rows that arrived on the day (updated_at on the day), against the daily counts of the last 28 days.
  The spread is the larger of their standard deviation and the square root of the mean, so small tables
  are not flagged for ordinary noise. More than 3 spreads away is amber, more than 6 is red.
- null rate: for each column, the share of the day's rows that are empty, against the same column's share in
  the last 28 days. More empties than usual by more than 3 spreads is amber, by more than 6 is red. The
  spread is the larger of the day-to-day spread and the binomial spread for the day's row count, with a
  floor of one percentage point.

A table's grade is its worst check, and its reason is that check's one-line explanation.
"""
import math

import pandas as pd

WINDOW_DAYS = 28
AMBER, RED = 3.0, 6.0
STALE_RED = 3  # red when the last row is older than this many times the longest usual gap
GRADES = ["green", "amber", "red"]
CHECKS = ["freshness", "volume", "null_rate"]
SKIP_COLUMNS = {"updated_at", "_dlt_load_id", "_dlt_id"}


def _worst(*grades: str) -> str:
    return max(grades, key=GRADES.index)


def _grade_z(z: float) -> str:
    return "red" if z > RED else "amber" if z > AMBER else "green"


def _hours(td: pd.Timedelta) -> float:
    return td.total_seconds() / 3600


def freshness(ts: pd.Series, day_start: pd.Timestamp) -> dict:
    day_end = day_start + pd.Timedelta(days=1)
    seen = ts[ts < day_end]
    if seen.empty:
        return {"grade": "red", "reason": "no rows at all", "hours_since_last_row": None}
    last = seen.max()
    age = _hours(day_end - last)
    window = seen[seen >= day_start - pd.Timedelta(days=WINDOW_DAYS)].sort_values()
    gaps = window.diff().dropna()
    usual = max(_hours(gaps.max()) if len(gaps) else 0.0, 24.0)
    grade = "green" if age <= usual else "amber" if age <= STALE_RED * usual else "red"
    reason = f"last row {_fmt_hours(age)} before the day ended (longest gap in {WINDOW_DAYS} days: {_fmt_hours(usual)})"
    return {"grade": grade, "reason": reason, "hours_since_last_row": round(age, 1)}


def _fmt_hours(h: float) -> str:
    return f"{h * 60:.0f} min" if h < 1 else f"{h:.0f} h" if h < 72 else f"{h / 24:.1f} days"


def _daily(df: pd.DataFrame, day_start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """The day's rows, the window's rows, and the window's days."""
    days = pd.date_range(day_start - pd.Timedelta(days=WINDOW_DAYS), periods=WINDOW_DAYS, freq="D")
    d = df.updated_at.dt.floor("D")
    return df[d == day_start], df[(d >= days[0]) & (d < day_start)], days


def volume(today: pd.DataFrame, window: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    counts = window.updated_at.dt.floor("D").value_counts().reindex(days, fill_value=0)
    mean, sd = counts.mean(), counts.std(ddof=0)
    spread = max(sd, math.sqrt(mean), 1.0)
    n = len(today)
    z = (n - mean) / spread
    grade = _grade_z(abs(z))
    direction = "above" if z > 0 else "below"
    reason = (f"{n:,} rows, usual {mean:,.0f} a day" if grade == "green"
              else f"{n:,} rows, {abs(z):.1f} spreads {direction} the usual {mean:,.0f} a day")
    return {"grade": grade, "reason": reason, "rows_today": n, "usual_rows": round(mean, 1)}


def null_rate(today: pd.DataFrame, window: pd.DataFrame, days: pd.DatetimeIndex, skip: set[str]) -> dict:
    n = len(today)
    if n == 0:
        return {"grade": "green", "reason": "no rows to check for empty values", "worst_column": None,
                "null_share_today": None, "null_share_usual": None}
    wday = window.updated_at.dt.floor("D")
    worst = None
    for col in today.columns:
        if col in skip:
            continue
        share = today[col].isna().mean()
        usual = window[col].isna().mean() if len(window) else 0.0
        daily = window[col].isna().groupby(wday).mean() if len(window) else pd.Series(dtype=float)
        spread = max(daily.std(ddof=0) if len(daily) > 1 else 0.0, math.sqrt(usual * (1 - usual) / n), 0.01)
        z = (share - usual) / spread
        if worst is None or z > worst[0]:
            worst = (z, col, share, usual)
    z, col, share, usual = worst
    grade = _grade_z(z)
    reason = (f"{col} {share:.0%} empty, usually {usual:.0%}" if grade != "green"
              else f"no column emptier than usual (closest: {col} {share:.0%}, usually {usual:.0%})")
    return {"grade": grade, "reason": reason, "worst_column": col, "null_share_today": round(share, 4),
            "null_share_usual": round(usual, 4)}


def score_table(df: pd.DataFrame, day: str, primary_key: str | None = None) -> dict:
    """One scorecard row for one table on one day. df needs an updated_at column."""
    day_start = pd.Timestamp(day)
    df = df[df.updated_at < day_start + pd.Timedelta(days=1)]
    today, window, days = _daily(df, day_start)
    f = freshness(df.updated_at, day_start)
    v = volume(today, window, days)
    nr = null_rate(today, window, days, SKIP_COLUMNS | ({primary_key} - {None}))
    checks = {"freshness": f, "volume": v, "null_rate": nr}
    grade = _worst(*(c["grade"] for c in checks.values()))
    if grade == "green":
        reason = f"{v['reason']}; last row {_fmt_hours(f['hours_since_last_row'])} before midnight; nulls as usual"
    else:
        reason = next(c["reason"] for c in checks.values() if c["grade"] == grade)
    return {
        "grade": grade, "reason": reason,
        **{f"{name}_grade": c["grade"] for name, c in checks.items()},
        "rows_today": v["rows_today"], "usual_rows": v["usual_rows"],
        "hours_since_last_row": f["hours_since_last_row"],
        "worst_null_column": nr["worst_column"], "null_share_today": nr["null_share_today"],
        "null_share_usual": nr["null_share_usual"],
    }


def scorecard(tables: dict[str, pd.DataFrame], day: str, primary_keys: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per table, worst grade first."""
    keys = primary_keys or {}
    rows = [{"table_name": name, "day": pd.Timestamp(day).date(), **score_table(df, day, keys.get(name))}
            for name, df in tables.items()]
    out = pd.DataFrame(rows)
    order = out.grade.map({"red": 0, "amber": 1, "green": 2})
    return out.assign(_o=order).sort_values(["_o", "table_name"]).drop(columns="_o").reset_index(drop=True)


def source_tables(world: dict) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """The simulator's tables as the loader sees them (internal columns dropped), and their primary keys."""
    from pipelines.engine import TABLES

    tables = {name: world[name].drop(columns=[c for c in spec.internal_cols if c in world[name]])
              for name, spec in TABLES.items()}
    return tables, {name: spec.primary_key for name, spec in TABLES.items()}


def main() -> None:
    import argparse
    import sys

    from data_health.batches import TABLE_FAULTS, arrivals, inject_table
    from pipelines.engine import TABLES

    p = argparse.ArgumentParser(prog="python -m data_health.scorecard")
    p.add_argument("--day", default="2026-06-30", help="day to grade (default: the last day of the cached history)")
    p.add_argument("--inject", choices=sorted(TABLE_FAULTS), help="break one table on purpose")
    p.add_argument("--table", default="events", help="table to break with --inject (default: events)")
    args = p.parse_args()

    tables = arrivals(args.day, WINDOW_DAYS)
    if args.inject:
        tables = inject_table(args.inject, tables, args.table, args.day)
    card = scorecard(tables, args.day, {name: spec.primary_key for name, spec in TABLES.items()})
    counts = card.grade.value_counts()
    print(f"table health on {args.day}: " + ", ".join(f"{counts.get(g, 0)} {g}" for g in GRADES)
          + (f" (injected: {args.inject} on {args.table})" if args.inject else ""))
    print(card[["table_name", "grade", *[f"{c}_grade" for c in CHECKS], "reason"]].to_string(index=False))
    sys.exit(1 if (card.grade == "red").any() else 0)


if __name__ == "__main__":
    main()
