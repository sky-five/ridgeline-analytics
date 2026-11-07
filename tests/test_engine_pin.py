"""The simulated business comes from saas-world-sim at a pinned tag. These checks fail if the pin drifts
or if the engine's seeded history changes under it, since every number in this repo depends on it."""
import re
from datetime import date
from pathlib import Path

import pytest

from pipelines import engine

ROOT = Path(__file__).resolve().parent.parent

# Row counts as of 2026-06-30, the same snapshot saas-world-sim locks in tests/test_fingerprint.py.
# They match what the in-repo simulator produced before the engine moved out.
ROWS_2026_06_30 = {
    "accounts": 7185, "ad_spend": 3648, "contractor_leads": 159311, "crm_calls": 2450, "crm_deals": 177,
    "events": 623164, "invoices": 10992, "measurement_orders": 137361, "subscription_changes": 2789,
    "subscriptions": 1248, "support_tickets": 10194,
}


def test_requirements_pin_matches_engine_tag():
    req = (ROOT / "requirements.txt").read_text()
    pins = re.findall(r"saas-world-sim @ git\+https://github\.com/sky-five/saas-world-sim@(\S+)", req)
    assert pins == [engine.ENGINE_TAG]


def test_installed_version_matches_tag():
    assert f"v{engine.__version__}" == engine.ENGINE_TAG


def test_history_cache_is_at_repo_root():
    import saas_world_sim.world

    assert saas_world_sim.world.CACHE_DIR == ROOT / ".cache"


def test_tables_this_repo_loads():
    assert set(engine.TABLES) == set(ROWS_2026_06_30)


@pytest.fixture(scope="module")
def world():
    return engine.world_as_of(date(2026, 6, 30))


def test_row_counts_unchanged(world):
    assert {n: len(df) for n, df in world.items()} == ROWS_2026_06_30


def test_money_totals_unchanged(world):
    assert world["invoices"].amount_usd.sum() == pytest.approx(3_404_516.0)
    assert world["subscriptions"].mrr_usd.sum() == pytest.approx(214_743.0)
