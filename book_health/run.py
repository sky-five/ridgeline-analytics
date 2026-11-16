"""Write the book health results: results/summary.json, results/province_month.csv, the retention back-test
(results/retention_backtest.csv) and forecast (results/retention_forecast.csv), and the one-page brief
results/brief.md; for the dashboard, the two watched segments by month (results/segment_watch.csv) and the
one-month-ahead back-test path (results/backtest_path.csv). Every number comes from the dbt marts, the
back-test, or labels.late_claims."""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from book_health import forecast as fc
from book_health.simulate import AS_OF, HAIL_DATE, HAIL_PROVINCE, RATE_ACTIONS

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
PROVINCE_MONTH = RESULTS / "province_month.csv"
BACKTEST = RESULTS / "retention_backtest.csv"
FORECAST = RESULTS / "retention_forecast.csv"
BRIEF = RESULTS / "brief.md"
SEGMENT_WATCH = RESULTS / "segment_watch.csv"
BACKTEST_PATH = RESULTS / "backtest_path.csv"
LAST_12 = f"month_start > date '{AS_OF}' - interval 12 month"
NAMES = {"AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick", "NS": "Nova Scotia",
         "ON": "Ontario", "QC": "Quebec", "SK": "Saskatchewan"}


def _plain(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating | float):
        return round(float(v), 4)
    return v


def _rows(con, sql: str) -> list[dict]:
    return [{k: _plain(v) for k, v in r.items()} for r in con.sql(sql).df().to_dict("records")]


def _one(con, sql: str) -> dict:
    return _rows(con, sql)[0]


def backtest(db: Path) -> pd.DataFrame:
    with duckdb.connect(str(db), read_only=True) as con:
        return fc.backtest(con.sql("select * from province_month").df())


def _rate_action(con, province: str, product: str, start) -> dict:
    """Retention and mean rate change for the segment's renewals in the 12 months before and after the action."""
    out = {"province": province, "product": product, "from": start.isoformat()}
    for side, cond in (("before", f"month_start >= date '{start}' - interval 12 month and month_start < '{start}'"),
                       ("after", f"month_start >= '{start}' and month_start < date '{start}' + interval 12 month")):
        out[side] = _one(con, f"""
            select sum(renewals_due)::int as renewals_due,
                   round(sum(renewed) / sum(renewals_due), 4)::double as retention,
                   round(sum(sum_rate_change) / sum(renewals_due), 4)::double as mean_rate_change
            from fct_segment_month where province = '{province}' and product = '{product}' and {cond}""")
    return out


