"""On the ops-daily warehouse built once in conftest.py: the simulator's feeds and planted events, the marts and the
flag rule against a pandas recomputation from the raw feeds, the back-check, the definitions sheet and the
committed results."""
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from ops_daily.run import (
    FLAGS,
    METRICS,
    OPS_DAY,
    SUMMARY,
    TODAY,
    definitions,
    flags_csv,
    ops_day_csv,
    summary,
    to_json,
    today,
)
from ops_daily.simulate import AS_OF, EVENTS, FIRST_DAY, MIN_DAYS_OPEN, handle_factor, simulate, staff_factor

BASELINE_WEEKS, FLAG_SCORE = 6, 3  # the vars in ops_daily/dbt/dbt_project.yml


@pytest.fixture(scope="module")
def con(ops_db):
    with duckdb.connect(str(ops_db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def s(ops_db):
    return summary(ops_db)


def test_simulation_is_seeded(operation):
    again = simulate()
    pd.testing.assert_frame_equal(operation.calls, again.calls)
    pd.testing.assert_frame_equal(operation.claims, again.claims)


def test_feeds_hold_together(operation):
    c, k = operation.calls, operation.claims
    assert len(c) == ((AS_OF - FIRST_DAY).days + 1) * 6
    assert (c["answered"] + c["abandoned"] == c["offered"]).all()
    assert (c["answered_within_60s"] <= c["answered"]).all()
    closed = k.dropna(subset=["closed_date"])
    assert ((closed["closed_date"] - closed["opened_date"]).map(lambda d: d.days) >= MIN_DAYS_OPEN).all()
    assert (closed["closed_date"] <= AS_OF).all() and k["claim_id"].is_unique


def test_planted_events_are_in_the_feeds(operation):
    assert staff_factor("west", "auto", date(2026, 6, 21)) == 1.0
    assert staff_factor("west", "auto", date(2026, 6, 22)) == 0.82
    assert staff_factor("west", "home", date(2026, 6, 22)) == 1.0
    assert handle_factor("east", "home", date(2026, 6, 7)) == 1.0
    assert handle_factor("east", "home", date(2026, 6, 30)) == pytest.approx(1.18)
    c = operation.calls.assign(aht=lambda d: d["handle_seconds"] / d["answered"])
    east = c[(c["site"] == "east") & (c["line"] == "home")]
    assert east[east["call_date"] >= date(2026, 6, 22)]["aht"].mean() > 1.15 * east[
        east["call_date"] < date(2026, 6, 8)]["aht"].mean()
    k = operation.claims
    storm = k[(k["site"] == "central") & (k["line"] == "home")]
    before = storm[storm["opened_date"].between(date(2026, 5, 18), date(2026, 6, 17))].groupby("opened_date").size()
    week = storm[storm["opened_date"].between(date(2026, 6, 18), date(2026, 6, 24))]
    assert len(week) > 2.5 * before.mean() * 7


def test_claims_day_matches_the_feed(con, operation):
    mart = con.sql("select * from fct_claims_day").df()
    mart["day"] = pd.to_datetime(mart["day"]).dt.date
    k = operation.claims
    for (site, line, day), row in mart.sample(60, random_state=1).set_index(["site", "line", "day"]).iterrows():
        x = k[(k["site"] == site) & (k["line"] == line)]
        assert row["claims_opened"] == (x["opened_date"] == day).sum()
        assert row["claims_closed"] == (x["closed_date"] == day).sum()
        still_open = (x["opened_date"] <= day) & (x["closed_date"].isna() | (x["closed_date"] > day))
        assert row["open_backlog"] == still_open.sum()


def test_ops_day_metrics_match_the_feed(con, operation):
    mart = con.sql("select * from fct_ops_day").df()
    mart["day"] = pd.to_datetime(mart["day"]).dt.date
    c = operation.calls.rename(columns={"call_date": "day"})
    m = mart.merge(c, on=["day", "site", "line"], suffixes=("", "_raw"))
    assert len(m) == len(c)
    np.testing.assert_allclose(m["service_level"], m["answered_within_60s_raw"] / m["offered_raw"])
    np.testing.assert_allclose(m["abandon_rate"], m["abandoned_raw"] / m["offered_raw"])
    np.testing.assert_allclose(m["avg_handle_minutes"], m["handle_seconds_raw"] / m["answered_raw"] / 60)


def _flag_rule(long: pd.DataFrame, defs: dict) -> pd.DataFrame:
    """The flag rule written again in pandas, from the definitions sheet."""
    out = []
    long = long.assign(wd=pd.to_datetime(long["day"]).dt.weekday).sort_values("day")
    for _, g in long.groupby(["site", "line", "metric", "wd"]):
        v = g["value"].to_numpy()
        d = defs[g["metric"].iloc[0]]
        for i in range(BASELINE_WEEKS, len(v)):
            prev = v[i - BASELINE_WEEKS:i]
            base = np.median(prev)
            spread = max(1.4826 * np.median(np.abs(prev - base)), float(d["min_spread"]),
                         np.sqrt(max(base, 1)) if d["kind"] == "count" else 0)
            move = v[i] - base
            bad = {"up": move < 0, "down": move > 0, "none": True}[d["good_direction"]]
            need = max(float(d["min_change_abs"]), float(d["min_change_rel"]) * abs(base))
            flagged = abs(move) >= FLAG_SCORE * spread and abs(move) >= need and bad
            out.append({**g.iloc[i][["day", "site", "line", "metric"]].to_dict(), "baseline": base,
                        "flagged": bool(flagged)})
    return pd.DataFrame(out)


def test_flag_rule_matches_a_pandas_rewrite(con):
    long = con.sql("select * from ops_metric_day").df()
    mine = _flag_rule(long, definitions())
    theirs = con.sql("select day, site, line, metric, baseline, flagged from ops_flags where baseline_days = 6").df()
    m = theirs.merge(mine, on=["day", "site", "line", "metric"], suffixes=("", "_pd"))
    assert len(m) == len(mine) == len(theirs)
    np.testing.assert_allclose(m["baseline"], m["baseline_pd"], rtol=1e-9)
    assert (m["flagged"] == m["flagged_pd"]).all()
    assert m["flagged"].sum() == len(FLAGS.read_text().splitlines()) - 1


def test_every_planted_event_is_flagged_on_its_cause_within_four_days(s):
    by = {e["event"]: e for e in s["flag_rule"]["events"]}
    assert set(by) == {e[0] for e in EVENTS}
    for e in by.values():
        assert e["days_to_flag_cause"] <= 4, e
    assert by["staff_cut"]["days_to_flag_cause"] == 0 and by["storm"]["days_to_flag_cause"] == 0
    # the slow handle-time creep is the one the rule finds late
    assert by["handle_time_creep"]["days_to_flag_cause"] == 4


def test_quiet_teams_are_rarely_flagged(s):
    fr = s["flag_rule"]
    assert fr["false_flag_rate"] < 0.01
    assert fr["false_flags"] == sum(fr["false_flags_by_metric"].values())


def test_as_of_watchlist_names_the_three_planted_teams(s):
    teams = {(w["site"], w["line"]) for w in s["watchlist_as_of"]}
    assert teams == {(site, line) for _, site, line, _, _ in EVENTS}
    assert [w["rank"] for w in s["watchlist_as_of"]] == [1, 2, 3]


def test_definitions_sheet_covers_every_metric_and_nothing_else(con):
    defs = definitions()
    assert list(defs) == METRICS
    assert set(con.sql("select distinct metric from ops_metric_day").df()["metric"]) == set(METRICS)
    for d in defs.values():
        assert all(str(v).strip() for v in d.values()), d
        assert d["good_direction"] in {"up", "down", "none"}


def test_today_has_three_things_and_a_paragraph_per_metric(ops_db, s):
    text = today(ops_db, s)
    assert text.count("\n1. ") == text.count("\n2. ") == text.count("\n3. ") == 1
    for d in definitions().values():
        assert f"**{d['label']}**" in text


def test_committed_results_are_current(ops_db, s):
    assert SUMMARY.read_text() == to_json(s)
    assert TODAY.read_text() == today(ops_db, s)
    assert FLAGS.read_text() == flags_csv(ops_db)
    assert OPS_DAY.read_text() == ops_day_csv(ops_db)
