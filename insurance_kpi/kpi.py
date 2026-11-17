"""The KPI tree on accident years 2024 and 2025, valued on 2026-06-30.

    combined ratio = loss ratio + expense ratio
    loss ratio     = incurred / earned premium = frequency x severity / average earned premium
    frequency      = claims / earned policy-years          (earned exposure)
    severity       = incurred / claims                     (incurred = paid + case reserve)
    avg premium    = earned premium / earned policy-years
    expense ratio  = commission ratio + admin ratio        (both over earned premium)

Premium, commission and exposure are earned day by day over each policy's term; a claim belongs to the accident year
of its loss date. The change in loss ratio from 2024 to 2025 is split exactly across frequency, severity and average
premium with the log-mean (LMDI) weights: each driver gets L(LR25, LR24) x ln(driver25 / driver24), where
L(a, b) = (a - b) / ln(a / b), and the average premium term carries a minus sign. The three parts add up to the change.
"""
import math

import duckdb
import pandas as pd

from insurance_kpi.simulate import ADMIN_COST_PER_POLICY_YEAR

YEARS = (2024, 2025)
LINES = ("auto", "home", "all")


def _base(con: duckdb.DuckDBPyConnection, schema: str) -> pd.DataFrame:
    """Exposure, premium, commission, claims and incurred by accident year, line and province."""
    years = ", ".join(str(y) for y in YEARS)
    return con.sql(f"""
        with earn as (
            select y.ay, p.policy_id, p.line, p.province, p.written_premium, p.commission_rate,
                   greatest(0, date_diff('day', greatest(p.start_date, make_date(y.ay, 1, 1)),
                                         least(p.end_date, make_date(y.ay + 1, 1, 1))))
                   / date_diff('day', p.start_date, p.end_date) as earned_share
            from {schema}.policies p cross join (select unnest([{years}]) as ay) y
        ), pol as (
            select ay, line, province, sum(earned_share) as exposure,
                   sum(earned_share * written_premium) as earned_premium,
                   sum(earned_share * written_premium * commission_rate) as commission
            from earn group by all
        ), clm as (
            select year(c.loss_date) as ay, p.line, p.province, count(*) as claims,
                   sum(c.paid + c.case_reserve) as incurred
            from {schema}.claims c join {schema}.policies p using (policy_id)
            where year(c.loss_date) in ({years}) group by all
        )
        select pol.ay, pol.line, pol.province, exposure, earned_premium, commission,
               coalesce(claims, 0) as claims, coalesce(incurred, 0) as incurred
        from pol left join clm using (ay, line, province)
        order by all""").df()


