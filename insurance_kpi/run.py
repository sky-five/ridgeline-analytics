"""Write the insurance KPI starter's results from one in-memory DuckDB build:

- results/column_profile.csv: every raw column's type, nulls, distinct values, min and max;
- results/checks.csv: each data-quality check, what it flagged and how that scores against the planted faults;
- results/kpi_tree.csv: every node of the tree by accident year and line (cleaned data);
- results/kpi_change.csv: each node in 2024 and 2025 and its contribution to the change, in ratio points;
- results/kpi_segments.csv: the tree's leaves by line and province;
- results/kpi_tree.md: the tree as text, what moved and why, and what the cleaning changed;
- results/summary.json: the headline numbers, including the planted changes next to the measured ones.
"""
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from insurance_kpi import kpi
from insurance_kpi.profile import column_profile, load, run_checks, score_checks
from insurance_kpi.simulate import AUTO_RATE, AUTO_SEVERITY, HAIL, VALUATION, simulate

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
PROFILE, CHECKS, TREE, CHANGE, SEGMENTS, TREE_MD, SUMMARY = (
    RESULTS / n for n in ("column_profile.csv", "checks.csv", "kpi_tree.csv", "kpi_change.csv", "kpi_segments.csv",
                          "kpi_tree.md", "summary.json"))


def build() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    load(con, simulate())
    return con


def _csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, float_format="%.6g", lineterminator="\n")


def severity_interval(con: duckdb.DuckDBPyConnection, line: str) -> tuple[float, float]:
    """Half-width (95%) of the 2024 -> 2025 relative severity change from sampling alone, by the delta method."""
    stats = con.sql(f"""
        select year(c.loss_date) as ay, count(*) as n, avg(c.paid + c.case_reserve) as m,
               stddev_samp(c.paid + c.case_reserve) as s
        from clean.claims c join clean.policies p using (policy_id)
        where year(c.loss_date) in (2024, 2025) and ('{line}' = 'all' or p.line = '{line}')
        group by all order by ay""").fetchall()
    (_, n1, m1, s1), (_, n2, m2, s2) = stats
    ratio = m2 / m1
    return ratio - 1, 1.96 * ratio * math.sqrt((s1 / m1) ** 2 / n1 + (s2 / m2) ** 2 / n2)


def _r(v, nd=4):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, float | np.floating):
        return round(float(v), nd)
    return v


def summary(con) -> dict:
    book_rows = con.sql("select (select count(*) from raw.policies), (select count(*) from raw.claims), "
                        "(select count(*) from clean.policies), (select count(*) from clean.claims)").fetchone()
    checks = score_checks(run_checks(con), simulate().planted)
    t, ch, rvc = kpi.tree(con), kpi.change(kpi.tree(con)), kpi.raw_vs_clean(con)
    seg = kpi.segments(con)
    home_freq = seg[seg["line"] == "home"].pivot(index="province", columns="ay", values="frequency")
    sev = {line: severity_interval(con, line) for line in ("auto", "home")}
    return {
        "valuation_date": VALUATION.isoformat(),
        "exports": {"policy_rows": book_rows[0], "claim_rows": book_rows[1]},
        "cleaned": {"policies": book_rows[2], "claims": book_rows[3]},
        "checks": {"run": len(checks), "with_planted_faults": int((checks["planted"] > 0).sum()),
                   "rows_flagged": int(checks["rows_flagged"].sum()), "caught": int(checks["caught"].sum()),
                   "planted": int(checks["planted"].sum()), "false_flags": int(checks["false_flags"].sum()),
                   "missed": int(checks["missed"].sum())},
        "tree": {f"{r.line}_{r.ay}": {k: _r(getattr(r, k)) for k in
                                      ("exposure", "earned_premium", "claims", "incurred", "frequency", "severity",
                                       "avg_earned_premium", "loss_ratio", "expense_ratio", "combined_ratio")}
                 for r in t.itertuples()},
        "change_pts": {line: {r.node: _r(r.contribution_pts) for r in ch[ch["line"] == line].itertuples()}
                       for line in kpi.LINES},
        "planted_vs_measured": {
            "auto_severity": {"planted": round(AUTO_SEVERITY[2] - 1, 4), "measured": round(sev["auto"][0], 4),
                              "sampling_95pct": round(sev["auto"][1], 4)},
            "home_severity": {"planted": 0.0, "measured": round(sev["home"][0], 4),
                              "sampling_95pct": round(sev["home"][1], 4)},
            "auto_rate": {"planted_on_new_policies": round(AUTO_RATE[2] - 1, 4),
                          "avg_earned_premium_change": _r(ch.query("line == 'auto' and node == 'avg_earned_premium'")
                                                          ["relative_change"].iloc[0])},
            "hail_frequency": {"planted": HAIL[3], "province": HAIL[1],
                               "measured": round(home_freq.loc[HAIL[1], 2025] / home_freq.loc[HAIL[1], 2024], 4)},
        },
        "raw_vs_clean": [{k: _r(v) for k, v in r.items()} for r in rvc.to_dict("records")],
    }


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _pts(v: float) -> str:
    return f"{v * 100:+.1f} pts"


