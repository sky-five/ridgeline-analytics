"""The renewals-at-risk list: only live subscriptions, the same score as the comparison, honest flags and reasons,
and the committed CSV must match a fresh run."""
import io
import re

import pandas as pd
import pytest

from customer_health.at_risk import AS_OF, AT_RISK, REASONS, at_risk_list
from customer_health.features import HISTORY_END, build_snapshots
from customer_health.model import RISK_SHARE, SCORE_RULES
from pipelines.engine import world_as_of

PAGE = AT_RISK.parents[2] / "reports" / "pages" / "renewals-at-risk.md"


@pytest.fixture(scope="module")
def world():
    return world_as_of(HISTORY_END)


@pytest.fixture(scope="module")
def risk(world):
    return at_risk_list(world, build_snapshots(world))


def test_scored_the_morning_after_the_history():
    assert AS_OF == pd.Timestamp("2026-07-01")


def test_one_row_per_live_subscription(world, risk):
    ch = world["subscription_changes"].sort_values("changed_at")
    last = ch[ch.changed_at < AS_OF].groupby("subscription_id").tail(1)
    live = last[last.change_type != "cancel"]
    assert risk.account_id.is_unique
    assert set(risk.account_id) == set(live.account_id)
    assert risk.mrr_usd.sum() == live.mrr_after.sum()


def test_each_method_flags_its_riskiest_fifth(risk):
    n = round(len(risk) * RISK_SHARE)
    assert risk.flagged_by_score.sum() == risk.flagged_by_model.sum() == n
    # nobody unflagged is riskier than someone flagged
    assert risk[~risk.flagged_by_score].health_score.min() >= risk[risk.flagged_by_score].health_score.max()
    assert risk[~risk.flagged_by_model].model_risk.max() <= risk[risk.flagged_by_model].model_risk.min()


def test_reasons_add_up_to_the_score(risk):
    assert set(REASONS) == {(col, rule) for col, rule, _ in SCORE_RULES}
    points = {REASONS[(col, rule)]: p for col, rule, p in SCORE_RULES}
    for _, row in risk.iterrows():
        fired = [r for r in str(row.reasons).split("; ") if r and r != "nan"]
        assert 100 - sum(points[r] for r in fired) == row.health_score


def test_list_is_sorted_worst_first(risk):
    assert risk.health_score.is_monotonic_increasing
    assert risk.iloc[0].flagged_by_score


def test_committed_list_matches_a_fresh_run(risk):
    buf = io.StringIO()
    risk.to_csv(buf, index=False)
    assert buf.getvalue() == AT_RISK.read_text()


def test_page_reads_only_tables_the_export_writes():
    tables = set(re.findall(r"ridgeline\.(\w+)", PAGE.read_text()))
    assert tables == {"health_at_risk", "health_compare"}
    sources = PAGE.parents[1] / "sources" / "ridgeline"
    for t in tables:
        assert (sources / f"{t}.sql").read_text().strip() == f"select * from reporting.{t}"