def summary(db: Path, bt: pd.DataFrame) -> dict:
    a = AS_OF.isoformat()
    with duckdb.connect(str(db), read_only=True) as con:
        book = _one(con, f"""
            select (select count(*) from raw_book.policies)::int as policies,
                   (select count(*) from raw_book.terms)::int as terms,
                   (select count(*) from raw_book.claims)::int as claims,
                   (select count(distinct month_start) from province_month)::int as months,
                   (select sum(policies_in_force) from province_month where month_start = date_trunc('month',
                    date '{a}'))::int as in_force,
                   round(sum(written_premium), 2)::double as written_premium_12m,
                   round(sum(earned_premium), 2)::double as earned_premium_12m,
                   round(sum(incurred) / sum(earned_premium), 4)::double as loss_ratio_12m,
                   round(sum(renewed) / sum(renewals_due), 4)::double as retention_12m
            from province_month where {LAST_12}""")
        provinces = _rows(con, f"""
            with last as (select province, policies_in_force, in_force_growth_yoy, written_premium_growth_12m
                          from province_month where month_start = date_trunc('month', date '{a}')),
            year as (select province, sum(written_premium) as written_premium_12m,
                            sum(incurred) / sum(earned_premium) as loss_ratio_12m,
                            sum(renewed) / sum(renewals_due) as retention_12m
                     from province_month where {LAST_12} group by 1)
            select province, policies_in_force::int as policies_in_force, in_force_growth_yoy,
                   written_premium_growth_12m, round(written_premium_12m, 2)::double as written_premium_12m,
                   round(loss_ratio_12m, 4)::double as loss_ratio_12m, round(retention_12m, 4)::double as retention_12m
            from last join year using (province) order by written_premium_12m desc""")
        channels = _rows(con, f"""
            select channel, sum(renewals_due)::int as renewals_due,
                   round(sum(renewed) / sum(renewals_due), 4)::double as retention_12m
            from fct_segment_month where {LAST_12} group by 1 order by retention_12m desc""")
        hail = _one(con, f"""
            select (select count(*) from raw_book.claims where cause = 'hail')::int as claims,
                   (select round(sum(amount), 2) from raw_book.claims where cause = 'hail')::double as incurred,
                   round(sum(incurred) filter (where month_start = date_trunc('month', date '{HAIL_DATE}'))
                         / sum(earned_premium) filter (where month_start = date_trunc('month', date '{HAIL_DATE}')),
                         4)::double as home_loss_ratio_that_month,
                   round(sum(incurred) filter (where year(month_start) = {HAIL_DATE.year})
                         / sum(earned_premium) filter (where year(month_start) = {HAIL_DATE.year}), 4)::double
                       as home_loss_ratio_that_year,
                   round(sum(incurred) filter (where year(month_start) = {HAIL_DATE.year - 1})
                         / sum(earned_premium) filter (where year(month_start) = {HAIL_DATE.year - 1}), 4)::double
                       as home_loss_ratio_year_before
            from fct_segment_month where province = '{HAIL_PROVINCE}' and product = 'home'""")
        actions = [_rate_action(con, p, prod, start) for p, prod, start, _ in RATE_ACTIONS]
        late = _one(con, f"""
            with reported as (
                select sum(incurred) as incurred, sum(earned_premium) as earned from province_month
                where month_start > date_trunc('month', date '{a}') - interval 3 month),
            late as (select count(*) as claims, sum(amount) as incurred from labels.late_claims
                     where loss_date >= date_trunc('month', date '{a}') - interval 2 month)
            select late.claims::int as late_claims, round(late.incurred, 2)::double as late_incurred,
                   round(reported.incurred / reported.earned, 4)::double as loss_ratio_3m_reported,
                   round((reported.incurred + late.incurred) / reported.earned, 4)::double as loss_ratio_3m_with_late
            from reported, late""")
        upcoming = con.sql("""select province, renewal_month, count(*) as renewals_due from stg_book__terms
                              where outcome = 'not_due' group by all""").df()
        pm = con.sql("select * from province_month").df()
    rule = fc.best_rule(bt)
    prov_bt = bt[bt["province"] != "all"]
    scores = fc.score(prov_bt, ["rule"]).to_dict("records")
    on_start = next(s for p, prod, s, _ in RATE_ACTIONS if p == "ON")
    after = prov_bt[(prov_bt["province"] == "ON") & (prov_bt["target"] >= pd.Period(on_start, "M"))
                    & (prov_bt["target"] < pd.Period(on_start, "M") + 6)]
    nxt = fc.next_months(pm, upcoming, rule)
    return {
        "as_of": a, "first_month": str(pm["month_start"].min())[:10], "book": book, "provinces": provinces,
        "channels": channels, "hail": {"date": HAIL_DATE.isoformat(), "province": HAIL_PROVINCE, **hail},
        "rate_actions": actions, "late_claims": late,
        "retention_forecast": {
            "rule": rule, "horizons": len(fc.HORIZONS), "scores": scores,
            "ontario_first_6_months_after_rate_action": fc.score(after, ["rule"]).to_dict("records"),
            "next_3_months": {"renewals_due": int(nxt["renewals_due"].sum()),
                              "expected_renewed": round(float(nxt["expected_renewed"].sum()), 1)},
        },
    }


def province_month_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("select * from province_month order by month_start, province").df()
    for c in ("written_premium", "earned_premium", "incurred"):
        df[c] = df[c].astype(float).round(2) + 0.0
    return df.to_csv(index=False, lineterminator="\n")


def backtest_csv(bt: pd.DataFrame) -> str:
    """Scores per province (and the whole book), rule and horizon."""
    return fc.score(bt, ["province", "rule", "horizon"]).to_csv(index=False, lineterminator="\n")


def forecast_csv(db: Path, bt: pd.DataFrame) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        pm = con.sql("select * from province_month").df()
        upcoming = con.sql("""select province, renewal_month, count(*) as renewals_due from stg_book__terms
                              where outcome = 'not_due' group by all""").df()
    return fc.next_months(pm, upcoming, fc.best_rule(bt)).to_csv(index=False, lineterminator="\n")


def segment_watch_csv(db: Path) -> str:
    """Month by month for the segments the planted events hit (Alberta home: the hail and its rate increase;
    Ontario auto: its rate increase): earned premium, incurred, loss ratio, renewals, retention, mean rate change."""
    segs = " or ".join(f"(province = '{p}' and product = '{prod}')" for p, prod, _, _ in RATE_ACTIONS)
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql(f"""
            select province, product, month_start,
                   sum(earned_premium)::double as earned_premium, sum(incurred)::double as incurred,
                   round(sum(incurred) / nullif(sum(earned_premium), 0), 4)::double as loss_ratio,
                   sum(renewals_due)::int as renewals_due, sum(renewed)::int as renewed,
                   round(sum(renewed) / nullif(sum(renewals_due), 0), 4)::double as retention,
                   round(sum(sum_rate_change) / nullif(sum(renewals_due), 0), 4)::double as mean_rate_change
            from fct_segment_month where {segs}
            group by all order by province, product, month_start""").df()
    for c in ("earned_premium", "incurred"):
        df[c] = df[c].round(2) + 0.0
    return df.to_csv(index=False, lineterminator="\n")


def backtest_path_csv(bt: pd.DataFrame) -> str:
    """The one-month-ahead forecasts behind the back-test: each rule's forecast and what happened, per province
    (and the whole book, 'all') and target month."""
    df = bt[bt["horizon"] == 1].assign(month_start=lambda d: d["target"].dt.start_time.dt.date)
    df = df[["province", "month_start", "rule", "forecast", "actual", "due"]].rename(columns={"due": "renewals_due"})
    df["forecast"], df["actual"] = df["forecast"].round(4), df["actual"].round(4)
    df["renewals_due"] = df["renewals_due"].astype(int)
    return df.sort_values(["province", "month_start", "rule"]).to_csv(index=False, lineterminator="\n")


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"


