"""Clean simulator batches pass the event contract; each injected bad batch fails on exactly the rule meant to
catch it, and the CLI exits non-zero on it."""
import subprocess
import sys

import pandas as pd
import pytest

from data_health.batches import FAULTS, day_batch, inject
from data_health.contracts import EVENT_TYPES, RULES, check_batch, summary
from pipelines.engine import world_as_of

DAY = "2026-06-30"


@pytest.fixture(scope="module")
def world():
    return world_as_of(DAY)


@pytest.fixture(scope="module")
def clean(world):
    batch, loaded = day_batch(world, DAY)
    return batch, world["accounts"], loaded


def test_whole_history_meets_the_contract(world):
    ev = world["events"]
    assert len(ev) > 600_000
    assert check_batch(ev, world["accounts"], None).empty


@pytest.mark.parametrize("day", ["2024-03-01", "2025-07-15", "2026-01-01", DAY])
def test_clean_daily_batches_pass(world, day):
    batch, loaded = day_batch(world, day)
    assert len(batch) > 0
    assert check_batch(batch, world["accounts"], day, loaded).empty


def test_contract_lists_every_type_in_the_data(world):
    assert set(world["events"].event_type) == set(EVENT_TYPES)


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_injected_fault_fails_on_its_rule_only(clean, fault):
    batch, accounts, loaded = clean
    broken, loaded2 = inject(fault, batch, accounts, loaded)
    violations = check_batch(broken, accounts, DAY, loaded2)
    assert not violations.empty
    assert set(violations.rule) == {FAULTS[fault][1]}


def test_every_rule_has_a_fault_that_trips_it():
    assert {rule for _, rule in FAULTS.values()} == set(RULES) - {"account_id.format"}


def test_bad_account_format_is_caught(clean):
    batch, accounts, loaded = clean
    b = batch.copy()
    b.loc[0, "account_id"] = "acc-1"
    v = check_batch(b, accounts, DAY, loaded)
    assert set(v.rule) == {"account_id.format", "account_id.known"}


def test_injection_does_not_touch_the_clean_batch(clean):
    batch, accounts, loaded = clean
    before = batch.copy()
    for fault in FAULTS:
        inject(fault, batch, accounts, loaded)
    pd.testing.assert_frame_equal(batch, before)


def test_failures_name_the_event(clean):
    batch, accounts, loaded = clean
    broken, _ = inject("value_on_login", batch, accounts, loaded)
    v = check_batch(broken, accounts, DAY, loaded)
    assert v.event_id.iloc[0] == broken.loc[broken.event_type == "login", "event_id"].iloc[0]
    assert v.detail.iloc[0] == "login"


def test_many_faults_at_once_are_all_reported(clean):
    batch, accounts, loaded = clean
    b = batch.copy()
    for fault in ["unknown_event_type", "value_in_cents", "edited_after_the_fact", "duplicate_event_id"]:
        b, loaded = inject(fault, b, accounts, loaded)
    s = summary(check_batch(b, accounts, DAY, loaded)).set_index("rule").failed
    assert s[["event_type.allowed", "value_usd.range", "updated_at.equals_occurred_at", "event_id.unique"]].ge(1).all()
    assert s.sum() == s[s > 0].sum() and (s > 0).sum() == 4


def test_summary_has_one_row_per_rule(clean):
    batch, accounts, loaded = clean
    s = summary(check_batch(batch, accounts, DAY, loaded))
    assert list(s.rule) == list(RULES) and (s.failed == 0).all()


def test_cli_exits_zero_on_clean_and_one_on_bad_batch():
    ok = subprocess.run([sys.executable, "-m", "data_health"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "16 rules, 0 failed" in ok.stdout
    bad = subprocess.run([sys.executable, "-m", "data_health", "--inject", "orphan_account"],
                         capture_output=True, text=True)
    assert bad.returncode == 1
    assert "1 failed (injected: orphan_account)" in bad.stdout
