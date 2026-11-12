"""The ARR page's tables: built once at the pinned snapshot, then checked against the dbt models and the
committed results, and against what the Evidence page and its source files ask for."""
import json
import re
from pathlib import Path

import duckdb
import pytest

from arr_source_of_truth.load import AS_OF
from arr_source_of_truth.report import STATUS_MEANING, WALK_STEPS, publish
from arr_source_of_truth.score import RESULTS

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
PAGE = ROOT / "reports" / "pages" / "arr-walk.md"


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    d = tmp_path_factory.mktemp("arr_report")
    counts = publish(AS_OF, d / "main.duckdb", d / "arr.duckdb")
    with duckdb.connect(str(d / "main.duckdb"), read_only=True) as con:
        yield counts, {name: con.execute(f"select * from reporting.{name}").df() for name in counts}


def test_walk_steps_add_up_every_month(published):
    _, t = published
    w = t["arr_walk_monthly"]
    steps = [c for c, _, k in WALK_STEPS if k == "step"]
    to_billing = w["crm_booked"] + w[steps[:6]].sum(axis=1)
    assert (to_billing.round(2) == w["billing_sales_led"].round(2)).all()
    to_net = w["billing_sales_led"] + w["seat_changes"] + w["cancellations"]
    assert (to_net.round(2) == w["net_change"].round(2)).all()


def test_walk_net_change_is_the_bridge_and_the_bridge_rolls_forward(published):
    _, t = published
    b, w = t["arr_bridge"], t["arr_walk_monthly"]
    moves = b[["new", "reactivation", "expansion", "contraction", "churn"]].sum(axis=1)
    assert ((b["opening"] + moves).round(2) == b["closing"].round(2)).all()
    assert (b["opening"].iloc[1:].values == b["closing"].iloc[:-1].values).all()
    assert ((b["closing"] - b["opening"]).round(2).tolist() == w["net_change"].round(2).tolist())


def test_long_walk_has_every_step_for_every_month(published):
    counts, t = published
    assert counts["arr_walk_steps"] == len(WALK_STEPS) * counts["arr_walk_monthly"]
    assert t["arr_walk_steps"]["step_order"].max() == len(WALK_STEPS)


def test_page_numbers_match_the_committed_results(published):
    _, t = published
    want = json.loads(RESULTS.read_text())
    meta = t["arr_meta"].iloc[0]
    assert meta["closing_arr"] == want["closing_arr"]
    assert meta["paying_customers"] == want["paying_customers"]
    assert meta["won_deals"] == want["won_deals"]
    assert meta["deals_matched"] == want["deals_matched"]
    status = dict(zip(t["arr_deal_status"]["status"], t["arr_deal_status"]["deals"], strict=True))
    assert status == want["status_counts"]
    assert len(t["arr_deal_flags"]) == want["won_deals"] - want["status_counts"]["agrees"]
    last = t["arr_walk_monthly"].iloc[-1]
    for col, _, _ in WALK_STEPS:
        assert last[col] == want["last_month"][col], col


def test_every_status_has_a_plain_meaning(published):
    _, t = published
    assert t["arr_deal_status"]["meaning"].notna().all()
    assert set(t["arr_deal_status"]["status"]) <= set(STATUS_MEANING)


def test_page_reads_only_tables_the_build_publishes(published):
    counts, _ = published
    page_sources = set(re.findall(r"ridgeline\.(\w+)", PAGE.read_text()))
    assert page_sources == set(counts)
    for name in counts:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"
