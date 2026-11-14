"""Is the conversion drop real? Compare the per-request rate with the per-session rate around the logging change.

The detector does not know the change date. It looks for the week where requests per session jumps the most,
then asks whether bound sessions moved with it.
"""
import math

import duckdb
import pandas as pd


def two_proportion(x1: int, n1: int, x2: int, n2: int) -> dict:
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se
    se_diff = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {"before": p1, "after": p2, "diff_pp": 100 * (p2 - p1),
            "ci_pp": [100 * (p2 - p1 - 1.96 * se_diff), 100 * (p2 - p1 + 1.96 * se_diff)],
            "p_value": math.erfc(abs(z) / math.sqrt(2))}


def find_logging_break(weekly: pd.DataFrame) -> dict:
    """The week requests per session steps up the most, and whether shoppers changed that week."""
    w = weekly.sort_values("week").reset_index(drop=True)
    jumps = w["requests_per_session"].diff()
    i = int(jumps.idxmax())
    before, after = w.iloc[:i], w.iloc[i:]
    return {
        "week": str(pd.Timestamp(w.loc[i, "week"]).date()),
        "requests_per_session_before": float(before["requests"].sum() / before["sessions"].sum()),
        "requests_per_session_after": float(after["requests"].sum() / after["sessions"].sum()),
        "sessions_per_week_before": float(before["sessions"].mean()),
        "sessions_per_week_after": float(after["sessions"].mean()),
        "binds_per_week_before": float(before["bound_sessions"].mean()),
        "binds_per_week_after": float(after["bound_sessions"].mean()),
    }


def teardown(con: duckdb.DuckDBPyConnection) -> dict:
    weekly = con.execute("select * from mart.funnel_weekly order by week").df()
    brk = find_logging_break(weekly)
    cut = pd.Timestamp(brk["week"])
    pre, post = weekly[weekly.week < cut], weekly[weekly.week >= cut]

    def tot(df, col):
        return int(df[col].sum())

    per_request = two_proportion(tot(pre, "bound_sessions"), tot(pre, "quoted_requests"),
                                 tot(post, "bound_sessions"), tot(post, "quoted_requests"))
    per_session = two_proportion(tot(pre, "bound_sessions"), tot(pre, "quoted_sessions"),
                                 tot(post, "bound_sessions"), tot(post, "quoted_sessions"))
    # per-request rate = per-session rate x (quoted sessions / quoted requests); split the drop between them
    log_ratio = math.log(per_request["after"] / per_request["before"])
    denominator = math.log((tot(post, "quoted_sessions") / tot(post, "quoted_requests"))
                           / (tot(pre, "quoted_sessions") / tot(pre, "quoted_requests")))
    return {
        "logging_break": brk,
        "weeks_before": len(pre), "weeks_after": len(post),
        "quote_to_bind_per_request": per_request,
        "quote_to_bind_per_session": per_session,
        "relative_drop_per_request_pct": 100 * (per_request["after"] / per_request["before"] - 1),
        "share_of_drop_from_request_count_pct": 100 * denominator / log_ratio,
    }
