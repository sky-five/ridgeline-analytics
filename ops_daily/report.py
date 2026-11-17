"""The ops-daily dashboard tables, from the committed results only (no warehouse needed).

`python -m ops_daily` writes results/; scripts/export_reporting.py turns them into reporting.ops_* tables for the
Evidence page. The operation is simulated with a fixed seed, so the page does not move with the nightly build.
"""
import json
import re

import pandas as pd

from ops_daily.run import DEFINITIONS, FLAGS, METRIC_DAY, METRICS, SUMMARY, TODAY, _event_on, _fmt, _team, definitions

EVENT_LABELS = {"staff_cut": "Staff cut", "handle_time_creep": "Handle-time creep", "storm": "Storm"}
FILES = (SUMMARY, TODAY, FLAGS, METRIC_DAY, DEFINITIONS)


def _sort(metric: pd.Series) -> pd.Series:
    return metric.map({m: i for i, m in enumerate(METRICS)})


def so_what_rows(text: str) -> pd.DataFrame:
    """today.md's metric-by-metric paragraphs, one row per metric: label, definition and the paragraph after it,
    without markdown."""
    rows = []
    for m in re.finditer(r"^\*\*(.+?)\*\* \((.+?)\): (.+)$", text, flags=re.M):
        rows.append({"metric_sort": len(rows), "label": m.group(1), "definition": m.group(2), "body": m.group(3)})
    return pd.DataFrame(rows)


def summary_row(s: dict, flags: pd.DataFrame) -> pd.DataFrame:
    op, fr = s["operation"], s["flag_rule"]
    ev = {e["event"]: e for e in fr["events"]}
    return pd.DataFrame([{
        "first_day": s["first_day"], "as_of": s["as_of"],
        "as_of_label": pd.Timestamp(s["as_of"]).strftime("%A %Y-%m-%d"),
        "sites": len(s["sites"]), "lines": len(s["lines"]), "teams": len(s["sites"]) * len(s["lines"]),
        **op,
        "scored_from": fr["scored_from"], "scored_days": fr["scored_days"], "scored_values": fr["scored_values"],
        "flags": len(flags), "false_flags": fr["false_flags"], "false_flag_rate": fr["false_flag_rate"],
        "days_with_a_false_watchlist_item": fr["days_with_a_false_watchlist_item"],
        **{f"{k}_days_to_flag_cause": e["days_to_flag_cause"] for k, e in ev.items()},
    }])


def today_rows(s: dict) -> pd.DataFrame:
    """The three things to look at on the as-of day, as the page prints them."""
    defs = definitions()
    rows = []
    for w in s["watchlist_as_of"]:
        d = defs[w["metric"]]
        others = w["other_flags"].split(", ") if w["other_flags"] else []
        rows.append({
            "rank": w["rank"], "team": _team(w["site"], w["line"]), "site": w["site"], "line": w["line"],
            "metric": w["metric"], "metric_label": d["label"], "value": w["value"], "baseline": w["baseline"],
            "value_text": _fmt(w["metric"], w["value"]), "baseline_text": _fmt(w["metric"], w["baseline"]),
            "score": w["score"], "also_flagged": ", ".join(defs[m]["label"].lower() for m in others),
            "first_check": d["first_check"],
        })
    return pd.DataFrame(rows)


def metric_day(defs: dict) -> pd.DataFrame:
    df = pd.read_csv(METRIC_DAY)
    df["day"] = pd.to_datetime(df["day"]).dt.date
    df.insert(1, "team", [_team(s, ln) for s, ln in zip(df["site"], df["line"], strict=True)])
    df.insert(5, "metric_label", df["metric"].map(lambda m: defs[m]["label"]))
    df["flagged_value"] = df["value"].where(df["flagged"])
    return df


def flag_rows(defs: dict) -> pd.DataFrame:
    """Every flagged value, with the planted event it belongs to ("nothing planted" when the team had none)."""
    df = pd.read_csv(FLAGS)
    df["day"] = pd.to_datetime(df["day"]).dt.date
    df.insert(1, "team", [_team(s, ln) for s, ln in zip(df["site"], df["line"], strict=True)])
    df.insert(5, "metric_label", df["metric"].map(lambda m: defs[m]["label"]))
    df["value_text"] = [_fmt(m, v) for m, v in zip(df["metric"], df["value"], strict=True)]
    df["baseline_text"] = [_fmt(m, v) for m, v in zip(df["metric"], df["baseline"], strict=True)]
    events = [_event_on(r.site, r.line, r.day) for r in df.itertuples()]
    df["planted_event"] = [EVENT_LABELS[e] if e else "nothing planted" for e in events]
    return df


def backcheck_rows(s: dict, defs: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "event": EVENT_LABELS[e["event"]], "team": _team(e["site"], e["line"]), "from_day": e["from"],
        "cause": defs[e["cause_metric"]]["label"], "days_to_flag_cause": e["days_to_flag_cause"],
        "first_flag": e["first_flag"], "first_metric": defs[e["first_metric"]]["label"],
        "metrics_flagged": ", ".join(defs[m]["label"].lower() for m in e["metrics_flagged"]),
        "days_on_watchlist": e["days_on_watchlist"], "days_since_start": e["days_since_start"],
    } for e in s["flag_rule"]["events"]])


def false_flag_rows(s: dict, defs: dict) -> pd.DataFrame:
    by = s["flag_rule"]["false_flags_by_metric"]
    return pd.DataFrame([{"metric_sort": i, "metric": m, "metric_label": defs[m]["label"], "false_flags": by[m]}
                         for i, m in enumerate(METRICS)])


def min_change_text(d: dict) -> str:
    """The sheet's minimum move in words: 10 points of service level, 0.5 minutes, 25% of the usual count."""
    parts = []
    if float(d["min_change_abs"]):
        a = float(d["min_change_abs"])
        parts.append(f"{a:g} minutes" if d["unit"] == "minutes" else f"{100 * a:g} points")
    if float(d["min_change_rel"]):
        parts.append(f"{float(d['min_change_rel']):.0%} of the usual")
    return " and ".join(parts)


def definition_rows(defs: dict) -> pd.DataFrame:
    df = pd.DataFrame(defs.values())
    df["min_change"] = [min_change_text(d) for d in defs.values()]
    df.insert(0, "metric_sort", _sort(df["metric"]))
    for c in ("min_change_abs", "min_change_rel", "min_spread"):
        df[c] = df[c].astype(float)
    df["good_direction"] = df["good_direction"].map({"up": "higher", "down": "lower", "none": "neither: flagged either way"})
    return df.sort_values("metric_sort").reset_index(drop=True)


def tables() -> dict[str, pd.DataFrame]:
    """reporting.ops_summary, _today, _metric_day, _flags, _backcheck, _false_flags, _so_what, _definitions
    (empty if there are no results)."""
    if not all(p.exists() for p in FILES):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    defs = definitions()
    flags = flag_rows(defs)
    return {
        "ops_summary": summary_row(s, flags), "ops_today": today_rows(s), "ops_metric_day": metric_day(defs),
        "ops_flags": flags, "ops_backcheck": backcheck_rows(s, defs), "ops_false_flags": false_flag_rows(s, defs),
        "ops_so_what": so_what_rows(TODAY.read_text(encoding="utf-8")), "ops_definitions": definition_rows(defs),
    }
