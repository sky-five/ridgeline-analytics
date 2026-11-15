"""The enrolment planning dashboard: the new results files are what the marts give, the reporting tables add up
(regions to Canada, program groups to all programs, months to IRCC's years), the what-if's intake window and
ratios are the published ones, the page's what-if queries give intake times ratio, and the page reads only tables
and columns the export writes."""
import json
import re

import duckdb
import pandas as pd
import pytest

from enrolment_planning.report import intake_window, tables
from enrolment_planning.run import PERMITS_MONTHLY, SHARE, SUMMARY, permits_monthly_csv, share_csv

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "enrolment-planning.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
NAMES = {"enrol_summary", "enrol_share", "enrol_backtest", "enrol_backtest_horizon", "enrol_permits_monthly",
         "enrol_bridge", "enrol_ratios"}


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page():
    return PAGE.read_text(encoding="utf-8")


def test_new_results_files_are_what_the_marts_give(db):
    assert SHARE.read_text() == share_csv(db)
    assert PERMITS_MONTHLY.read_text() == permits_monthly_csv(db)


def test_export_writes_seven_tables(t):
    assert set(t) == NAMES
    assert len(t["enrol_summary"]) == 1
    assert len(t["enrol_backtest"]) == 5 * 4 * 3  # series x period x rule
    assert len(t["enrol_ratios"]) == 4
    assert "enrolment_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_shares_add_up_across_regions_and_program_groups(t, s):
    sh = t["enrol_share"].fillna({"international": 0})  # a few territory cells are not published at all
    regions = sh[sh["region_code"] != "CA"].groupby(["fall_year", "program_group"])[["international", "total"]].sum()
    canada = sh[sh["region_code"] == "CA"].set_index(["fall_year", "program_group"])[["international", "total"]]
    pd.testing.assert_frame_equal(regions.sort_index(), canada.sort_index(), check_dtype=False)
    groups = sh[sh["program_group"] != "ALL"].groupby(["fall_year", "region_code"])[["international", "total"]].sum()
    every = sh[sh["program_group"] == "ALL"].set_index(["fall_year", "region_code"])[["international", "total"]]
    pd.testing.assert_frame_equal(groups.sort_index(), every.sort_index(), check_dtype=False)
    assert sh["international_share"].dropna().between(0, 1).all()
    assert (sh["fall"] == sh["fall_year"].astype(str)).all()
    # the leaves carry StatCan's random rounding: within 0.1% of the published fall 2024 count, not equal to it
    ca = sh.query("fall_year == 2024 and region_code == 'CA' and program_group == 'ALL'").iloc[0]
    e = s["enrolments"]
    assert ca["international"] == 533_349 != e["international"] == 533_382
    assert abs(ca["international"] - e["international"]) / e["international"] < 0.001
    on = sh.query("fall_year == 2024 and region_code == 'ON' and program_group == 'ALL'").iloc[0]
    assert (on["international"], round(on["international_share"], 3)) == (286_539, 0.285)
    stem = sh.query("fall_year == 2024 and region_code == 'CA' and program_group == 'STEM'").iloc[0]
    assert stem["international"] == e["international_by_program_group_last_fall"]["STEM"]


def test_monthly_permits_add_up_to_the_yearly_counts(t, s):
    p = t["enrol_permits_monthly"]
    ca = p[p["series"] == "CA"]
    by_year = ca.groupby(pd.to_datetime(ca["month"]).dt.year)["permits"].sum()
    assert {str(y): int(n) for y, n in by_year.items()} == s["new_post_secondary_permits_by_year"]
    assert set(p["series"]) == {"CA", "ON", "BC", "QC", "AB"} and len(p) == 5 * 140


def test_intake_windows_are_october_to_september(t, s):
    monthly = pd.read_csv(PERMITS_MONTHLY, dtype={"month": str})
    for b in s["intake_to_enrolment"]:
        assert intake_window(monthly, b["fall_year"]) == b["new_permits_oct_to_sep"]
    assert intake_window(monthly, 2025) == 263_845
    assert intake_window(monthly, 2026) is None  # September 2026 is not published yet
    row = t["enrol_summary"].iloc[0]
    assert (row["next_fall"], row["next_fall_intake"], row["last_bridge_intake"]) == (2025, 263_845, 430_105)


