from datetime import date

import duckdb
import pytest

from pipelines.run import load
from simulator.world import world_as_of

D, D_NEXT = date(2024, 3, 31), date(2024, 4, 29)


def _count(db, table, system="app_db"):
    with duckdb.connect(str(db), read_only=True) as c:
        return c.sql(f"select count(*) from raw_{system}.{table}").fetchone()[0]


@pytest.fixture
def target(tmp_path):
    return {"duckdb_path": str(tmp_path / "wh.duckdb"), "pipelines_dir": str(tmp_path / "dlt")}


def test_first_load_counts_match_world(target):
    load(D, **target)
    w = world_as_of(D)
    assert _count(target["duckdb_path"], "accounts") == len(w["accounts"])
    assert _count(target["duckdb_path"], "events", "product_events") == len(w["events"])


def test_incremental_load_idempotent(target):
    load(D, **target)
    before = _count(target["duckdb_path"], "events", "product_events")
    load(D, **target)
    assert _count(target["duckdb_path"], "events", "product_events") == before


def test_empty_increment(target):
    load(D, **target)
    counts = load(D, **target)
    assert all(n == 0 for n in counts.values())


def test_next_day_updates_merge(target):
    load(D, **target)
    load(D_NEXT, **target)
    w = world_as_of(D_NEXT)
    db = target["duckdb_path"]
    assert _count(db, "subscriptions") == len(w["subscriptions"])
    assert _count(db, "support_tickets", "support") == len(w["support_tickets"])
    with duckdb.connect(db, read_only=True) as c:
        loaded = dict(c.sql("select subscription_id, status from raw_app_db.subscriptions").fetchall())
    expected = dict(zip(w["subscriptions"].subscription_id, w["subscriptions"].status, strict=True))
    assert loaded == expected


def test_reload_after_lost_state_does_not_duplicate(tmp_path):
    # If dlt's incremental state is lost (renamed pipeline, wiped state), a full reload must not
    # duplicate rows in log tables.
    db = str(tmp_path / "wh.duckdb")
    load(D, duckdb_path=db, pipelines_dir=str(tmp_path / "a"))
    before = _count(db, "events", "product_events")
    with duckdb.connect(db) as c:
        for schema in ("raw_product_events", "raw_app_db", "raw_crm", "raw_support", "raw_ads", "raw_contractor_ops"):
            c.sql(f"delete from {schema}._dlt_pipeline_state")
    load(D, duckdb_path=db, pipelines_dir=str(tmp_path / "b"))
    assert _count(db, "events", "product_events") == before
