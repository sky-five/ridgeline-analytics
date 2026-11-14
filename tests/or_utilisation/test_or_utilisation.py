"""Builds the surgical-suite warehouse once (simulate + load + dbt build, about 10 s) and checks the
simulator's rules, the marts against an independent pandas count, the metric spec against the marts, the
validation suite on hand-made and real claims, the return estimate against the replayed truth, and the
committed results."""
import duckdb
import pandas as pd
import pytest

from or_utilisation import roi, spec, validate
from or_utilisation.load import dbt_build, load
from or_utilisation.run import SUMMARY, WEEKLY, marts, summary, to_json, weekly_csv
from or_utilisation.simulate import BLOCK_MINUTES, POLICY_START, simulate


@pytest.fixture(scope="module")
def suite():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, suite):
    path = tmp_path_factory.mktemp("or") / "or.duckdb"
    load(path, suite)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def m(db):
    return marts(db)


# --- the simulator ---------------------------------------------------------------------------


def test_replay_without_the_rule_differs_only_after_it_starts(suite):
    off = simulate(policy=False, replay=False)
    before = pd.Timestamp(POLICY_START)
    on_cases = suite.cases[pd.to_datetime(suite.cases["case_date"]) < before].reset_index(drop=True)
    off_cases = off.cases[pd.to_datetime(off.cases["case_date"]) < before].reset_index(drop=True)
    pd.testing.assert_frame_equal(on_cases, off_cases)
    assert (off.releases["release_type"] == "voluntary").all()
    auto = suite.releases[suite.releases["release_type"] == "auto"]
    assert len(auto) > 0 and (auto["released_at"] >= pd.Timestamp(POLICY_START) - pd.Timedelta(hours=72)).all()
    assert suite.truth["added_in_block_minutes"] > 0


def test_owner_has_no_cases_in_a_released_block(suite):
    owners = suite.blocks.set_index("block_id")["service_id"]
    released = suite.cases[suite.cases["block_id"].isin(suite.releases["block_id"])]
    assert (released["service_id"] != released["block_id"].map(owners)).all()


# --- marts vs an independent count -----------------------------------------------------------


def test_marts_match_a_pandas_count(suite, m):
    c = suite.cases[suite.cases["status"] == "completed"].copy()
    end = pd.to_datetime(c["case_date"]) + pd.Timedelta(minutes=450 + BLOCK_MINUTES)
    c["minutes"] = ((c["wheels_out"].clip(upper=end) - c["wheels_in"]).dt.total_seconds() // 60).clip(lower=0)
    c["owner"] = c["service_id"] == c["block_id"].map(suite.blocks.set_index("block_id")["service_id"])
    c["period"] = (pd.to_datetime(c["case_date"]) >= pd.Timestamp(POLICY_START)).map({True: "after", False: "before"})
    expect = c.groupby(["period", "owner"])["minutes"].sum()
    p = m["by_period"].set_index(["period", "blocks_in_scope"])
    for period in ("before", "after"):
        assert p.loc[(period, "all"), "owner_in_block_minutes"] == expect[(period, True)]
        assert p.loc[(period, "all"), "reused_in_block_minutes"] == expect[(period, False)]
        assert p.loc[(period, "all"), "allocated_minutes"] == 780 * BLOCK_MINUTES


def test_every_spec_metric_is_a_mart_column_and_recomputes(m):
    for name in spec.metrics():
        for row in m["weekly"].itertuples():
            assert spec.value(name, row._asdict()) == pytest.approx(getattr(row, name), rel=1e-9), name


# --- the validation suite --------------------------------------------------------------------


def _period_rows(after_owner=200.0, after_credited=0.0, after_cancel=0.06, turnover=0.0) -> pd.DataFrame:
    """Two periods x two scopes of hand-made minute sums; only the arguments change between periods."""
    def row(period, scope, owner, credited, cancel):
        r = {"period": period, "blocks_in_scope": scope, "days": 10, "allocated_minutes": 1000.0,
             "credited_released_minutes": credited, "released_minutes": credited, "owner_in_block_minutes": owner,
             "owner_turnover_minutes": turnover, "reused_in_block_minutes": 0.0, "completed_cases": 100,
             "cancelled_cases": 100 * cancel}
        r["same_day_cancellation_rate"] = cancel
        return r
    return pd.DataFrame([row("before", "all", 200.0, 0.0, 0.06), row("after", "all", after_owner, after_credited,
                         after_cancel), row("before", "owner_booked", 200.0, 0.0, 0.06),
                         row("after", "owner_booked", after_owner, 0.0, after_cancel)])


def test_a_claim_with_nothing_moved_passes():
    r = validate.review("room_utilisation", _period_rows())
    assert r.flags == [] and r.change_pp == 0


def test_a_planted_denominator_change_is_flagged_and_sized():
    # same owner minutes, but 200 of the 1,000 after-period minutes were released: 20% -> 25% with no new case
    r = validate.review("adjusted_block_utilisation", _period_rows(after_credited=200.0))
    assert "denominator_moved" in r.flags
    assert r.change_pp == pytest.approx(5.0)
    moved = next(c for c in r.checks if c.check == "denominator_moved")
    assert moved.size_pp == pytest.approx(5.0)  # all of the change is the denominator


def test_turnover_and_untouched_moves_are_flagged():
    assert "counts_turnover" in validate.review("block_utilisation_with_turnover", _period_rows(turnover=50)).flags
    r = validate.review("room_utilisation", _period_rows(after_owner=230.0))  # +3 pp everywhere, also on booked blocks
    assert r.flags == ["moved_where_rule_cannot_act"]


def test_unequal_windows_are_flagged():
    days = {"before": list(pd.date_range("2026-01-05", periods=5)),
            "after": list(pd.date_range("2026-04-06", periods=4))}
    assert "unequal_windows" in validate.review("room_utilisation", _period_rows(), days).flags


def test_real_claims(m):
    adjusted = validate.review("adjusted_block_utilisation", m["by_period"])
    room = validate.review("room_utilisation", m["by_period"])
    assert {"denominator_moved", "misses_the_gain", "moved_where_rule_cannot_act"} <= set(adjusted.flags)
    assert room.flags == ["moved_where_rule_cannot_act"]
    assert adjusted.change_pp > room.change_pp > 0


# --- the return --------------------------------------------------------------------------------


def test_defended_estimate_covers_the_truth_and_the_claim_does_not(suite, m):
    r = roi.roi(m["by_period"], m["daily"], suite.truth)
    assert r.defended_ci_covers_truth
    assert r.defended.ci_low > 0
    assert r.claimed.added_minutes > 3 * r.true_added_minutes
    assert r.claimed.added_minutes > r.before_after.added_minutes > r.defended.ci_high


def test_defended_estimate_reads_only_warehouse_numbers(m):
    # the estimate is a function of the daily mart alone; truth is only passed in to be compared with
    assert roi.defended_minutes(m["daily"]) == pytest.approx(
        roi.roi(m["by_period"], m["daily"], {"added_in_block_minutes": 1}).defended.added_minutes, abs=0.5)


def test_committed_results_are_current(db, suite):
    assert SUMMARY.read_text() == to_json(summary(db, suite))
    assert WEEKLY.read_text() == weekly_csv(db)


def test_warehouse_has_no_truth_columns(db):
    with duckdb.connect(str(db), read_only=True) as con:
        cols = con.execute("select column_name from information_schema.columns where table_schema = 'raw_or'").df()
    assert not cols["column_name"].str.contains("truth|counterfactual|policy").any()
