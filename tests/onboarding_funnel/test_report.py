"""The onboarding funnel dashboard tables: they come from the committed results, the funnel steps are in order and
never grow, both ways of counting agree before the break and split after it, and the page reads only tables (and
columns) the export writes."""
import json
import re

import pandas as pd
import pytest

from onboarding_funnel.report import STEPS, tables
from onboarding_funnel.run import SUMMARY, WEEKLY

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "onboarding-funnel.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_export_writes_eight_tables(t):
    assert set(t) == {"onb_summary", "onb_funnel", "onb_drop_offs", "onb_time_to_first_txn", "onb_weekly",
                      "onb_activation_weekly", "onb_checks", "onb_steps"}
    assert len(t["onb_summary"]) == 1
    assert len(t["onb_funnel"]) == 4 * len(STEPS)
    assert len(t["onb_weekly"]) == 100
    assert len(t["onb_checks"]) == 3 and len(t["onb_steps"]) == 12
    assert "onboarding_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_funnel_steps_never_grow_and_match_the_results(t, s):
    f = t["onb_funnel"]
    for program, g in f.groupby("program"):
        g = g.sort_values("step_sort")
        assert g["people"].is_monotonic_decreasing, program
        assert g["share_of_started"].iloc[0] == 1.0
        assert g["share_of_previous_step"].between(0, 1).all()
    by = {r["program"]: r for r in s["funnel"]}
    last = f[f["step_sort"] == len(STEPS) - 1].set_index("program")
    for program, r in by.items():
        assert last.loc[program, "people"] == r["activated"]
        assert last.loc[program, "share_of_started"] == pytest.approx(r["activation_rate"], abs=1e-4)
    summ = t["onb_summary"].iloc[0]
    assert summ["mature_started"] == 20_128 == sum(r["started"] for r in s["funnel"])
    assert round(summ["mature_activation_rate"], 3) == 0.482


def test_drop_offs_add_up_to_everyone_who_did_not_activate(t, s):
    d = t["onb_drop_offs"]
    assert d["step_label"].notna().all() and d["reason_label"].notna().all()
    for r in s["funnel"]:
        got = d[d["program"] == r["program"]]
        assert got["applicants"].sum() == r["started"] - r["activated"], r["program"]
        assert got["share_of_drop_offs"].sum() == pytest.approx(1, abs=1e-3)


def test_both_counts_agree_until_the_break_then_split(t):
    a = t["onb_activation_weekly"]
    summ = t["onb_summary"].iloc[0]
    assert set(a["counted"]) == {"Per application id", "Per person"}
    w = a.pivot_table(index=["program", "cohort_week"], columns="counted", values="activation").reset_index()
    gap = w["Per person"] - w["Per application id"]
    week = pd.to_datetime(w["cohort_week"])
    brk = pd.Timestamp(summ["break_week"])
    cross = w["program"] == "cross_border"
    after = cross & (week >= brk)
    # the week before the break: a few people who started then resumed after the bug and got a second id
    edge = cross & (week == brk - pd.Timedelta(days=7))
    assert (gap[~after & ~edge].abs() < 1e-9).all()  # one id per person: the two counts are the same
    assert 0 < gap[edge].item() < 0.01
    assert (gap[after] > 0).all()  # second ids only ever add people who did not activate
    assert after.sum() == 8  # mature weeks after the break
    assert pd.to_datetime(a["cohort_week"]).max() == pd.Timestamp(summ["last_mature_week"])


def test_ids_per_person_flag_matches_the_check(t, s):
    w = t["onb_weekly"]
    over = w[w["over_limit"]]
    assert set(over["program"]) == {"cross_border"}
    assert len(over) == s["checks"]["ids_per_person"]["programs"]["cross_border"]["weeks_over_limit"] == 12
    assert over["cohort_week"].min() == t["onb_summary"].iloc[0]["break_week"]
    assert w.loc[w["program"] != "cross_border", "application_ids_per_applicant"].eq(1.0).all()


def test_the_page_numbers(t):
    summ = t["onb_summary"].iloc[0]
    assert (summ["per_id_change_pp"], summ["per_person_change_pp"], summ["share_from_counting"]) == (-4.8, -1.0, 0.8)
    assert (summ["per_person_ci_low"], summ["per_person_ci_high"]) == (-4.0, 2.0)
    assert (summ["real_program_label"], str(summ["real_week"]), summ["real_t"]) == ("Consumer card", "2026-05-11", -5.4)
    assert summ["real_reason"] == "Selfie mismatch"
    assert summ["noise_t"] == 2.9 and summ["noise_t"] < 3
    checks = t["onb_checks"].set_index("sort")
    assert checks["passed"].tolist() == [True, True, False]
    assert "raw email would split 165" in checks.loc[1, "result"]
    assert "Cross-border over from 2026-04-06 for 12 weeks (max 1.176)" == checks.loc[2, "result"]
    readings = t["onb_steps"].set_index(["program", "rate"])["reading"]
    assert readings[("cross_border", "activation_rate_per_id")] == "counting artefact"
    assert readings[("consumer_card", "kyc_pass_rate")] == "real"
    assert (readings == "no shift").sum() == 10


def test_page_reads_only_exported_tables_and_columns(t):
    page = PAGE.read_text(encoding="utf-8")
    assert set(re.findall(r"ridgeline\.(\w+)", page)) == set(t)
    queries = dict(re.findall(r"```sql (\w+)\nselect \* from ridgeline\.(\w+)", page))
    assert queries["summary"] == "onb_summary"
    for name, table in queries.items():
        cols = set(t[table].columns)
        for comp in re.findall(rf"<\w+ data={{{name}}}[^>]*>", page):
            for attr in ("value", "column", "x", "y"):
                for col in re.findall(rf"\b{attr}=(\w+)", comp):
                    assert col in cols, (name, attr, col)
    # columns picked by name in the other queries exist in the table they select from
    for block in re.findall(r"```sql \w+\n(.*?)```", page, flags=re.S):
        m = re.match(r"select (?!\*)(.*?)\s+from ridgeline\.(\w+)", block, flags=re.S)
        if not m:
            continue
        cols, table = m.groups()
        for col in re.findall(r"\b([a-z_]+)\b", re.sub(r"\(.*?\)", "", cols)):
            if col not in ("as", "value", "label", "distinct"):
                assert col in t[table].columns, (table, col)


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* onboarding-funnel/", NIGHTLY.read_text())


def test_committed_results_exist():
    assert SUMMARY.exists() and WEEKLY.exists()
