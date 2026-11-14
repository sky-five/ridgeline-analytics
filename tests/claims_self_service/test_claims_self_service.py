"""Builds the claims warehouse once (simulate + load + dbt build, about 10 s) and checks the simulator's
planted patterns, the star schema against the raw rows, every headline metric from MetricFlow against an
independent pandas count, the semantic layer's guard rails, and the committed results."""
from datetime import date

import duckdb
import pandas as pd
import pytest

from claims_self_service import metrics
from claims_self_service.load import dbt_build, load
from claims_self_service.run import SUMMARY, summary, to_json
from claims_self_service.simulate import AS_OF, HAIL_REGION, HAIL_START, TERM_DAYS, simulate

AS_OF_TS = pd.Timestamp(AS_OF)


@pytest.fixture(scope="module")
def book():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, book):
    path = tmp_path_factory.mktemp("claims") / "claims.duckdb"
    load(path, book)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def claims(book):
    return book.claims.merge(book.policies, on="policy_id")


def earned(policies: pd.DataFrame, first: pd.Timestamp | None = None, last: pd.Timestamp = AS_OF_TS) -> pd.Series:
    """Earned premium per policy between first and last (inclusive), computed straight from the policy rows."""
    lo = policies["start_date"] if first is None else policies["start_date"].clip(lower=first)
    hi = policies["end_date"].clip(upper=last)
    days = ((hi - lo).dt.days + 1).clip(lower=0)
    return policies["annual_premium"] * days / TERM_DAYS


def q(db, ms, gb=None, where=None):
    return metrics.query(ms, gb, where, db=db)


# --- the simulator ---------------------------------------------------------------------------


def test_simulation_is_seeded(book):
    again = simulate()
    pd.testing.assert_frame_equal(book.claims, again.claims)
    pd.testing.assert_frame_equal(book.policies, again.policies)


def test_claims_are_consistent(book):
    c = book.claims
    assert (c["loss_date"] <= c["reported_date"]).all() and (c["reported_date"] <= AS_OF_TS).all()
    open_ = c["status"] == "open"
    assert c.loc[open_, "closed_date"].isna().all() and c.loc[~open_, "closed_date"].notna().all()
    assert (c.loc[~open_, "closed_date"] <= AS_OF_TS).all()
    assert (c.loc[c["status"].isin(["denied", "withdrawn"]), "incurred_amount"] == 0).all()
    assert (c.loc[open_, "incurred_amount"] > c.loc[open_, "paid_amount"]).all()  # reserve above paid to date


def test_planted_hailstorm_and_direct_denials(claims):
    home_south = claims[(claims["line_of_business"] == "homeowners") & (claims["region"] == HAIL_REGION)]
    by_month = home_south.groupby(home_south["loss_date"].dt.to_period("M")).size()
    storm = by_month[pd.Period(HAIL_START, "M")]
    assert storm > 5 * by_month.drop(pd.Period(HAIL_START, "M")).median()
    decided = claims[claims["status"].isin(["approved", "denied"])]
    deny = decided.groupby("channel")["status"].apply(lambda s: (s == "denied").mean())
    assert deny["direct"] > 1.5 * max(deny["agent"], deny["broker"])


# --- the star schema -------------------------------------------------------------------------


def test_marts_keep_every_row_and_dollar(db, book):
    with duckdb.connect(str(db), read_only=True) as con:
        n_claims, incurred = con.execute("select count(*), sum(incurred_amount) from main.fct_claims").fetchone()
        n_pol = con.execute("select count(*) from main.dim_policy").fetchone()[0]
        prem = con.execute("select policy_id, sum(earned_premium) as ep, sum(earned_days) as days "
                           "from main.fct_premium_monthly group by policy_id").df().set_index("policy_id")
    assert n_claims == len(book.claims) and n_pol == len(book.policies)
    assert float(incurred) == pytest.approx(book.claims["incurred_amount"].sum(), abs=0.01)
    p = book.policies.set_index("policy_id")
    days = (p["end_date"].clip(upper=AS_OF_TS) - p["start_date"]).dt.days + 1
    assert (prem["days"].reindex(p.index) == days).all()  # months add up to the days in force, no gaps or overlaps
    assert prem["ep"].sum() == pytest.approx(earned(book.policies).sum(), rel=1e-9)


# --- metrics from MetricFlow vs an independent count ------------------------------------------


