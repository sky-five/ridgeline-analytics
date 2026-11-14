"""The quote funnel's dashboard tables: they come from the committed results, agree with each other,
and the page reads only tables (and columns) the export writes."""
import json
import re

import pandas as pd
import pytest

from quote_funnel.report import SUMMARY, WEEKLY, tables

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "quote-funnel.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_export_writes_five_tables(t):
    assert set(t) == {"quote_funnel_summary", "quote_funnel_weekly", "quote_funnel_segments",
                      "quote_funnel_carrier", "quote_funnel_lost_binds"}
    assert len(t["quote_funnel_summary"]) == 1
    assert len(t["quote_funnel_weekly"]) == 26
    assert len(t["quote_funnel_segments"]) == 4
    assert len(t["quote_funnel_carrier"]) == 3
    assert len(t["quote_funnel_lost_binds"]) == 12


def test_weeks_add_up_to_the_source_rows(t, s):
    w = t["quote_funnel_weekly"]
    assert w["sessions"].sum() == s["source_rows"]["sessions"]
    assert w["requests"].sum() == s["source_rows"]["quote_requests"]
    assert w["bound_sessions"].sum() == s["source_rows"]["binds"]
    assert t["quote_funnel_segments"]["sessions"].sum() == s["source_rows"]["sessions"]


def test_weekly_rates_recompute_from_counts(t):
    w = t["quote_funnel_weekly"]
    assert w["quote_to_bind"].tolist() == pytest.approx((w["bound_sessions"] / w["quoted_sessions"]).tolist(),
                                                        rel=1e-4)
    assert w["quote_to_bind_per_request"].tolist() == pytest.approx(
        (w["bound_sessions"] / w["quoted_requests"]).tolist(), rel=1e-4)


def test_logging_break_marks_where_the_two_rates_part(t):
    """Before the break both rates are the same number; after it the per-request one is always lower."""
    summ, w = t["quote_funnel_summary"].iloc[0], t["quote_funnel_weekly"]
    assert summ["break_week"] == summ["true_break_week"] == pd.Timestamp("2026-04-06").date()
    before, after = w[~w["after_break"]], w[w["after_break"]]
    assert len(before) == len(after) == 13
    assert (before["quote_to_bind"] == before["quote_to_bind_per_request"]).all()
    assert (after["quote_to_bind_per_request"] < after["quote_to_bind"] * 0.8).all()


def test_summary_rates_match_the_teardown(t, s):
    summ = t["quote_funnel_summary"].iloc[0]
    cc = s["counting_change"]
    assert summ["per_request_diff"] == pytest.approx(cc["quote_to_bind_per_request"]["diff_pp"] / 100)
    assert summ["per_session_ci_low"] < 0 < summ["per_session_ci_high"]
    assert summ["relative_drop_per_request"] < -0.25
    assert summ["quote_to_bind"] == s["funnel"]["quote_to_bind"]


def test_segments_in_page_order_with_labels(t):
    seg = t["quote_funnel_segments"]
    assert seg["segment"].tolist() == ["auto_standard", "auto_non_standard", "home_standard", "home_non_standard"]
    assert seg["segment_label"].notna().all()


def test_carrier_estimate_next_to_the_replayed_truth(t, s):
    c = t["quote_funnel_carrier"].set_index("measure")
    nc = s["new_carrier"]
    assert c.loc["Added binds", "estimate"] == nc["estimate"]["added_binds"]
    assert c.loc["Added binds", "truth"] == nc["truth"]["added_binds"]
    assert c.loc["Added commission", "truth"] == nc["truth"]["added_commission"]
    assert c.loc[["Added binds", "Added commission"], "ci_covers"].all()
    assert pd.isna(c.loc["Policies the candidate writes", "ci_covers"])


def test_lost_binds_add_up(t, s):
    lost = t["quote_funnel_lost_binds"].groupby("source")["binds_lost"].sum()
    nc = s["new_carrier"]
    for source, side in (("Estimate", "estimate"), ("Replayed truth", "truth")):
        added = nc[side]["candidate_binds"] - lost[source]
        assert added == pytest.approx(nc[side]["added_binds"], abs=0.5)


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
    named = set(re.findall(r"(?:column|value|id|x)=(\w+)", text))
    assert named <= known, named - known


def test_nightly_smoke_test_checks_the_page():
    assert "quote-funnel/" in NIGHTLY.read_text()


def test_missing_results_export_nothing(monkeypatch, tmp_path):
    import quote_funnel.report as report

    monkeypatch.setattr(report, "WEEKLY", tmp_path / "missing.csv")
    assert report.tables() == {}
    assert WEEKLY.exists()