def test_ratio_choices_are_the_published_ones(t, s):
    r = t["enrol_ratios"].set_index("ratio_key")
    ratios = [b["enrolments_per_new_permit"] for b in s["intake_to_enrolment"]]
    assert r.loc["last", "ratio"] == ratios[-1] == 1.24
    assert r.loc["low", "ratio"] == min(ratios) == 1.094
    assert r.loc["high", "ratio"] == max(ratios) == 1.677
    assert r.loc["mean", "ratio"] == round(sum(ratios) / len(ratios), 3)
    assert r.loc["high", "choice"] == "Highest (fall 2020): 1.68"


def test_one_best_rule_per_series_and_period(t):
    bt = t["enrol_backtest"]
    assert (bt.groupby(["series", "period"])["is_best"].sum() == 1).all()
    best = bt[bt["is_best"] & (bt["series"] == "CA")].set_index("period")
    assert best.loc["2024-2026 after the cap", "rule"] == "same_month_last_year"
    assert best.loc["2024-2026 after the cap", "wape"] == 0.352
    after = bt[(bt["series"] == "CA") & (bt["period"] == "2024-2026 after the cap")]
    assert (after["bias"] > 0).all()  # every rule too high after the cap, as the page says


def _block(page: str, name: str) -> str:
    return re.search(rf"```sql {name}\n(.*?)```", page, flags=re.S).group(1)


def test_what_if_is_intake_times_ratio(t, page):
    """Run the page's own what-if queries in DuckDB with the slider and dropdown filled in."""
    default = int(re.search(r"<Slider name=intake[^>]*defaultValue=(\d+)", page).group(1))
    lo, hi = (int(re.search(rf"<Slider name=intake[^>]*{k}=(\d+)", page).group(1)) for k in ("min", "max"))
    assert lo <= default <= hi and lo <= 263_845 <= hi
    assert 'defaultValue="last"' in page
    intl = t["enrol_summary"].iloc[0]["international"]
    with duckdb.connect() as con:
        con.execute("create schema ridgeline")
        for name in ("enrol_ratios", "enrol_summary"):
            con.register("_df", t[name])
            con.execute(f"create table ridgeline.{name} as select * from _df")
            con.unregister("_df")
        for intake in (default, 400_000):
            for key, ratio in t["enrol_ratios"][["ratio_key", "ratio"]].itertuples(index=False):
                sql = _block(page, "estimate").replace("${inputs.intake}", str(intake))
                sql = sql.replace("${inputs.ratio.value}", key)
                (choice, fall, change), = con.sql(sql).fetchall()
                assert fall == round(intake * ratio) and change == pytest.approx(fall / intl - 1)
            rng = con.sql(_block(page, "whatif_range").replace("${inputs.intake}", str(intake))).df()
            assert rng["fall_international"].tolist() == [round(intake * r) for r in t["enrol_ratios"]["ratio"]]
    assert round(default * 1.24) == 328_600


def test_page_quotes_true_numbers(t, page):
    b = t["enrol_bridge"].set_index("fall_year")["enrolments_per_new_permit"]
    assert f"{b[2019]:.2f} in fall 2019" in page and f"{b[2020]:.2f} in fall 2020" in page
    assert f"{b[2023]:.2f} at the peak of fall 2023" in page
    assert b.idxmax() == 2020 and b.idxmin() == 2023
    assert t["enrol_summary"].iloc[0]["last_fall"] == 2024  # chart titles say fall 2024


def test_page_reads_only_exported_tables_and_columns(t, page):
    used = set(re.findall(r"ridgeline\.(\w+)", page))
    assert used == NAMES
    queries = dict(re.findall(r"```sql (\w+)\n(.*?)```", page, flags=re.S))
    summary_cols = set(t["enrol_summary"].columns)
    for comp in re.findall(r"<(?:BigValue|Value) data=\{summary\}[^>]*>", page):
        for col in re.findall(r"\b(?:value|column)=(\w+)", comp):
            assert col in summary_cols, col
    for block in queries.values():
        m = re.match(r"select (?:distinct )?(?!\*)(.*?)\s+from ridgeline\.(\w+)", block, flags=re.S)
        if not m or "${" in m.group(1):
            continue
        cols, table = m.groups()
        cols = re.sub(r"'[^']*'", "", re.sub(r"\(.*?\)", "", cols))
        cols = re.sub(r"case .*? end", "", cols, flags=re.S)
        for col in re.findall(r"\b([a-z_]+)\b", cols):
            if col not in ("as", "sort", "best"):
                assert col in t[table].columns, (table, col)


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* enrolment-planning/", NIGHTLY.read_text())