def _ratios(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["admin_cost"] = df["exposure"] * ADMIN_COST_PER_POLICY_YEAR
    df["frequency"] = df["claims"] / df["exposure"]
    df["severity"] = df["incurred"] / df["claims"]
    df["avg_earned_premium"] = df["earned_premium"] / df["exposure"]
    df["loss_ratio"] = df["incurred"] / df["earned_premium"]
    df["commission_ratio"] = df["commission"] / df["earned_premium"]
    df["admin_ratio"] = df["admin_cost"] / df["earned_premium"]
    df["expense_ratio"] = df["commission_ratio"] + df["admin_ratio"]
    df["combined_ratio"] = df["loss_ratio"] + df["expense_ratio"]
    return df


SUMS = ["exposure", "earned_premium", "commission", "claims", "incurred"]


def tree(con: duckdb.DuckDBPyConnection, schema: str = "clean") -> pd.DataFrame:
    """One row per accident year and line (auto, home, all) with every node of the tree."""
    base = _base(con, schema)
    by_line = base.groupby(["ay", "line"], as_index=False)[SUMS].sum()
    total = base.groupby("ay", as_index=False)[SUMS].sum().assign(line="all")
    out = pd.concat([by_line, total], ignore_index=True)
    out["line"] = pd.Categorical(out["line"], LINES, ordered=True)
    return _ratios(out.sort_values(["ay", "line"]).reset_index(drop=True)).assign(line=lambda d: d["line"].astype(str))


def segments(con: duckdb.DuckDBPyConnection, schema: str = "clean") -> pd.DataFrame:
    """The tree's leaves by line and province, for finding where a driver moved."""
    return _ratios(_base(con, schema))


def _logmean(a: float, b: float) -> float:
    return a if math.isclose(a, b) else (a - b) / math.log(a / b)


def change(t: pd.DataFrame) -> pd.DataFrame:
    """Each node in 2024 and 2025, its change, and its contribution in loss-ratio or combined-ratio points."""
    rows = []
    for line in LINES:
        a = t[(t["line"] == line) & (t["ay"] == YEARS[0])].iloc[0]
        b = t[(t["line"] == line) & (t["ay"] == YEARS[1])].iloc[0]
        w = _logmean(b["loss_ratio"], a["loss_ratio"])
        contrib = {
            "combined_ratio": b["combined_ratio"] - a["combined_ratio"],
            "loss_ratio": b["loss_ratio"] - a["loss_ratio"],
            "frequency": w * math.log(b["frequency"] / a["frequency"]),
            "severity": w * math.log(b["severity"] / a["severity"]),
            "avg_earned_premium": -w * math.log(b["avg_earned_premium"] / a["avg_earned_premium"]),
            "expense_ratio": b["expense_ratio"] - a["expense_ratio"],
            "commission_ratio": b["commission_ratio"] - a["commission_ratio"],
            "admin_ratio": b["admin_ratio"] - a["admin_ratio"],
        }
        parent = {"combined_ratio": "", "loss_ratio": "combined_ratio", "expense_ratio": "combined_ratio",
                  "frequency": "loss_ratio", "severity": "loss_ratio", "avg_earned_premium": "loss_ratio",
                  "commission_ratio": "expense_ratio", "admin_ratio": "expense_ratio"}
        for node, pts in contrib.items():
            rows.append((line, node, parent[node], a[node], b[node], b[node] / a[node] - 1, pts))
    return pd.DataFrame(rows, columns=["line", "node", "parent", f"ay{YEARS[0]}", f"ay{YEARS[1]}", "relative_change",
                                       "contribution_pts"])


def raw_vs_clean(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The all-lines loss ratio as a naive query over the raw exports would give it, against the cleaned one.

    The naive query sums every claim row by loss year (duplicates, orphans, out-of-term claims and sign errors
    included) over the earned premium of every policy row (test policies included)."""
    years = ", ".join(str(y) for y in YEARS)
    naive = con.sql(f"""
        select year(loss_date) as ay, count(*) as claims, sum(paid + case_reserve) as incurred
        from raw.claims where year(loss_date) in ({years}) group by all order by ay""").df()
    clean = tree(con)
    clean = clean[clean["line"] == "all"]
    raw_ep = tree(con, "raw")
    raw_ep = raw_ep[raw_ep["line"] == "all"][["ay", "exposure", "earned_premium"]]
    out = naive.merge(raw_ep, on="ay").merge(clean[["ay", "claims", "incurred", "loss_ratio", "frequency"]],
                                               on="ay", suffixes=("_raw", "_clean"))
    out["loss_ratio_raw"] = out["incurred_raw"] / out["earned_premium"]
    out["frequency_raw"] = out["claims_raw"] / out["exposure"]
    out["loss_ratio_gap_pts"] = out["loss_ratio_raw"] - out["loss_ratio"]
    return out.rename(columns={"loss_ratio": "loss_ratio_clean", "frequency": "frequency_clean"})[
        ["ay", "claims_raw", "claims_clean", "incurred_raw", "incurred_clean", "loss_ratio_raw", "loss_ratio_clean",
         "loss_ratio_gap_pts", "frequency_raw", "frequency_clean"]]
