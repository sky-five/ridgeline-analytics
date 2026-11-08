"""Builds the CRM warehouse once (load + dbt build, a few seconds) and checks the fixes, the marts and
the committed results against the pack's labels and planted patterns."""
import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from crm_pipeline.load import dbt_build, load
from crm_pipeline.score import RESULTS, score

AS_OF = date(2026, 6, 30)
SOQL = Path(__file__).resolve().parents[2] / "crm_pipeline" / "soql"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("crm") / "crm.duckdb"
    load(AS_OF, path)
    dbt_build(AS_OF, path)
    return path


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def summary(db):
    return score(AS_OF, db)


def rows(con, sql):
    return con.execute(sql).fetchall()


def test_labels_stay_out_of_the_warehouse(con):
    sql = "select column_name from information_schema.columns where table_schema = 'raw_crm'"
    cols = {c for (c,) in rows(con, sql)}
    assert "duplicate_of_account_id" not in cols and "close_date_backdated" not in cols


def test_dedupe_finds_the_duplicates_without_false_matches(summary):
    assert summary.duplicates_labelled == 61
    assert summary.duplicates_found >= 60
    assert summary.duplicates_false_matches == 0
    assert summary.companies_after_dedupe == summary.account_records - summary.duplicates_found


def test_backdated_close_dates_all_caught(summary):
    assert summary.backdated_labelled_closed > 0
    assert summary.backdated_found == summary.backdated_labelled_closed
    assert summary.backdated_false_flags == 0


def test_corrected_dates_move_backdated_wins_into_the_next_quarter(con):
    bad = rows(con, """
        select count(*) from fct_opportunities
        where is_backdated
          and date_trunc('quarter', corrected_close_date) <= date_trunc('quarter', recorded_close_date)""")
    assert bad == [(0,)]


def test_won_total_matches_the_pack(con):
    # every deal survives the dedupe join, so totals match the pack's README ($6,007,400 won as of 2026-06-30)
    assert rows(con, "select count(*), sum(amount_usd) filter (where is_won) from fct_opportunities") == [
        (1006, 6_007_400.0)]
    assert rows(con, "select sum(won_usd) from dim_accounts") == [(6_007_400.0,)]


def test_win_rate_rises_stage_by_stage(con):
    rates = [r for (r,) in rows(con, "select win_rate_from_stage from stage_conversion order by stage_rank")]
    assert len(rates) == 5 and rates == sorted(rates)
    assert rates[-1] < 1  # some deals are lost even at negotiation


def test_planted_patterns_show_in_the_marts(con):
    win = dict(rows(con, """
        select lead_source, avg(is_won::int) from fct_opportunities
        where is_closed and opportunity_type = 'new_business' group by lead_source"""))
    assert win["partner_referral"] > win["web_form"] + 0.15
    days = dict(rows(con, "select segment, median_days_to_win from sales_velocity"))
    assert days["enterprise"] > 2 * days["smb"]
    pushed = dict(rows(con, """
        select close_date_pushes >= 2, avg(is_won::int) from fct_opportunities where is_closed group by 1"""))
    assert pushed[True] < pushed[False] - 0.2


def test_forecast_backtest_learned_rates_beat_crm_probabilities(con, summary):
    assert summary.forecast_quarters == 9
    assert summary.forecast_mape_learned_rates < summary.forecast_mape_crm_probability
    # stage probabilities alone miss the deals created during the quarter, so they always forecast low
    assert rows(con, "select count(*) from forecast_backtest where forecast_crm_probability_usd >= actual_won_usd") == [
        (0,)]


def test_coverage_is_open_pipeline_over_the_quarterly_baseline(con):
    ((pipe, base, ratio),) = rows(con, """
        select open_pipeline_usd, avg_won_per_quarter_usd, coverage_ratio from pipeline_coverage
        where close_quarter = date '2026-07-01'""")
    assert pipe == 1_923_200.0  # the pack's open pipeline as of 2026-06-30
    assert ratio == pytest.approx(pipe / base, abs=0.01)


@pytest.mark.parametrize("soql", sorted(SOQL.glob("*.soql")), ids=lambda p: p.stem)
def test_each_object_query_has_a_sql_version_that_runs(con, soql):
    sql = soql.with_suffix(".sql")
    assert sql.exists()
    assert len(con.execute(sql.read_text()).fetchall()) > 0


def test_committed_results_match_the_code(summary):
    assert json.loads(RESULTS.read_text()) == json.loads(summary.to_json())
