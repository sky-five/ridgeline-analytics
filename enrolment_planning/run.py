"""Write the results: results/summary.json (the enrolment headline, yearly new permits, the back-test's 12-month
scores and which rule did best in each period, and the permits-to-enrolment ratio a what-if starts from),
results/backtest_scores.csv (every series, rule, period and horizon), results/international_share.csv (region x
fall x program group) and results/permits_monthly.csv (the five back-tested series). Every number comes from the
dbt marts; the dashboard (report.py) reads only these files."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from enrolment_planning import forecast, public

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
SCORES = RESULTS / "backtest_scores.csv"
SHARE = RESULTS / "international_share.csv"
PERMITS_MONTHLY = RESULTS / "permits_monthly.csv"
SERIES = ("CA", "ON", "BC", "QC", "AB")  # Canada and the four provinces with the most new permits


def _round(x, digits=4):
    return round(float(x), digits)


def permit_series(con, region: str, study_level: str = "post_secondary") -> pd.Series:
    """Monthly new permits as a Series indexed by monthly Period. CA is IRCC's all-Canada row."""
    if region == "CA":
        sql = "select permit_month, permits from study_permits_canada_month where study_level = ? order by 1"
        df = con.execute(sql, [study_level]).df()
    else:
        sql = """select permit_month, permits from fct_study_permits_month
                 where study_level = ? and region_code = ? order by 1"""
        df = con.execute(sql, [study_level, region]).df()
    return pd.Series(df["permits"].to_numpy(float), index=pd.PeriodIndex(df["permit_month"], freq="M"))


