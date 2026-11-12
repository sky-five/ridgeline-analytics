"""Builds the auction warehouse once (simulate + load + dbt build, about 15 s) and checks the metric
definitions against an independent pandas count, the readout against the planted truth, and the
committed results."""
import json

import duckdb
import pandas as pd
import pytest

from vehicle_auction.load import dbt_build, load
from vehicle_auction.readout import RESULTS, proportion_diff, readout, srm_p_value, summary, to_json
from vehicle_auction.report import WEEKLY, to_csv, weekly_frame
from vehicle_auction.simulate import TEST_START, arm_for, simulate


@pytest.fixture(scope="module")
def auction():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, auction):
    path = tmp_path_factory.mktemp("auction") / "auction.duckdb"
    load(path, auction)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


def frame(con, sql) -> pd.DataFrame:
    return con.execute(sql).df()


# --- the simulator ---------------------------------------------------------------------------

def test_simulation_is_deterministic(auction):
    again = simulate()
    pd.testing.assert_frame_equal(auction.listings, again.listings)
    pd.testing.assert_frame_equal(auction.bids, again.bids)


def test_split_is_a_stable_hash_near_half():
    ids = [f"VEH-{i:06d}" for i in range(1, 20_001)]
    share = sum(arm_for(v) == "treatment" for v in ids) / len(ids)
    assert 0.49 < share < 0.51
    assert arm_for("VEH-000123") == arm_for("VEH-000123")


def test_only_cars_consigned_in_the_test_window_are_assigned(auction):
    first = auction.listings[auction.listings["run_number"] == 1].set_index("vehicle_id")["sale_date"]
    assigned = set(auction.truth["vehicle_id"])
    in_window = set(first[first >= pd.Timestamp(TEST_START)].index)
    assert assigned == in_window


def test_counterfactual_stays_out_of_the_warehouse(con):
    cols = {c for (c,) in con.execute(
        "select column_name from information_schema.columns where table_schema = 'raw_auction'").fetchall()}
    assert not cols & {"control_status", "treatment_status", "reserve_z", "guidance", "in_test"}


# --- metric definitions: dbt marts against an independent pandas count from the raw frames ---

def _pandas_channel_metrics(auction) -> pd.DataFrame:
    lst = auction.listings
    offered = lst[lst["status"] != "withdrawn"]
    by_listing = offered.groupby("channel").agg(
        listings_offered=("listing_id", "size"),
        sold_on_block=("status", lambda s: (s == "sold").sum()),
        converted=("status", lambda s: s.isin(["sold", "if_sale"]).sum()),
    )
    by_vehicle = offered.assign(conv=offered["status"].isin(["sold", "if_sale"])).groupby(
        ["channel", "vehicle_id"])["conv"].any().groupby("channel").agg(["size", "sum"])
    return pd.DataFrame({
        "listings_offered": by_listing["listings_offered"],
        "sell_through_on_block": by_listing["sold_on_block"] / by_listing["listings_offered"],
        "conversion_rate": by_listing["converted"] / by_listing["listings_offered"],
        "vehicles_offered": by_vehicle["size"],
        "vehicle_sell_through": by_vehicle["sum"] / by_vehicle["size"],
    })


def test_sell_through_by_channel_matches_an_independent_count(con, auction):
    mart = frame(con, "select * from sell_through_by_channel").set_index("channel").sort_index()
    expected = _pandas_channel_metrics(auction).sort_index()
    for col in expected.columns:
        assert mart[col].tolist() == pytest.approx(expected[col].tolist()), col


def test_weekly_rates_recompute_from_their_counts(con):
    w = frame(con, "select * from sell_through_weekly")
    assert len(w) == 26 * 3
    assert (w["listings"] == w["withdrawn"] + w["offered"]).all()
    assert (w["offered"] == w["sold_on_block"] + w["if_sales"] + w["no_sales"]).all()
    assert w["sell_through_on_block"].tolist() == pytest.approx((w["sold_on_block"] / w["offered"]).tolist())


def test_withdrawn_listings_are_not_in_the_denominator(con):
    """Counting withdrawn cars as offered would understate sell-through: the definition must exclude them."""
    row = con.execute("""
        select count(*) filter (where is_sold_on_block) / count(*) filter (where is_offered),
               count(*) filter (where is_sold_on_block) / count(*)
        from fct_listings
    """).fetchone()
    right, wrong = row
    total = frame(con, "select sum(sold_on_block) s, sum(listings_offered) o from sell_through_by_channel")
    assert right == pytest.approx(total["s"][0] / total["o"][0])
    assert right - wrong > 0.01


def test_relists_make_vehicle_basis_higher_than_listing_basis(con):
    c = frame(con, "select * from sell_through_by_channel")
    assert (c["vehicles_offered"] < c["listings_offered"]).all()
    assert (c["vehicle_sell_through"] > c["conversion_rate"] + 0.05).all()


def test_simulcast_sells_through_best_and_timed_online_worst(con):
    c = frame(con, "select channel, sell_through_on_block from sell_through_by_channel "
                   "order by sell_through_on_block desc")
    assert c["channel"].tolist() == ["simulcast", "in_lane", "online_timed"]


# --- the reserve-price test readout ----------------------------------------------------------

def test_stat_helpers():
    assert srm_p_value(500, 500) == pytest.approx(1.0)
    assert srm_p_value(550, 450) < 0.01
    d = proportion_diff(50, 100, 60, 100)
    assert d.diff == pytest.approx(0.10)
    assert d.ci_low < 0.10 < d.ci_high
    assert d.ci_high - d.ci_low == pytest.approx(2 * 1.959964 * ((0.25 + 0.24) / 100) ** 0.5)


@pytest.fixture(scope="module")
def result(db, auction):
    return readout(db, auction)


def test_split_passes_the_sample_ratio_check(result):
    assert result.srm_p_value > 0.01


def test_aa_split_before_the_test_shows_no_difference(result):
    assert result.aa_conversion_p_value > 0.05


def test_ci_covers_the_true_effect_on_the_same_cars(result):
    assert result.ci_covers_truth
    assert result.conversion.ci_low > 0  # the lower reserve sells more first runs
    p = result.proceeds_per_offered_usd
    assert p.ci_low <= result.true_proceeds_diff_usd <= p.ci_high


def test_price_when_sold_drops_because_the_sold_cars_differ(result):
    """The treatment arm sells cars control would have no-sold, so its average sold price is lower even
    though the money per car offered is higher. The readout must not compare sold prices alone."""
    assert result.price_to_book_when_sold_treatment < result.price_to_book_when_sold_control
    assert result.proceeds_per_offered_usd.diff > 0


def test_committed_results_are_current(db, auction):
    fresh = summary(db, auction)
    assert RESULTS.read_text() == to_json(fresh)
    committed = json.loads(RESULTS.read_text())
    assert committed["listings"] == 15064 and committed["vehicles"] == 12569


def test_committed_weekly_results_are_current(db):
    assert WEEKLY.read_text() == to_csv(weekly_frame(db))
