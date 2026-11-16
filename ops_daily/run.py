"""Write the ops-daily results: results/summary.json (the operation, the back-check of the flag rule against the
planted events, today's watchlist), results/today.md (the three things to look at on the as-of day and a so-what
paragraph per metric), results/flags.csv (every flagged day, site, line and metric) and results/ops_day.csv (the
daily metrics per site and line, for the dashboard). Every number comes from the dbt marts."""
import csv
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ops_daily.simulate import AS_OF, EVENTS

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SUMMARY = RESULTS / "summary.json"
TODAY = RESULTS / "today.md"
FLAGS = RESULTS / "flags.csv"
OPS_DAY = RESULTS / "ops_day.csv"
DEFINITIONS = HERE / "dbt" / "seeds" / "metric_definitions.csv"
METRICS = ["calls_offered", "service_level", "abandon_rate", "avg_handle_minutes", "claims_opened", "claims_closed",
           "open_backlog"]


def definitions() -> dict[str, dict]:
    with DEFINITIONS.open(newline="") as f:
        return {r["metric"]: r for r in csv.DictReader(f)}


def _plain(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating | float):
        return round(float(v), 4)
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return v


def _rows(con, sql: str) -> list[dict]:
    return [{k: _plain(v) for k, v in r.items()} for r in con.sql(sql).df().to_dict("records")]


def _event_on(site: str, line: str, day) -> str | None:
    for name, s, ln, start, _ in EVENTS:
        if (s, ln) == (site, line) and day >= start:
            return name
    return None


def backcheck(con) -> dict:
    """How fast the rule found each planted event, and how often it flagged a team with nothing wrong."""
    flags = con.sql("select day, site, line, metric, score from ops_flags where flagged").df()
    flags["day"] = pd.to_datetime(flags["day"]).dt.date
    watch = con.sql("select day, site, line from ops_watchlist").df()
    watch["day"] = pd.to_datetime(watch["day"]).dt.date
    scored = con.sql("""select count(*) as n, min(day) as first_day from ops_flags
                         where baseline_days = 6""").fetchone()
    events = []
    for name, site, line, start, cause in EVENTS:
        hit = flags[(flags["site"] == site) & (flags["line"] == line) & (flags["day"] >= start)].sort_values("day")
        first, on_cause = hit.iloc[0], hit[hit["metric"] == cause].iloc[0]
        on_list = watch[(watch["site"] == site) & (watch["line"] == line) & (watch["day"] >= start)]
        events.append({"event": name, "site": site, "line": line, "from": start.isoformat(),
                       "first_flag": first["day"].isoformat(), "days_to_flag": (first["day"] - start).days,
                       "first_metric": first["metric"], "cause_metric": cause,
                       "days_to_flag_cause": (on_cause["day"] - start).days,
                       "metrics_flagged": sorted(hit["metric"].unique().tolist()),
                       "days_on_watchlist": int(on_list["day"].nunique()),
                       "days_since_start": (AS_OF - start).days + 1})
    false = flags[[_event_on(r.site, r.line, r.day) is None for r in flags.itertuples()]]
    false_watch = watch[[_event_on(r.site, r.line, r.day) is None for r in watch.itertuples()]]
    days = (AS_OF - scored[1]).days + 1
    return {
        "scored_from": scored[1].isoformat(), "scored_days": days, "scored_values": int(scored[0]),
        "events": events,
        "false_flags": int(len(false)),
        "false_flags_by_metric": {m: int((false["metric"] == m).sum()) for m in METRICS},
        "false_flag_rate": round(len(false) / scored[0], 4),
        "days_with_a_false_watchlist_item": int(false_watch["day"].nunique()),
    }


def ops_day(con) -> pd.DataFrame:
    df = con.sql("select * from fct_ops_day order by day, site, line").df()
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


def operation_day(df: pd.DataFrame) -> pd.DataFrame:
    """The whole operation per day (all sites and lines), with each metric as defined."""
    g = df.groupby("day")[["offered", "answered", "abandoned", "answered_within_60s", "handle_seconds",
                           "claims_opened", "claims_closed", "open_backlog"]].sum()
    return pd.DataFrame({
        "calls_offered": g["offered"].astype(float),
        "service_level": g["answered_within_60s"] / g["offered"],
        "abandon_rate": g["abandoned"] / g["offered"],
        "avg_handle_minutes": g["handle_seconds"] / g["answered"] / 60,
        "claims_opened": g["claims_opened"].astype(float),
        "claims_closed": g["claims_closed"].astype(float),
        "open_backlog": g["open_backlog"].astype(float),
    })