def _usd(x: float) -> str:
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _pts(x: float) -> str:
    return f"{x:+.1f} points"


def brief(s: dict) -> str:
    b, h, lc, rf = s["book"], s["hail"], s["late_claims"], s["retention_forecast"]
    provs = s["provinces"]
    fastest = max(provs, key=lambda p: p["in_force_growth_yoy"])
    slowest = min(provs, key=lambda p: p["in_force_growth_yoy"])
    worst = max(provs, key=lambda p: p["loss_ratio_12m"])
    best = min(provs, key=lambda p: p["loss_ratio_12m"])
    ch = {c["channel"]: c for c in s["channels"]}
    on = next(a for a in s["rate_actions"] if a["province"] == "ON")
    ab = next(a for a in s["rate_actions"] if a["province"] == "AB")
    sc = {r["rule"]: r for r in rf["scores"]}
    cost = (on["before"]["retention"] - on["after"]["retention"]) / (
        on["after"]["mean_rate_change"] - on["before"]["mean_rate_change"])
    after = {r["rule"]: r for r in rf["ontario_first_6_months_after_rate_action"]}
    lines = [
        "# Provincial book health: the brief",
        "",
        f"Simulated home and auto book, {s['first_month'][:7]} to {s['as_of'][:7]}. Last 12 months unless said.",
        "",
        "## What the numbers say",
        "",
        f"- **The book:** {b['in_force']:,} policies in force, {_usd(b['written_premium_12m'])} written, loss ratio "
        f"{_pct(b['loss_ratio_12m'])}, {_pct(b['retention_12m'])} of renewals kept.",
        f"- **Growth:** {NAMES[fastest['province']]} has {_pct(fastest['in_force_growth_yoy'])} more "
        f"policies in force than a year ago; {NAMES[slowest['province']]} {_pct(slowest['in_force_growth_yoy'])}.",
        f"- **Ontario auto paid for its rate increase in customers.** Renewals from {on['from'][:7]} took "
        f"{_pct(on['after']['mean_rate_change'])} on average (was {_pct(on['before']['mean_rate_change'])}); "
        f"retention fell from {_pct(on['before']['retention'])} to {_pct(on['after']['retention'])} in the year "
        "after.",
        f"- **The {h['date']} hail in Alberta** cost {_usd(h['incurred'])} across {h['claims']} home claims: Alberta "
        f"home's loss ratio was {_pct(h['home_loss_ratio_that_month'])} that month and "
        f"{_pct(h['home_loss_ratio_that_year'])} for the year (year before: {_pct(h['home_loss_ratio_year_before'])}"
        f"). The {_pct(ab['after']['mean_rate_change'])} increase that followed moved retention from "
        f"{_pct(ab['before']['retention'])} to {_pct(ab['after']['retention'])}.",
        f"- **Loss ratio by province** runs from {_pct(best['loss_ratio_12m'])} ({NAMES[best['province']]}) to "
        f"{_pct(worst['loss_ratio_12m'])} ({NAMES[worst['province']]}). The small provinces swing year to year on a "
        "few large claims; read them over two or three years, not one.",
        f"- **Digital customers leave more:** {_pct(ch['digital']['retention_12m'])} renew, against "
        f"{_pct(ch['broker']['retention_12m'])} through brokers.",
        "",
        "## Two cautions",
        "",
        f"- **The last three months look better than they are.** {lc['late_claims']} claims "
        f"({_usd(lc['late_incurred'])}) from those months were not reported by {s['as_of']}. With them the loss "
        f"ratio is {_pct(lc['loss_ratio_3m_with_late'])}, not {_pct(lc['loss_ratio_3m_reported'])}.",
        f"- **A 12-month average is a good retention forecast until prices move.** Back-tested over every month and "
        f"province, the {rf['rule'].replace('_', ' ')} rule misses by {sc[rf['rule']]['mae_points']:.2f} points "
        f"on average (last month: {sc['last_month']['mae_points']:.2f}, trailing 3: "
        f"{sc['trailing_3']['mae_points']:.2f}). In Ontario's first six months after the increase the 12-month "
        f"average was {after['trailing_12']['bias_points']:.1f} points too hopeful, the 3-month average "
        f"{after['trailing_3']['bias_points']:.1f}.",
        "",
        "## So what",
        "",
        f"- Plan on {rf['next_3_months']['expected_renewed']:,.0f} of the {rf['next_3_months']['renewals_due']:,} "
        "renewals due in the next three months staying, and switch to the 3-month average in any province or "
        "product that takes a rate change above the usual.",
        "- Price each rate action against the customers it will cost: in Ontario auto each extra point of increase "
        f"cost {cost:.1f} points of retention.",
        "- Report the latest quarter's loss ratio with the late-claims allowance next to it, or not at all.",
        "",
    ]
    return "\n".join(lines)
