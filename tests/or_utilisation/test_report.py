"""The operating-room ROI dashboard tables: they come from the committed results and metric_spec.yml, agree with
each other, and the page reads only tables (and columns) the export writes."""
import json
import re

import pandas as pd
import pytest

from or_utilisation import spec
from or_utilisation.report import SUMMARY, WEEKLY, tables

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "or-utilisation.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_export_writes_six_tables(t):
    assert set(t) == {"or_roi_summary", "or_roi_framings", "or_roi_claims", "or_roi_checks", "or_roi_weekly",
                      "or_roi_metric_spec"}
    assert len(t["or_roi_summary"]) == 1
    assert len(t["or_roi_framings"]) == 4
    assert len(t["or_roi_claims"]) == 4
    assert len(t["or_roi_checks"]) == 4 * 5
    assert len(t["or_roi_weekly"]) == 26
    assert len(t["or_roi_metric_spec"]) == 7
    assert "or_roi_tables()" in EXPORT.read_text()


def test_framings_in_order_against_the_truth(t, s):
    f = t["or_roi_framings"].set_index("framing")
    assert list(f.index) == ["Claimed", "Before/after", "Defended", "Replayed truth"]
    assert f.loc["Replayed truth", "added_minutes"] == s["truth"]["added_in_block_minutes"] == 6332
    assert f.loc["Claimed", "added_minutes"] == 30857
    assert f["added_minutes"].is_monotonic_decreasing  # each framing is closer to the truth than the one above
    assert f.loc["Claimed", "over_truth"] == pytest.approx(s["roi"]["claimed_over_truth"], abs=0.05)
    d = f.loc["Defended"]
    assert d["ci_low"] <= f.loc["Replayed truth", "added_minutes"] <= d["ci_high"]
    assert f.drop(index="Defended")["ci_low"].isna().all()  # only the defended estimate has an interval


def test_net_return_follows_the_stated_assumptions(t):
    summ = t["or_roi_summary"].iloc[0]
    f = t["or_roi_framings"]
    expected = (f["added_minutes"] / 60 * summ["margin_per_patient_hour_usd"] - summ["rule_cost_usd"]).round()
    # money is computed from unrounded minutes: half a minute is $12.50 at $1,500 an hour
    assert f["net_usd"].tolist() == pytest.approx(expected.tolist(), abs=13)


def test_claims_and_checks_agree(t, s):
    claims, checks = t["or_roi_claims"], t["or_roi_checks"]
    assert claims["metric"].tolist() == [c["metric"] for c in s["claims"]]
    fired = checks[checks["flagged"]].groupby("claim_sort").size()
    assert claims["n_flags"].tolist() == [fired.get(i, 0) for i in claims["sort"]]
    assert claims["n_flags"].tolist() == [3, 3, 2, 1]
    assert claims["change_pp"].tolist() == pytest.approx(((claims["after"] - claims["before"]) * 100).tolist(),
                                                         abs=0.01)
    assert set(checks["result"]) == {"flagged", "passes"}


def test_weekly_marks_the_rule_and_adds_up(t, s):
    w = t["or_roi_weekly"]
    start = t["or_roi_summary"].loc[0, "policy_start"]
    assert start == pd.Timestamp("2026-04-06").date()
    assert w["after_rule"].sum() == 13
    assert (w["after_rule"] == (w["period"] == "after")).all()
    assert w["completed_cases"].sum() == s["cases_completed"]
    assert w["allocated_minutes"].sum() == s["blocks"] * 480


def test_metric_spec_panel_is_the_spec_file(t, s):
    m = t["or_roi_metric_spec"].set_index("metric")
    assert list(m.index) == list(spec.metrics())
    for name, row in spec.metrics().items():
        assert m.loc[name, "numerator"] == row["numerator"]
        assert m.loc[name, "denominator"] == row["denominator"]
        assert m.loc[name, "before"] == s["periods"]["before_all"][name]
    assert m.loc["room_utilisation", "after_text"] == "59.5%"


def test_page_reads_only_tables_the_export_writes(t):
    used = set(re.findall(r"ridgeline\.(\w+)", PAGE.read_text()))
    assert used == set(t)
    sources = PAGE.parents[1] / "sources" / "ridgeline"
    for name in used:
        assert (sources / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_page_columns_exist(t):
    """Every column the page names in a component or panel is in its table (Evidence would render a blank)."""
    text = PAGE.read_text()
    known = set().union(*(df.columns for df in t.values()))
    named = set(re.findall(r"(?:column|value|id|x)=(\w+)", text)) | set(re.findall(r"\{m\.(\w+)\}", text))
    assert named <= known, named - known


def test_no_value_starts_a_line():
    """A <Value> at the start of a line splits the paragraph in Evidence's markdown."""
    assert not re.search(r"^<Value", PAGE.read_text(), flags=re.M)


def test_nightly_smoke_test_checks_the_page():
    assert "or-utilisation/" in NIGHTLY.read_text()


def test_missing_results_export_nothing(monkeypatch, tmp_path):
    import or_utilisation.report as report

    monkeypatch.setattr(report, "WEEKLY", tmp_path / "missing.csv")
    assert report.tables() == {}
    assert WEEKLY.exists()