NODES = [  # node, label, depth, format
    ("combined_ratio", "Combined ratio", 0, _pct),
    ("loss_ratio", "Loss ratio", 1, _pct),
    ("frequency", "Frequency (claims per policy-year)", 2, lambda v: f"{v:.4f}"),
    ("severity", "Severity (incurred per claim)", 2, lambda v: f"${v:,.0f}"),
    ("avg_earned_premium", "Average earned premium (divides)", 2, lambda v: f"${v:,.0f}"),
    ("expense_ratio", "Expense ratio", 1, _pct),
    ("commission_ratio", "Commission ratio", 2, _pct),
    ("admin_ratio", "Admin ratio", 2, _pct),
]


def tree_md(s: dict, ch: pd.DataFrame, rvc: pd.DataFrame) -> str:
    out = [f"# Insurance KPI tree, accident years 2024 and 2025 (valued {s['valuation_date']})", "",
           "Generated by `python -m insurance_kpi`; simulated data. Contributions add up to the parent's change.", ""]
    for line in kpi.LINES:
        out += [f"## {'All lines' if line == 'all' else line.capitalize()}", "", "```",
                f"{'':42}{'AY2024':>10}{'AY2025':>10}{'change':>12}"]
        c = ch[ch["line"] == line].set_index("node")
        for node, label, depth, fmt in NODES:
            r = c.loc[node]
            out.append(f"{'  ' * depth + label:42}{fmt(r['ay2024']):>10}{fmt(r['ay2025']):>10}"
                       f"{_pts(r['contribution_pts']):>12}")
        out += ["```", ""]
    pv = s["planted_vs_measured"]
    pts = {(r.line, r.node): r.contribution_pts for r in ch.itertuples()}
    a = {n: pts[("auto", n)] for n in ("loss_ratio", "frequency", "severity", "avg_earned_premium")}
    h = {n: pts[("home", n)] for n in ("loss_ratio", "frequency", "severity", "avg_earned_premium")}
    sev, rate, hail = pv["auto_severity"], pv["auto_rate"], pv["hail_frequency"]
    inside = abs(sev["measured"] - sev["planted"]) <= sev["sampling_95pct"]
    out += ["## What moved", "",
            f"- Auto: loss ratio {_pts(a['loss_ratio'])}: severity {_pts(a['severity'])}, frequency "
            f"{_pts(a['frequency'])}, average premium {_pts(a['avg_earned_premium'])}. Severity rose "
            f"{_pct(sev['measured'])}, +/- {_pct(sev['sampling_95pct'])} from sampling alone; the simulator planted "
            f"+{_pct(sev['planted'])}, {'inside' if inside else 'just outside'} that range (claim costs are "
            "heavy-tailed, and this is one draw). Average earned premium rose "
            f"{_pct(rate['avg_earned_premium_change'])}: the +{_pct(rate['planted_on_new_policies'])} rate on "
            "policies starting in 2025 is only about half earned in 2025, on top of the 3% yearly trend.",
            f"- Home: loss ratio {_pts(h['loss_ratio'])}: frequency {_pts(h['frequency'])}, severity "
            f"{_pts(h['severity'])} (it rose {_pct(pv['home_severity']['measured'])}, +/- "
            f"{_pct(pv['home_severity']['sampling_95pct'])} from sampling; nothing planted), "
            f"average premium {_pts(h['avg_earned_premium'])}. By province the frequency jump is in "
            f"{hail['province']}: {hail['measured']:.2f}x its 2024 rate (planted hail: {hail['planted']:.1f}x); "
            "the other provinces are in kpi_segments.csv.",
            f"- Expenses: the expense ratio moved {_pts(pts[('all', 'expense_ratio')])}, as the fixed admin cost "
            "per policy-year spreads over a higher average premium.", "",
            "## What the cleaning changed", "",
            "A naive query over the raw exports (every claim row, every policy row) against the cleaned tables, "
            "all lines:", "", "| AY | claims raw | claims clean | loss ratio raw | loss ratio clean | gap |",
            "|---|---:|---:|---:|---:|---:|"]
    for r in rvc.itertuples():
        out.append(f"| {r.ay} | {r.claims_raw:,} | {r.claims_clean:,} | {_pct(r.loss_ratio_raw)} | "
                   f"{_pct(r.loss_ratio_clean)} | {_pts(r.loss_ratio_gap_pts)} |")
    return "\n".join(out) + "\n"


def outputs(con) -> dict[Path, str]:
    s = summary(con)
    t = kpi.tree(con)
    ch, rvc = kpi.change(t), kpi.raw_vs_clean(con)
    return {
        PROFILE: _csv(column_profile(con)),
        CHECKS: _csv(score_checks(run_checks(con), simulate().planted)),
        TREE: _csv(t),
        CHANGE: _csv(ch),
        SEGMENTS: _csv(kpi.segments(con)),
        TREE_MD: tree_md(s, ch, rvc),
        SUMMARY: json.dumps(s, indent=2) + "\n",
    }