def backtests(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = pd.concat([forecast.backtest(permit_series(con, s), s) for s in SERIES], ignore_index=True)
    return monthly, forecast.next_12_months(monthly)


def scores_frame(monthly: pd.DataFrame, yearly: pd.DataFrame) -> pd.DataFrame:
    m = forecast.score(monthly, ["series", "period", "rule", "horizon"]).assign(measure="month")
    y = forecast.score(yearly, ["series", "period", "rule"]).assign(measure="next_12_months", horizon=12)
    df = pd.concat([m, y], ignore_index=True)[["series", "measure", "period", "rule", "horizon", "forecasts",
                                               "wape", "bias"]]
    return df.round({"wape": 4, "bias": 4})


def summary(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        monthly, yearly = backtests(con)
        canada = con.sql("""select t.fall_year,
                                   max(t.published_enrolments) filter (where t.status_code = 'ALL') as total,
                                   max(t.published_enrolments) filter (where t.status_code = 'INT') as international
                            from stg_statcan__totals as t where t.region_code = 'CA' group by 1 order by 1""").df()
        by_region = con.sql("""select region_code, international, total, international_share
                               from enrolment_region_year where fall_year = (select max(fall_year) from dim_term)
                               order by international desc""").df()
        stem = con.sql("""select p.program_group, sum(f.enrolments) as n from fct_enrolment as f
                          join dim_program as p using (program_code)
                          where f.status_code = 'INT' and f.fall_year = (select max(fall_year) from dim_term)
                          group by 1 order by 2 desc""").df()
        ca = permit_series(con, "CA")
        facts = con.sql("select count(*), count(*) filter (where is_not_available) from fct_enrolment").fetchone()
        suppressed = con.sql("select count(*) filter (where is_suppressed), count(*) "
                             "from stg_ircc__study_permits").fetchone()
    per_year = ca.groupby(ca.index.year).sum()
    # The bridge from intake to the fall count: international enrolment in the fall of year y over the new
    # post-secondary permits from October of y-1 to September of y (the permits that start that fall's count).
    bridge = []
    for r in canada.itertuples():
        start, end = pd.Period(f"{r.fall_year - 1}-10", "M"), pd.Period(f"{r.fall_year}-09", "M")
        window = ca[(ca.index >= start) & (ca.index <= end)]
        if len(window) == 12:
            bridge.append({"fall_year": int(r.fall_year), "international_enrolments": int(r.international),
                           "new_permits_oct_to_sep": int(window.sum()),
                           "enrolments_per_new_permit": _round(r.international / window.sum(), 3)})
    yscore = forecast.score(yearly, ["series", "period", "rule"])
    best = (yscore.sort_values("wape").groupby(["series", "period"], sort=False).head(1)
            .sort_values(["series", "period"]))
    last = canada.iloc[-1]
    peak = canada.loc[canada["international"].idxmax()]
    return {
        "sources": {
            "enrolments": {"table": public.STATCAN_TABLE, "licence": public.LICENCE,
                           "first_fall": int(canada["fall_year"].min()), "last_fall": int(canada["fall_year"].max()),
                           "fact_rows": int(facts[0]), "cells_not_published": int(facts[1])},
            "study_permits": {"dataset": public.IRCC_DATASET, "licence": public.LICENCE,
                              "first_month": str(ca.index.min()), "last_month": str(ca.index.max()),
                              "cells": int(suppressed[1]), "cells_suppressed": int(suppressed[0])},
            "sha256": public.SHA256,
        },
        "enrolments": {
            "last_fall": int(last.fall_year), "total": int(last.total), "international": int(last.international),
            "international_share": _round(last.international / last.total),
            "peak_international_fall": int(peak.fall_year), "peak_international": int(peak.international),
            "first_fall_international_share": _round(canada.iloc[0].international / canada.iloc[0].total),
            "international_by_region_last_fall": [
                {"region": r.region_code, "international": int(r.international),
                 "share": _round(r.international_share)} for r in by_region.itertuples()],
            "international_by_program_group_last_fall": {r.program_group: int(r.n) for r in stem.itertuples()},
        },
        "new_post_secondary_permits_by_year": {str(y): int(n) for y, n in per_year.items()},
        "intake_to_enrolment": bridge,
        "backtest": {
            "series": list(SERIES), "rules": list(forecast.RULES), "first_origin": str(forecast.FIRST_ORIGIN),
            "last_origin": str(monthly["origin"].max()), "monthly_forecasts": len(monthly),
            "next_12_months_best_rule": [
                {"series": r.series, "period": r.period, "rule": r.rule, "wape": _round(r.wape),
                 "bias": _round(r.bias)} for r in best.itertuples()],
            "canada_next_12_months": [
                {"period": r.period, "rule": r.rule, "forecasts": int(r.forecasts), "wape": _round(r.wape),
                 "bias": _round(r.bias)} for r in yscore[yscore["series"] == "CA"].itertuples()],
        },
    }


def scores_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        monthly, yearly = backtests(con)
    return scores_frame(monthly, yearly).to_csv(index=False, lineterminator="\n")


def share_csv(db: Path) -> str:
    """International enrolments over all enrolments per region (CA = every region added up), fall year and
    program group (ALL = every group). Cells StatCan did not publish count as nothing on both sides."""
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("""
            with f as (
                select f.fall_year, f.region_code, p.program_group, f.status_code, f.enrolments
                from fct_enrolment as f join dim_program as p using (program_code)
            )
            select fall_year,
                   coalesce(region_code, 'CA') as region_code,
                   coalesce(program_group, 'ALL') as program_group,
                   sum(enrolments) filter (where status_code = 'INT')::bigint as international,
                   sum(enrolments)::bigint as total
            from f
            group by cube (region_code, program_group), fall_year
            order by fall_year, region_code, program_group
        """).df()
    df["international_share"] = (df["international"] / df["total"]).round(4)
    return df.to_csv(index=False, lineterminator="\n")


def permits_monthly_csv(db: Path) -> str:
    """New post-secondary study permits per month for the five back-tested series."""
    with duckdb.connect(str(db), read_only=True) as con:
        frames = [permit_series(con, s).rename("permits").rename_axis("month").reset_index().assign(series=s)
                  for s in SERIES]
    df = pd.concat(frames, ignore_index=True)[["series", "month", "permits"]]
    df["month"] = df["month"].astype(str)
    df["permits"] = df["permits"].astype(int)
    return df.to_csv(index=False, lineterminator="\n")


def results(db: Path) -> tuple[dict, dict[Path, str]]:
    """The summary and every results file's fresh text."""
    s = summary(db)
    return s, {SUMMARY: to_json(s), SCORES: scores_csv(db), SHARE: share_csv(db),
               PERMITS_MONTHLY: permits_monthly_csv(db)}


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"
