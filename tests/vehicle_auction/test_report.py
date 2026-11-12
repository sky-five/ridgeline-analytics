"""The vehicle auction's dashboard tables: they come from the committed results, agree with each other,
and the page reads only tables the export writes."""
import json
import re

import pandas as pd
import pytest

from vehicle_auction.report import SUMMARY, tables

PAGE = SUMMARY.parents[2] / "reports" / "pages" / "vehicle-auction.md"
NIGHTLY = SUMMARY.parents[2] / ".github" / "workflows" / "nightly.yml"


@pytest.fixture(scope="module")
def t():
    return tables()


def test_export_writes_three_tables(t):
    assert set(t) == {"auction_channels", "auction_weekly", "auction_reserve_test"}
    assert len(t["auction_channels"]) == 3
    assert len(t["auction_weekly"]) == 26 * 3
    assert len(t["auction_reserve_test"]) == 2


def test_weeks_add_up_to_the_channel_totals(t):
    w = t["auction_weekly"].groupby("channel")[["offered", "vehicles_offered"]].sum()
    c = t["auction_channels"].set_index("channel")
    assert w["offered"].to_dict() == c["listings_offered"].to_dict()
    assert w["vehicles_offered"].to_dict() == c["vehicles_offered"].to_dict()
    assert c["listings_offered"].sum() == json.loads(SUMMARY.read_text())["listings_offered"]


def test_weekly_rates_are_in_definition_order_and_recompute(t):
    w = t["auction_weekly"]
    assert (w["sell_through_on_block"] <= w["conversion_rate"]).all()
    assert w["sell_through_on_block"].tolist() == pytest.approx((w["sold_on_block"] / w["offered"]).tolist(), abs=1e-4)
    assert w["conversion_rate"].tolist() == pytest.approx(
        ((w["sold_on_block"] + w["if_sales"]) / w["offered"]).tolist(), abs=1e-4)
    assert w["vehicle_sell_through"].tolist() == pytest.approx(
        (w["vehicles_sold"] / w["vehicles_offered"]).tolist(), abs=1e-4)


def test_late_cohorts_have_lower_vehicle_sell_through(t):
    """The page says the vehicle line drops at the right edge because late cars had fewer relists."""
    w = t["auction_weekly"].assign(sale_week=lambda d: pd.to_datetime(d["sale_week"]))
    last = w[w["sale_week"] == w["sale_week"].max()]
    rest = w[w["sale_week"] < w["sale_week"].max() - pd.Timedelta(weeks=2)]
    for ch in last["channel"]:
        assert last.loc[last.channel == ch, "vehicle_sell_through"].item() < \
            rest.loc[rest.channel == ch, "vehicle_sell_through"].mean()


def test_channels_in_page_order_with_labels(t):
    c = t["auction_channels"]
    assert c["channel"].tolist() == ["in_lane", "simulcast", "online_timed"]
    assert c["channel_label"].notna().all()
    assert t["auction_weekly"]["channel_label"].notna().all()


def test_reserve_readout_matches_the_summary(t):
    rt = json.loads(SUMMARY.read_text())["reserve_test"]
    r = t["auction_reserve_test"].set_index("unit")
    assert r.loc["rate", "diff"] == rt["conversion"]["diff"]
    assert r.loc["rate", "true_diff"] == rt["true_conversion_diff"]
    assert r.loc["usd", "diff"] == rt["proceeds_per_offered_usd"]["diff"]
    assert r.loc["usd", "true_diff"] == rt["true_proceeds_diff_usd"]
    assert r["ci_covers"].all()
    assert (r["srm_p_value"] > 0.01).all()


def test_page_reads_only_tables_the_export_writes(t):
    used = set(re.findall(r"ridgeline\.(\w+)", PAGE.read_text()))
    assert used == set(t)
    sources = PAGE.parents[1] / "sources" / "ridgeline"
    for name in used:
        assert (sources / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_page_columns_exist(t):
    """Every column the page names in a component is in its table (Evidence would render a blank)."""
    text = PAGE.read_text()
    known = set().union(*(df.columns for df in t.values()))
    named = set(re.findall(r"(?:column|value|id)=(\w+)", text)) - {"channel"}
    assert named <= known, named - known


def test_nightly_smoke_test_checks_the_page():
    assert "vehicle-auction/" in NIGHTLY.read_text()


def test_missing_results_export_nothing(monkeypatch, tmp_path):
    import vehicle_auction.report as report

    monkeypatch.setattr(report, "WEEKLY", tmp_path / "missing.csv")
    assert report.tables() == {}

