"""Metric definitions on hand-made rows, the simulator's planted facts, the teardown and the carrier sizing."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from quote_funnel import carrier, counting, memo, metrics, simulate
from quote_funnel.run import run

RESULTS = Path(__file__).resolve().parents[2] / "quote_funnel" / "results"


@pytest.fixture(scope="module")
def summary():
    return run()


def tiny() -> duckdb.DuckDBPyConnection:
    """Two quoted sessions in one week: S1 resubmits twice and binds, S2 submits once and never clicks."""
    t = datetime(2026, 4, 7, 10)
    con = duckdb.connect()
    simulate.load(con, {
        "carriers": pd.DataFrame({"carrier_id": ["x", "y"], "commission_per_bind": [100.0, 80.0],
                                  "segments_quoted": ["auto_standard", "auto_standard"]}),
        "sessions": pd.DataFrame({"session_id": ["S1", "S2"], "started_at": [t, t], "line": ["auto"] * 2,
                                  "tier": ["standard"] * 2, "device": ["mobile", "desktop"]}),
        "quote_requests": pd.DataFrame({"request_id": ["Q1", "Q2", "Q3", "Q4"],
                                        "session_id": ["S1", "S1", "S1", "S2"],
                                        "submitted_at": [t] * 4, "submit_number": [1, 2, 3, 1]}),
        "carrier_quotes": pd.DataFrame({"session_id": ["S1", "S1", "S2"], "carrier_id": ["x", "y", "x"],
                                        "premium": [1500.0, 1400.0, 1700.0]}),
        "clicks": pd.DataFrame({"session_id": ["S1"], "carrier_id": ["y"], "clicked_at": [t]}),
        "binds": pd.DataFrame({"session_id": ["S1"], "carrier_id": ["y"], "bound_on": [t.date()],
                               "annual_premium": [1400.0]}),
    })
    metrics.build(con)
    return con


def test_rates_count_sessions_not_requests():
    w = tiny().execute("select * from mart.funnel_weekly").df().iloc[0]
    assert (w.sessions, w.requests, w.quoted_sessions, w.bound_sessions) == (2, 4, 2, 1)
    assert w.quote_to_bind == 0.5 and w.click_rate == 0.5 and w.bind_rate == 1.0
    assert w.quote_to_bind_per_request == 0.25  # the old definition halves on the same shoppers
    assert w.commission_per_session == 40.0  # carrier y's commission over two sessions


def test_session_mart_takes_best_price_and_bound_carrier():
    s = tiny().execute("select * from mart.session_funnel order by session_id").df()
    assert s.best_premium.tolist() == [1400.0, 1700.0]
    assert s.bound_carrier.tolist()[0] == "y" and s.n_requests.tolist() == [3, 1]


def test_same_draws_same_tables_and_panel_order_does_not_matter():
    d = simulate.draws()
    a, b = simulate.simulate(d), simulate.simulate(d, list(reversed(simulate.PANEL)))
    for name in ("sessions", "quote_requests", "clicks"):
        pd.testing.assert_frame_equal(a[name], b[name])
    assert sorted(a["binds"].session_id) == sorted(b["binds"].session_id)


def test_request_log_changes_only_from_the_tracking_change():
    data = simulate.simulate()
    r = data["quote_requests"].merge(data["sessions"], on="session_id")
    per = r.groupby(r.started_at.dt.date >= simulate.TRACKING_CHANGE).size() / \
        data["sessions"].groupby(data["sessions"].started_at.dt.date >= simulate.TRACKING_CHANGE).size()
    assert per[False] == 1.0 and 1.3 < per[True] < 1.6


def test_candidate_only_quotes_auto():
    q = simulate.simulate(carriers=[simulate.CANDIDATE])["carrier_quotes"]
    s = simulate.simulate()["sessions"].set_index("session_id")
    assert set(s.loc[q.session_id, "line"]) == {"auto"}


def test_two_proportion_matches_a_hand_calculation():
    r = counting.two_proportion(50, 500, 50, 1000)
    assert r["before"] == 0.1 and r["after"] == 0.05 and r["diff_pp"] == pytest.approx(-5.0)
    assert r["p_value"] < 0.001


def test_detector_finds_the_logging_change_without_being_told(summary):
    c = summary["counting_change"]
    assert c["logging_break"]["week"] == str(simulate.TRACKING_CHANGE)
    assert c["relative_drop_per_request_pct"] < -25  # the dashboard rate falls by a quarter or more
    lo, hi = c["quote_to_bind_per_session"]["ci_pp"]
    assert lo < 0 < hi and c["quote_to_bind_per_session"]["p_value"] > 0.05  # shoppers did not change
    assert c["share_of_drop_from_request_count_pct"] > 90


def test_carrier_estimate_lands_near_the_replayed_truth(summary):
    e, t = summary["new_carrier"]["estimate"], summary["new_carrier"]["truth"]
    assert e["added_binds_ci"][0] <= t["added_binds"] <= e["added_binds_ci"][1]
    assert e["added_commission_ci"][0] <= t["added_commission"] <= e["added_commission_ci"][1]
    assert abs(e["added_binds"] / t["added_binds"] - 1) < 0.15
    assert abs(e["candidate_binds"] / t["candidate_binds"] - 1) < 0.2
    assert 0 < e["added_binds"] < e["candidate_binds"]  # some of its policies come from the panel


def test_estimate_does_not_read_the_replay(monkeypatch):
    """Only the candidate's own rating engine may be simulated; the panel replay is truth-only."""
    calls = []
    real = simulate.simulate

    def spy(d=None, carriers=None):
        calls.append([c.carrier_id for c in carriers or simulate.PANEL])
        return real(d, carriers)

    con = duckdb.connect()
    d = simulate.draws()
    simulate.load(con, real(d))
    metrics.build(con)
    monkeypatch.setattr(carrier.simulate, "simulate", spy)
    carrier.estimate(con, d)
    assert calls == [[simulate.CANDIDATE.carrier_id]]


def test_memo_quotes_the_summary(summary):
    text = memo.to_markdown(summary)
    e = summary["new_carrier"]["estimate"]
    assert f"{e['added_binds']:,.0f} more binds" in text
    assert f"{100 * summary['counting_change']['quote_to_bind_per_request']['after']:.1f}%" in text
    assert "Do we act on it?\n\n**No." in text


def test_committed_results_are_current():
    out = subprocess.run([sys.executable, "-m", "quote_funnel", "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    committed = json.loads((RESULTS / "summary.json").read_text())
    assert committed["source_rows"]["sessions"] == 38929