def summary(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        bc = backcheck(con)
        watch = _rows(con, f"""select w.rank, w.site, w.line, w.metric, w.value, w.baseline, round(w.score, 1) as score,
                                      w.other_flags
                               from ops_watchlist w where day = '{AS_OF}' order by rank""")
        df = ops_day(con)
        n_claims = con.sql("select count(*) from stg_ops__claims where opened_date >= '2026-01-01'").fetchone()[0]
    op = operation_day(df)
    window = op.loc[[d for d in op.index if d.year == AS_OF.year]]
    last = df[df["day"] == AS_OF]
    return {
        "as_of": AS_OF.isoformat(), "first_day": df["day"].min().isoformat(),
        "sites": sorted(df["site"].unique().tolist()), "lines": sorted(df["line"].unique().tolist()),
        "operation": {
            "calls_offered": int(df["offered"].sum()),
            "service_level": round(float(df["answered_within_60s"].sum() / df["offered"].sum()), 4),
            "abandon_rate": round(float(df["abandoned"].sum() / df["offered"].sum()), 4),
            "avg_handle_minutes": round(float(df["handle_seconds"].sum() / df["answered"].sum() / 60), 2),
            "claims_opened": int(n_claims),
            "claims_closed": int(df["claims_closed"].sum()),
            "open_backlog_as_of": int(last["open_backlog"].sum()),
            "open_backlog_median": float(window["open_backlog"].median()),
        },
        "flag_rule": bc,
        "watchlist_as_of": watch,
    }


def _fmt(metric: str, v: float) -> str:
    if metric in ("service_level", "abandon_rate"):
        return f"{100 * v:.1f}%"
    if metric == "avg_handle_minutes":
        return f"{v:.1f} min"
    return f"{v:,.0f}"


def _team(site: str, line: str) -> str:
    return f"{site.capitalize()} {line}"


def today(db: Path, s: dict) -> str:
    defs = definitions()
    with duckdb.connect(str(db), read_only=True) as con:
        df = ops_day(con)
        recent = con.sql(f"""select site, line, metric, count(*) as days, min(day) as since from ops_flags
                             where flagged and day > date '{AS_OF}' - interval 7 day group by all""").df()
    op = operation_day(df)
    same_wd = [d for d in op.index if d < AS_OF and d.weekday() == AS_OF.weekday()][-6:]
    lines = [f"# Operations: what to look at on {AS_OF:%A %Y-%m-%d}", "",
             "Simulated claims operation, three sites (east, central, west) x two lines (home, auto). Each metric is "
             "compared with the same weekday over the previous six weeks; see the README for the rule and "
             "[the definitions](../dbt/seeds/metric_definitions.csv).", "", "## Three things", ""]
    for w in s["watchlist_as_of"]:
        d = defs[w["metric"]]
        also = f" Also flagged: {', '.join(defs[m]['label'].lower() for m in w['other_flags'].split(', '))}." \
            if w["other_flags"] else ""
        lines.append(f"{w['rank']}. **{_team(w['site'], w['line'])}: {d['label'].lower()} "
                     f"{_fmt(w['metric'], w['value'])}**, usually {_fmt(w['metric'], w['baseline'])} on a "
                     f"{AS_OF:%A}.{also} First check: {d['first_check']}")
    lines += ["", "## Metric by metric", ""]
    for m in METRICS:
        d = defs[m]
        v, base = op.loc[AS_OF, m], float(np.median(op.loc[same_wd, m]))
        hit = recent[recent["metric"] == m].sort_values("days", ascending=False)
        if hit.empty:
            flagged = "No team was flagged on it in the last seven days, so nothing to do today."
        else:
            teams = "; ".join(f"{_team(r.site, r.line)} on {r.days} of the last 7 days" for r in hit.itertuples())
            flagged = f"Flagged: {teams}. So what: {d['first_check']}"
        lines.append(f"**{d['label']}** ({d['definition'][0].lower() + d['definition'][1:-1]}): "
                     f"{_fmt(m, v)} across the operation today against {_fmt(m, base)} on recent {AS_OF:%A}s. "
                     f"{flagged}")
        lines.append("")
    return "\n".join(lines)


def flags_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("""select day, site, line, metric, value, baseline, spread, score from ops_flags where flagged
                        order by day, site, line, metric""").df()
    for c in ("value", "baseline", "spread", "score"):
        df[c] = df[c].round(4)
    return df.to_csv(index=False, lineterminator="\n")


def ops_day_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = ops_day(con)
    for c in ("service_level", "abandon_rate", "avg_handle_minutes"):
        df[c] = df[c].round(4)
    df["staffed_hours"] = df["staffed_hours"].astype(float)
    return df.drop(columns=["calls_offered"]).to_csv(index=False, lineterminator="\n")


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"
