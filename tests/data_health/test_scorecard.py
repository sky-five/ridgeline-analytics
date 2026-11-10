"""The table health scorecard: clean days stay out of red, each injected table fault turns its check red,
and the grading rules behave on small hand-made tables."""
import subprocess
import sys

import pandas as pd
import pytest

from data_health.batches import TABLE_FAULTS, arrivals, inject_table
from data_health.scorecard import CHECKS, WINDOW_DAYS, score_table, scorecard
from pipelines.engine import TABLES

DAY = "2026-06-30"
CLEAN_DAYS = [str(d.date()) for d in pd.date_range(end=DAY, periods=14)]
KEYS = {name: spec.primary_key for name, spec in TABLES.items()}
BUSY = ["events", "measurement_orders", "contractor_leads"]  # hundreds of rows a day: every fault shows


@pytest.fixture(scope="module")
def stack():
    return arrivals(DAY, WINDOW_DAYS + len(CLEAN_DAYS) - 1)


@pytest.fixture(scope="module")
def clean(stack):
    return scorecard(stack, DAY, KEYS)


def test_scorecard_has_every_table_once(clean):
    assert sorted(clean.table_name) == sorted(TABLES)
    assert set(clean.grade) <= {"green", "amber", "red"}
    assert clean.reason.str.len().gt(0).all()


def test_two_weeks_of_clean_days_have_no_red(stack):
    cards = pd.concat([scorecard(stack, d, KEYS) for d in CLEAN_DAYS])
    assert len(cards) == 14 * len(TABLES)
    assert (cards.grade == "red").sum() == 0
    assert (cards.grade == "amber").sum() <= 8  # 6 of 154 on the pinned engine: ambers are meant to be seen


def test_batches_count_every_version_of_a_changed_row(stack):
    # support tickets change after they open (first reply, solved): the stack holds more rows than tickets
    tickets = stack["support_tickets"]
    assert len(tickets) > tickets.ticket_id.nunique()
    assert stack["events"].event_id.is_unique  # events never change


FAULT_CASES = [(f, t) for f in TABLE_FAULTS for t in BUSY]
FAULT_CASES += [("stuck_loader", t) for t in TABLES if t not in BUSY and t not in ("crm_deals", "crm_calls")]
FAULT_CASES += [("account_id_dropped", t) for t in ["invoices", "support_tickets", "subscriptions", "crm_calls"]]


@pytest.mark.parametrize("fault,table", FAULT_CASES)
def test_injected_fault_turns_its_check_red(stack, clean, fault, table):
    _, check = TABLE_FAULTS[fault]
    card = scorecard(inject_table(fault, stack, table, DAY), DAY, KEYS).set_index("table_name")
    assert card.loc[table, f"{check}_grade"] == "red"
    assert card.loc[table, "grade"] == "red"
    others = clean.set_index("table_name").drop(index=table)
    assert card.drop(index=table).loc[others.index, "grade"].equals(others.grade)


def test_every_fault_and_check_is_exercised():
    assert {check for _, check in TABLE_FAULTS.values()} == set(CHECKS)
    assert {f for f, _ in FAULT_CASES} == set(TABLE_FAULTS)


def test_null_fault_needs_an_account_id(stack):
    with pytest.raises(ValueError):
        inject_table("account_id_dropped", stack, "ad_spend", DAY)


def test_cli_exits_1_on_a_red_table():
    args = [sys.executable, "-m", "data_health.scorecard", "--day", DAY]
    broken = subprocess.run([*args, "--inject", "double_load", "--table", "events"], capture_output=True, text=True)
    assert broken.returncode == 1, broken.stdout + broken.stderr
    assert "1 red" in broken.stdout and "events" in broken.stdout


# hand-made tables: one row every hour for 29 days, so the rules can be checked by arithmetic


