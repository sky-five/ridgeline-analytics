"""The reconciliation page's tables agree with the committed results, and the page reads only exported tables."""
import json
import re

import pytest

from report_reconciliation import dashboard, uat
from report_reconciliation.build import FAULTS
from report_reconciliation.dashboard import CHECKS, SUMMARY, tables

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "report-reconciliation.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text())


def test_export_writes_five_tables(t):
    assert set(t) == {"recon_summary", "recon_checks", "recon_faults", "recon_uat", "recon_samples"}
    assert len(t["recon_summary"]) == 1
    assert len(t["recon_checks"]) == 3 * len(CHECKS)
    assert len(t["recon_faults"]) == len(FAULTS) * 3
    assert len(t["recon_uat"]) == 3 * (len(CHECKS) + 3)
    assert len(t["recon_samples"]) == 9


def test_check_grid_matches_the_results(t, s):
    c = t["recon_checks"].set_index(["report", "check_name"])
    for r in s["reports"]:
        for k, chk in r["checks"].items():
            assert c.loc[(r["report"], k), "ok"] == chk["ok"]
            assert c.loc[(r["report"], k), "status"] == ("pass" if chk["ok"] else "fail")
    assert (t["recon_checks"]["status"] == "pass").all()


def test_fault_matrix_matches_the_results_and_every_fault_is_caught(t, s):
    f = t["recon_faults"]
    for _, row in f.iterrows():
        failed = s["planted_faults"][row["fault"]][row["report"]]
        assert row["failed_checks"] == (", ".join(failed) or "all pass")
        assert [k for k in CHECKS if row[f"fails_{k}"]] == failed
    assert f.groupby("fault")["caught"].any().all()
    assert f["fault"].drop_duplicates().tolist() == list(FAULTS)


def test_page_claims_about_the_faults_hold(t):
    """The page says the fan-out keeps row counts right, and the undocumented column trips one report only."""
    f = t["recon_faults"].set_index(["fault", "report"])
    fan = f.loc["rate_join_fan_out"]
    assert not fan["fails_row_count"].any() and fan["fails_totals"].all()
    assert f.loc["undocumented_column"]["caught"].tolist() == [False, True, False]


def test_every_fault_has_a_description():
    assert set(dashboard.FAULT_TEXT) == set(FAULTS)


def test_summary_counts_add_up(t, s):
    row = t["recon_summary"].iloc[0]
    assert row["checks_passing"] == t["recon_checks"]["ok"].sum() == 12
    assert row["faults_caught"] == row["faults"] == 5
    u = t["recon_uat"]
    assert row["owner_items_open"] == ((u["kind"] == "owner") & ~u["done"]).sum() == 9
    assert row["approved_hours"] == 22538.25 and row["approved_cost"] == 2234622.68
    assert row["approved_entries"] == s["timesheet_status"]["approved"]


def test_uat_items_follow_the_checklist(t, s):
    u = t["recon_uat"]
    owner = u[u["kind"] == "owner"]
    expected = [(rep, item, who is not None) for rep, items in uat.SIGN_OFF.items() for item, who in items.items()]
    assert list(zip(owner["report"], owner["item"], owner["done"], strict=True)) == expected
    auto = u[u["kind"] == "automated"]
    assert auto["item"].tolist() == [uat.CHECK_TEXT[k](c) for r in s["reports"] for k, c in r["checks"].items()]


def test_samples_match_the_results(t, s):
    sm = t["recon_samples"]
    for rep, rows in s["samples"].items():
        got = sm[sm["report"] == rep]
        assert got["value"].tolist() == [list(r.values())[-1] for r in rows]


def test_page_reads_only_tables_the_export_writes(t):
    used = set(re.findall(r"ridgeline\.(\w+)", PAGE.read_text()))
    assert used == set(t)
    sources = PAGE.parents[1] / "sources" / "ridgeline"
    for name in used:
        assert (sources / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"
    assert "report_reconciliation.dashboard" in EXPORT.read_text()


def test_page_columns_exist(t):
    """Every column the page names is in a table or a query alias (Evidence would render a blank)."""
    text = PAGE.read_text()
    known = set().union(*(df.columns for df in t.values())) | set(re.findall(r"\bas (\w+)", text))
    named = set(re.findall(r"(?:column|value|id)=(\w+)", text))
    assert named <= known, named - known


def test_nightly_smoke_test_checks_the_page():
    assert "report-reconciliation/" in NIGHTLY.read_text()


def test_missing_results_export_nothing(tmp_path):
    assert tables(tmp_path / "missing.json") == {}
