"""Checks pass on a correct build, catch each planted fault, and catch edits made to a mart by hand."""
import json
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest

from report_reconciliation import simulate, uat
from report_reconciliation.checks import check_report, source_frames
from report_reconciliation.reports import REPORTS
from report_reconciliation.run import build_and_check, failed, run

BY_NAME = {r.name: r for r in REPORTS}


@pytest.fixture()
def built():
    con, _ = build_and_check()
    return con


def check(con, name, rep=None):
    return check_report(con, rep or BY_NAME[name], source_frames(con), simulate.AS_OF)


def test_correct_build_passes_every_check():
    _, results = build_and_check()
    assert failed(results) == {"project_hours": [], "utilisation": [], "budget_burn": []}
    hours = {r["report"]: r["checks"]["totals"]["measures"]["hours"]["mart"]
             for r in results if "hours" in r["checks"]["totals"]["measures"]}
    assert hours["project_hours"] == hours["utilisation"] > 0


@pytest.mark.parametrize("fault, expected", [
    ("rate_join_fan_out", ["totals"]),
    ("rejected_included", ["totals"]),
    ("closed_projects_dropped", ["row_count", "totals"]),
    ("stale_extract", ["refresh_age"]),
])
def test_each_planted_fault_fails_the_expected_check_on_every_report(fault, expected):
    _, results = build_and_check(fault)
    assert all(v == expected for v in failed(results).values())


def test_undocumented_column_fails_lineage_only_where_it_was_added():
    _, results = build_and_check("undocumented_column")
    assert failed(results) == {"project_hours": [], "utilisation": ["lineage"], "budget_burn": []}
    util = next(r for r in results if r["report"] == "utilisation")
    assert util["checks"]["lineage"]["undocumented"] == ["margin_pct"]


def test_fan_out_inflates_cost_but_not_row_counts():
    _, results = build_and_check("rate_join_fan_out")
    ph = next(r for r in results if r["report"] == "project_hours")["checks"]
    assert ph["row_count"]["ok"]
    cost = ph["totals"]["measures"]["cost"]
    assert cost["mart"] > cost["source"] and cost["keys_differing"] > 0


def test_one_cent_edit_in_one_mart_row_is_found(built):
    built.execute("update mart.project_hours_monthly set cost = cost + 0.02 "
                  "where project_id = 'P01' and month = date '2026-03-01'")
    t = check(built, "project_hours")["checks"]["totals"]
    assert not t["ok"] and t["measures"]["cost"]["keys_differing"] == 1


def test_deleted_mart_row_fails_row_count(built):
    built.execute("delete from mart.resource_utilisation_weekly where resource_id = 'R05' "
                  "and week_start = date '2026-02-02'")
    rc = check(built, "utilisation")["checks"]["row_count"]
    assert not rc["ok"] and rc["keys_only_in_source"] == 1 and rc["keys_only_in_mart"] == 0


def test_mart_built_before_a_newer_extract_fails_refresh_even_inside_the_sla(built):
    built.execute("update source.extract_log set extracted_at = extracted_at + interval 1 hour "
                  "where table_name = 'projects'")
    r = check(built, "budget_burn")["checks"]["refresh_age"]
    assert r["stale_inputs"] == [] and not r["ok"]


def test_lineage_entry_naming_a_missing_source_column_fails(built):
    rep = BY_NAME["budget_burn"]
    rep = replace(rep, lineage={**rep.lineage, "budget_cost": "projects.budget"})
    lin = check(built, "budget_burn", rep)["checks"]["lineage"]
    assert lin["unknown_source_columns"] == ["projects.budget"]


def test_entry_on_a_raise_date_is_priced_at_the_new_rate_in_sql_and_pandas(built):
    rid, valid_from, rate = built.execute(
        "select resource_id, valid_from, hourly_cost from source.rate_history "
        "where valid_from > (select min(valid_from) from source.rate_history r2 "
        "where r2.resource_id = rate_history.resource_id) order by 1 limit 1").fetchone()
    on_day = built.execute("select hourly_cost from staging.timesheet_costed where resource_id = ? "
                           "and work_date = ?", [rid, valid_from]).fetchall()
    day_before = built.execute("select hourly_cost from staging.timesheet_costed where resource_id = ? "
                               "and work_date < ? order by work_date desc limit 1", [rid, valid_from]).fetchone()
    assert on_day and all(r[0] == rate for r in on_day) and day_before[0] < rate


def test_simulated_sources_are_seeded_and_messy_in_known_ways():
    a, b = simulate.frames(), simulate.frames()
    assert a["timesheets"].equals(b["timesheets"])
    assert set(a["timesheets"]["status"]) == {"approved", "rejected", "submitted"}
    assert (a["projects"]["status"] == "closed").sum() == 3
    rh = a["rate_history"].merge(a["resources"][["resource_id", "start_date"]], on="resource_id")
    assert (rh["valid_from"] >= rh["start_date"]).all()
    assert (simulate.AS_OF - simulate.EXTRACTED_AT) < timedelta(hours=24)


def test_uat_checklist_keeps_owner_items_open_until_signed():
    summary = run()
    md = uat.to_markdown(summary)
    assert md.count("- [x] ") == 4 * len(REPORTS)
    assert md.count("(needs the report owner)") == 3 * len(REPORTS)
    uat.SIGN_OFF["budget_burn"]["Signed off (name, date)"] = "A. Owner, 2026-06-30"
    try:
        assert "- [x] Signed off (name, date) (A. Owner, 2026-06-30)" in uat.to_markdown(summary)
    finally:
        uat.SIGN_OFF["budget_burn"]["Signed off (name, date)"] = None


def test_committed_results_are_current():
    out = subprocess.run([sys.executable, "-m", "report_reconciliation", "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_committed_summary_numbers():
    from pathlib import Path
    s = json.loads((Path("report_reconciliation/results/summary.json")).read_text())
    assert s["source_rows"] == {"projects": 18, "resources": 30, "rate_history": 41, "timesheets": 4800}
    assert s["timesheet_status"] == {"approved": 4598, "rejected": 84, "submitted": 118}