def test_loss_ratio_by_line_matches_pandas(db, book, claims):
    got = q(db, ["loss_ratio"], ["policy__line_of_business"]).set_index("policy__line_of_business")["loss_ratio"]
    ep = earned(book.policies).groupby(book.policies["line_of_business"]).sum()
    want = claims.groupby("line_of_business")["incurred_amount"].sum() / ep
    pd.testing.assert_series_equal(got.astype(float), want, check_names=False, check_index_type=False, rtol=1e-9)


def test_hail_month_loss_ratio_matches_pandas(db, book, claims):
    first = pd.Timestamp(HAIL_START.replace(day=1))
    last = first + pd.offsets.MonthEnd(0)
    pol = book.policies[(book.policies["line_of_business"] == "homeowners") & (book.policies["region"] == HAIL_REGION)]
    c = claims[claims["policy_id"].isin(pol["policy_id"]) & claims["loss_date"].between(first, last)]
    want = c["incurred_amount"].sum() / earned(pol, first, last).sum()
    got = q(db, ["loss_ratio"], ["metric_time__month"],
            ["{{ Dimension('policy__line_of_business') }} = 'homeowners'",
             f"{{{{ Dimension('policy__region') }}}} = '{HAIL_REGION}'"])
    got = got[pd.to_datetime(got["metric_time__month"]) == first]["loss_ratio"].iloc[0]
    assert float(got) == pytest.approx(want, rel=1e-9)
    assert want > 5  # the storm month's losses are several times that month's premium


def test_cycle_time_and_approval_rate_by_channel_match_pandas(db, claims):
    got = q(db, ["claim_cycle_time_days", "approval_rate"], ["policy__channel"]).set_index("policy__channel")
    closed = claims[claims["status"] != "open"]
    cycle = (closed["closed_date"] - closed["reported_date"]).dt.days.groupby(closed["channel"]).mean()
    decided = claims[claims["status"].isin(["approved", "denied"])]
    approval = decided.groupby("channel")["status"].apply(lambda s: (s == "approved").mean())
    for ch in cycle.index:
        assert float(got.loc[ch, "claim_cycle_time_days"]) == pytest.approx(cycle[ch], rel=1e-9)
        assert float(got.loc[ch, "approval_rate"]) == pytest.approx(approval[ch], rel=1e-9)


def test_cycle_time_counts_claims_in_the_month_they_closed(db, claims):
    got = q(db, ["closed_claims"], ["metric_time__month"]).dropna(subset=["metric_time__month"])
    got = got.set_index(pd.to_datetime(got["metric_time__month"]).dt.to_period("M"))["closed_claims"]
    closed = claims[claims["status"] != "open"]
    want = closed.groupby(closed["closed_date"].dt.to_period("M")).size()
    assert (got.astype(int).reindex(want.index, fill_value=0) == want).all()


# --- the semantic layer as a self-service surface --------------------------------------------


def test_every_metric_is_documented_and_sliceable(db):
    ms = {m["name"]: m for m in metrics.list_metrics(db)}
    for name in metrics.HEADLINE:
        assert len(ms[name]["description"]) > 40
        assert set(metrics.SLICES) <= set(ms[name]["dimensions"])
    assert all(m["description"] for m in ms.values())


def test_loss_ratio_by_peril_is_refused(db):
    """Premium is not earned by peril, so the layer refuses the slice instead of returning a wrong number."""
    assert "peril__peril_group" not in {d for m in metrics.list_metrics(db) if m["name"] == "loss_ratio"
                                        for d in m["dimensions"]}
    with pytest.raises(Exception, match="peril"):
        q(db, ["loss_ratio"], ["peril__peril_group"])
    assert not q(db, ["incurred_losses"], ["peril__peril_group"]).empty  # losses alone can be cut by peril


def test_explain_shows_the_sql(db):
    sql = metrics.explain(["approval_rate"], ["policy__region"], db=db)
    assert "fct_claims" in sql and "dim_policy" in sql


# --- committed results -----------------------------------------------------------------------


def test_committed_summary_is_current(db, book):
    fresh = summary(db, book)
    assert SUMMARY.read_text() == to_json(fresh)
    assert fresh["as_of"] == date(2026, 6, 30).isoformat()
    assert fresh["claims"] == sum(fresh["claims_by_status"].values())
