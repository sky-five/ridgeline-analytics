import json

import pytest

from experiments.analysis import RESULTS, _round, analyse, replays
from experiments.peeking import aa_tests
from experiments.simulate import Design, daily_cumulative, simulate
from experiments.stats import power


@pytest.fixture(scope="module")
def result():
    return analyse()


def test_simulation_is_deterministic():
    a, b = simulate(seed=3), simulate(seed=3)
    assert a.equals(b)
    assert not a.equals(simulate(seed=4))


def test_planted_rates_come_back_on_a_large_sample():
    big = simulate(Design(arrivals_per_day=10_000), seed=1)
    rates = big.groupby("arm")["activated"].mean()
    assert rates["control"] == pytest.approx(0.30, abs=0.005)
    assert rates["treatment"] == pytest.approx(0.34, abs=0.005)
    assert big.groupby("arm").size()["treatment"] / len(big) == pytest.approx(0.5, abs=0.005)


def test_funnel_steps_only_narrow():
    df = simulate()
    assert (df.created_job >= df.measured_roof).all() and (df.measured_roof >= df.sent_proposal).all()


def test_daily_cumulative_ends_at_the_totals():
    df = simulate()
    last = daily_cumulative(df).iloc[-1]
    assert last.n_control + last.n_treatment == len(df)
    assert last.x_control + last.x_treatment == df.activated.sum()


def test_readout_interval_covers_the_planted_effect(result):
    res = result["result"]
    assert res["ci_low"] <= result["design"]["planted_lift"] <= res["ci_high"]
    assert res["n_control"] + res["n_treatment"] == 28 * 170


def test_repeated_runs_recover_the_effect_at_the_designed_rate():
    d = Design()
    r = replays(d, n_runs=2000, seed=5)
    # 95% intervals cover the true lift about 95% of the time
    assert r["ci_covers_planted"] == pytest.approx(0.95, abs=0.015)
    # the share of significant runs matches the analytic power of the planned size
    assert r["significant"] == pytest.approx(power(d.p_control, d.lift, d.days * d.arrivals_per_day // 2), abs=0.03)
    assert r["median_diff"] == pytest.approx(d.lift, abs=0.004)


def test_srm_check_passes_the_clean_split_and_catches_the_tracking_bug(result):
    assert not result["srm"]["alarm"]
    bug = result["srm_tracking_bug"]
    assert bug["alarm"]
    # the bug inflates the apparent lift well past the planted one
    assert bug["biased_result"]["diff"] > 1.5 * result["design"]["planted_lift"]


def test_peeking_inflates_false_positives():
    r = aa_tests(n_tests=4000, seed=2)
    assert r.false_positive_fixed == pytest.approx(0.05, abs=0.012)
    assert r.false_positive_peeking > 3 * r.false_positive_fixed


def test_committed_results_are_up_to_date(result):
    assert json.loads(RESULTS.read_text(encoding="utf-8")) == json.loads(json.dumps(_round(result)))