def _hourly(days=29, per_hour=1, end=DAY, **cols):
    stamps = pd.date_range(end=pd.Timestamp(end) + pd.Timedelta(hours=23), periods=days * 24, freq="h")
    stamps = stamps.repeat(per_hour)
    return pd.DataFrame({"row_id": range(len(stamps)), "updated_at": stamps, "note": "x", **cols})


def test_steady_table_is_green_with_a_reason():
    s = score_table(_hourly(), DAY, "row_id")
    assert s["grade"] == "green"
    assert s["rows_today"] == 24 and s["usual_rows"] == 24
    assert s["reason"].startswith("24 rows, usual 24 a day")


def test_freshness_is_amber_past_the_longest_gap_and_red_past_three_times():
    df = _hourly()
    day_end = pd.Timestamp(DAY) + pd.Timedelta(days=1)
    for hours_quiet, grade in [(23, "green"), (30, "amber"), (71, "amber"), (73, "red")]:
        cut = df[df.updated_at <= day_end - pd.Timedelta(hours=hours_quiet)]
        assert score_table(cut, DAY)["freshness_grade"] == grade, hours_quiet


def test_volume_spread_never_falls_below_the_square_root_of_the_mean():
    # a perfectly steady 24 rows a day has no spread; sqrt(24) = 4.9 keeps 12 rows (z = 2.4) green
    df = _hourly()
    today = df.updated_at.dt.floor("D") == pd.Timestamp(DAY)
    twelve = df.drop(index=df.index[today][::2])
    assert score_table(twelve, DAY)["volume_grade"] == "green"
    assert score_table(df[~today | (df.updated_at.dt.hour < 4)], DAY)["volume_grade"] == "amber"  # 4 rows, z = 4.1
    assert score_table(df[~today], DAY)["volume_grade"] == "amber"  # 0 rows, z = 4.9
    busy = _hourly(per_hour=10)
    busy_today = busy.updated_at.dt.floor("D") == pd.Timestamp(DAY)
    assert score_table(busy.drop(index=busy.index[busy_today][24:]), DAY)["volume_grade"] == "red"  # 24 of 240


def test_null_rate_flags_only_more_empties_than_usual():
    df = _hourly(note=None)  # note is always empty, so an empty note today is normal
    assert score_table(df, DAY, "row_id")["null_rate_grade"] == "green"
    df = _hourly()
    today = df.index[df.updated_at.dt.floor("D") == pd.Timestamp(DAY)]
    df.loc[today[:1], "note"] = None  # 1 of 24 (4.2%) where none is usual: 4.2 spreads of the 1-point floor
    s = score_table(df, DAY, "row_id")
    assert s["null_rate_grade"] == "amber" and s["worst_null_column"] == "note"
    df.loc[today[:6], "note"] = None  # a quarter empty, never before
    s = score_table(df, DAY, "row_id")
    assert s["null_rate_grade"] == "red" and s["reason"] == "note 25% empty, usually 0%"


def test_key_and_updated_at_are_not_null_checked():
    df = _hourly()
    df.loc[df.index[-3:], "row_id"] = None
    assert score_table(df, DAY, "row_id")["null_rate_grade"] == "green"


def test_a_table_with_no_rows_today_skips_nulls_and_one_with_no_rows_at_all_is_red():
    df = _hourly()
    s = score_table(df[df.updated_at < pd.Timestamp(DAY)], DAY)
    assert s["null_rate_grade"] == "green" and s["null_share_today"] is None
    assert score_table(df.iloc[:0], DAY)["grade"] == "red"


def test_table_grade_is_the_worst_check_and_red_tables_sort_first(stack):
    broken = inject_table("stuck_loader", stack, "invoices", DAY)
    card = scorecard(broken, DAY, KEYS)
    assert card.iloc[0].table_name == "invoices"
    row = card.iloc[0]
    assert row.grade == "red" and row.freshness_grade == "red"
    assert row.reason.startswith("last row 4.1 days before the day ended")
