"""The book health dashboard tables, from the committed results only (no warehouse needed).

`python -m book_health` writes results/; scripts/export_reporting.py turns them into reporting.book_* tables for
the Evidence page. The book is simulated with a fixed seed, so the page does not move with the nightly build.
"""
import json
import re

import pandas as pd

from book_health.run import (
    BACKTEST,
    BACKTEST_PATH,
    BRIEF,
    FORECAST,
    NAMES,
    PROVINCE_MONTH,
    SEGMENT_WATCH,
    SUMMARY,
)

RULE_LABELS = {"last_month": "Last month", "trailing_3": "3-month average", "trailing_12": "12-month average"}
WHOLE_BOOK = "Whole book"
SEGMENT_LABELS = {("AB", "home"): "Alberta home", ("ON", "auto"): "Ontario auto"}
FILES = (SUMMARY, PROVINCE_MONTH, BACKTEST, BACKTEST_PATH, FORECAST, SEGMENT_WATCH, BRIEF)


def _name(code: str) -> str:
    return WHOLE_BOOK if code == "all" else NAMES[code]


def _dates(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


def brief_rows(text: str) -> pd.DataFrame:
    """The brief's bullets, one row each: section, order, the bold lead (may be empty) and the rest, without
    markdown, so the page can print them in a loop."""
    rows, section = [], ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("- "):
            m = re.match(r"- \*\*(.+?)\*\*\s*(.*)", line)
            lead, rest = (m.group(1), m.group(2)) if m else ("", line[2:])
            rows.append({"section": section, "item_sort": len(rows), "lead": lead, "body": rest})
    return pd.DataFrame(rows)


def rate_actions(s: dict) -> pd.DataFrame:
    """Each rate action's 12 months before and after: renewals due, retention and mean rate change."""
    return pd.DataFrame([{
        "segment": SEGMENT_LABELS[(a["province"], a["product"])], "province": a["province"],
        "product": a["product"], "from_month": a["from"], "period": f"12 months {side}", "period_sort": i,
        **a[side],
    } for a in s["rate_actions"] for i, side in enumerate(("before", "after"))])


def summary_row(s: dict) -> pd.DataFrame:
    b, h, lc, rf = s["book"], s["hail"], s["late_claims"], s["retention_forecast"]
    sc = {r["rule"]: r for r in rf["scores"]}
    on6 = {r["rule"]: r for r in rf["ontario_first_6_months_after_rate_action"]}
    act = {a["province"]: a for a in s["rate_actions"]}
    on, ab = act["ON"], act["AB"]
    provs = s["provinces"]
    fastest = max(provs, key=lambda p: p["in_force_growth_yoy"])
    slowest = min(provs, key=lambda p: p["in_force_growth_yoy"])
    best = min(provs, key=lambda p: p["loss_ratio_12m"])
    worst = max(provs, key=lambda p: p["loss_ratio_12m"])
    ch = {c["channel"]: c for c in s["channels"]}
    return pd.DataFrame([{
        "first_month": s["first_month"][:7], "as_of": s["as_of"], "months": b["months"],
        "policies": b["policies"], "terms": b["terms"], "claims": b["claims"], "provinces": len(provs),
        "in_force": b["in_force"], "written_premium_12m": b["written_premium_12m"],
        "earned_premium_12m": b["earned_premium_12m"], "loss_ratio_12m": b["loss_ratio_12m"],
        "retention_12m": b["retention_12m"],
        "fastest_province": NAMES[fastest["province"]], "fastest_growth": fastest["in_force_growth_yoy"],
        "slowest_province": NAMES[slowest["province"]], "slowest_growth": slowest["in_force_growth_yoy"],
        "best_lr_province": NAMES[best["province"]], "best_lr": best["loss_ratio_12m"],
        "worst_lr_province": NAMES[worst["province"]], "worst_lr": worst["loss_ratio_12m"],
        "broker_retention": ch["broker"]["retention_12m"], "digital_retention": ch["digital"]["retention_12m"],
        "hail_date": h["date"], "hail_province": NAMES[h["province"]], "hail_claims": h["claims"],
        "hail_incurred": h["incurred"], "hail_lr_month": h["home_loss_ratio_that_month"],
        "hail_lr_year": h["home_loss_ratio_that_year"], "hail_lr_year_before": h["home_loss_ratio_year_before"],
        "ab_from": ab["from"][:7], "ab_rate_after": ab["after"]["mean_rate_change"],
        "ab_retention_before": ab["before"]["retention"], "ab_retention_after": ab["after"]["retention"],
        "on_from": on["from"][:7], "on_rate_before": on["before"]["mean_rate_change"],
        "on_rate_after": on["after"]["mean_rate_change"], "on_retention_before": on["before"]["retention"],
        "on_retention_after": on["after"]["retention"],
        "on_points_lost_per_point": round((on["before"]["retention"] - on["after"]["retention"])
                                          / (on["after"]["mean_rate_change"] - on["before"]["mean_rate_change"]), 2),
        "late_claims": lc["late_claims"], "late_incurred": lc["late_incurred"],
        "lr_3m_reported": lc["loss_ratio_3m_reported"], "lr_3m_with_late": lc["loss_ratio_3m_with_late"],
        "rule": RULE_LABELS[rf["rule"]], "forecasts_per_rule": sc[rf["rule"]]["forecasts"],
        "mae_best": sc[rf["rule"]]["mae_points"], "mae_last_month": sc["last_month"]["mae_points"],
        "mae_trailing_3": sc["trailing_3"]["mae_points"], "mae_trailing_12": sc["trailing_12"]["mae_points"],
        "on_bias_trailing_12": on6["trailing_12"]["bias_points"],
        "on_bias_trailing_3": on6["trailing_3"]["bias_points"],
        "next_3_due": rf["next_3_months"]["renewals_due"], "next_3_expected": rf["next_3_months"]["expected_renewed"],
        "next_3_retention": round(rf["next_3_months"]["expected_renewed"] / rf["next_3_months"]["renewals_due"], 4),
    }])


def tables() -> dict[str, pd.DataFrame]:
    """reporting.book_summary, _provinces, _province_month, _channels, _segments, _rate_actions, _backtest,
    _backtest_path, _forecast, _brief (empty if there are no results)."""
    if not all(p.exists() for p in FILES):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))

    provinces = pd.DataFrame(s["provinces"])
    provinces.insert(1, "province_name", provinces["province"].map(NAMES))

    pm = _dates(pd.read_csv(PROVINCE_MONTH), "month_start")
    pm.insert(2, "province_name", pm["province"].map(NAMES))

    seg = _dates(pd.read_csv(SEGMENT_WATCH), "month_start")
    seg.insert(0, "segment", [SEGMENT_LABELS[k] for k in zip(seg["province"], seg["product"], strict=True)])

    scores = pd.read_csv(BACKTEST)
    scores.insert(1, "province_name", scores["province"].map(_name))
    scores.insert(3, "rule_label", scores["rule"].map(RULE_LABELS))

    path = _dates(pd.read_csv(BACKTEST_PATH), "month_start")
    path.insert(1, "province_name", path["province"].map(_name))
    path.insert(4, "rule_label", path["rule"].map(RULE_LABELS))
    path["error_points"] = ((path["forecast"] - path["actual"]) * 100).round(2)

    fc = pd.read_csv(FORECAST)
    fc.insert(1, "province_name", fc["province"].map(NAMES))
    fc["month_start"] = pd.to_datetime(fc["month"]).dt.date

    return {
        "book_summary": summary_row(s), "book_provinces": provinces, "book_province_month": pm,
        "book_channels": pd.DataFrame(s["channels"]), "book_segments": seg, "book_rate_actions": rate_actions(s),
        "book_backtest": scores, "book_backtest_path": path, "book_forecast": fc,
        "book_brief": brief_rows(BRIEF.read_text(encoding="utf-8")),
    }
