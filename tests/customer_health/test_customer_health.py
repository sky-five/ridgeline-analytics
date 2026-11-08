"""Snapshots must not see the future, the split must keep accounts on one side, and the committed results
must match a fresh run."""
import json

import pandas as pd
import pytest

from customer_health.features import FEATURES, HISTORY_END, HORIZON_DAYS, build_snapshots, snapshot_dates
from customer_health.model import RESULTS, SCORE_RULES, churn_in_riskiest, evaluate, health_score, is_test_account
from pipelines.engine import world_as_of


@pytest.fixture(scope="module")
def world():
    return world_as_of(HISTORY_END)


@pytest.fixture(scope="module")
def snaps(world):
    return build_snapshots(world)


def test_churn_window_ends_inside_the_history():
    last = snapshot_dates()[-1]
    assert last + pd.Timedelta(days=HORIZON_DAYS) <= pd.Timestamp(HISTORY_END)


def test_one_row_per_account_and_month_with_no_gaps(snaps):
    assert not snaps.duplicated(["snapshot", "account_id"]).any()
    assert snaps[FEATURES].notna().all().all()


def test_features_ignore_rows_after_the_snapshot(world, snaps):
    # moving every event to after the last snapshot must not change any snapshot's login counts
    late = dict(world)
    ev = world["events"].copy()
    ev["occurred_at"] = pd.Timestamp(HISTORY_END) + pd.Timedelta(days=1)
    late["events"] = ev
    shifted = build_snapshots(late)
    assert (shifted.logins_30d == 0).all()
    assert (shifted.login_trend == 0).all()
    # and labels and live accounts do not depend on events at all
    pd.testing.assert_series_equal(shifted.churned_60d, snaps.churned_60d)


def test_label_matches_cancels_in_the_window(world, snaps):
    ch = world["subscription_changes"]
    row = snaps[snaps.churned_60d == 1].iloc[0]
    c = ch[(ch.subscription_id == row.subscription_id) & (ch.change_type == "cancel")]
    assert ((c.changed_at >= row.snapshot) & (c.changed_at < row.snapshot + pd.Timedelta(days=HORIZON_DAYS))).any()


def test_only_live_subscriptions_are_snapshotted(world, snaps):
    ch = world["subscription_changes"].sort_values("changed_at")
    for _, row in snaps.sample(50, random_state=0).iterrows():
        before = ch[(ch.subscription_id == row.subscription_id) & (ch.changed_at < row.snapshot)]
        assert before.change_type.iloc[-1] != "cancel"


def test_health_score_rules():
    healthy = pd.DataFrame([dict.fromkeys(FEATURES, 0) | {"crew_size_rank": 3, "logins_30d": 20, "tenure_months": 12}])
    assert health_score(healthy).iloc[0] == 100
    worst = pd.DataFrame([dict.fromkeys(FEATURES, 0) | {
        "crew_size_rank": 0, "had_redo_60d": 1, "accuracy_tickets_30d": 2, "late_invoices_90d": 1,
        "login_trend": -1.0, "logins_30d": 0, "tenure_months": 1}])
    # every rule fires except the crew-of-2-5 one
    assert health_score(worst).iloc[0] == 100 - sum(p for _, _, p in SCORE_RULES) + 10 == 15


def test_split_is_stable_and_by_account(snaps):
    ids = snaps.account_id.unique()
    share = sum(map(is_test_account, ids)) / len(ids)
    assert 0.2 < share < 0.4
    assert [is_test_account(a) for a in ids[:20]] == [is_test_account(a) for a in ids[:20]]


def test_churn_in_riskiest_counts_per_month():
    idx = pd.MultiIndex.from_tuples([("m1", "a"), ("m1", "b"), ("m2", "c"), ("m2", "d")], names=["snapshot", "a"])
    risk = pd.Series([0.9, 0.1, 0.8, 0.2], index=idx)
    churned = pd.Series([1, 0, 0, 1], index=idx)
    assert churn_in_riskiest(risk, churned, share=0.5) == (0.5, 0.5)


def test_committed_results_match_a_fresh_run(snaps):
    fresh = json.loads(evaluate(snaps).to_json())
    assert fresh == json.loads(RESULTS.read_text())
    # both beat a coin flip on held-out accounts, and the riskiest fifth churns more than average
    assert fresh["auc_health_score"] > 0.55 and fresh["auc_model"] > 0.55
    assert fresh["churn_in_riskiest_score"] > fresh["churn_rate"]
    assert fresh["churn_in_riskiest_model"] > fresh["churn_rate"]
