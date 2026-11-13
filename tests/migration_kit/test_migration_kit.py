"""Loaders, reconciliation and checklist on snapshots made from the committed real one, with planted changes."""
import gzip
import io
import json
from datetime import timedelta

import duckdb
import pandas as pd
import pytest

from migration_kit import checklist
from migration_kit.feed import STAMP, fetched_at, snapshots
from migration_kit.loaders import load_legacy, load_target, setup
from migration_kit.reconcile import reconcile, to_markdown
from migration_kit.replay import RESULTS, compact, replay

REAL = snapshots()[0]
T0 = fetched_at(REAL)


def raw() -> pd.DataFrame:
    return pd.read_csv(REAL, dtype=str, keep_default_na=False)


def write(folder, df: pd.DataFrame, when) -> object:
    path = folder / f"{when.strftime(STAMP)}.csv.gz"
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    return path


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """Three snapshots: day 0 lacks the 5 newest events; day 1 is the real feed; day 2 is a day later with
    3 magnitude revisions, 2 status changes, 1 deletion inside the window, 4 new events, and the events older
    than the new 30-day window gone."""
    folder = tmp_path_factory.mktemp("snaps")
    df = raw()
    t = pd.to_datetime(df["time"])
    newest = t.nlargest(5).index
    day0 = write(folder, df.drop(index=newest), T0 - timedelta(hours=6))
    day1 = write(folder, df, T0)

    d2 = df.copy()
    when2 = T0 + timedelta(days=1)
    old = t < pd.Timestamp(when2 - timedelta(days=30)).tz_localize(None).tz_localize("UTC")
    middle = d2.index[(~old) & (~d2.index.isin(newest))]
    revised, restatused, deleted = middle[:3], middle[10:12], middle[20:21]
    d2.loc[revised, "mag"] = (d2.loc[revised, "mag"].astype(float) + 0.1).round(2).astype(str)
    d2.loc[restatused, "status"] = d2.loc[restatused, "status"].map({"automatic": "reviewed", "reviewed": "automatic"})
    d2 = d2.drop(index=deleted.union(d2.index[old]))
    new = df.loc[newest[:4]].copy()
    new["id"] = [f"zz{i}" for i in range(4)]
    new["time"] = (T0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d2 = pd.concat([d2, new])
    day2 = write(folder, d2, when2)
    return {"paths": [day0, day1, day2], "revised": set(df.loc[revised, "id"]),
            "restatused": set(df.loc[restatused, "id"]), "deleted": set(df.loc[deleted, "id"]),
            "aged_out": set(df.loc[old, "id"]), "new": set(new["id"]), "newest": set(df.loc[newest, "id"])}


def run(paths, strategy="hash_merge"):
    con = duckdb.connect()
    setup(con)
    out = []
    for p in paths:
        row = load_target(con, p, strategy)
        load_legacy(con, p)
        out.append((row, reconcile(con)))
    return con, out


def test_the_hash_merge_finds_exactly_the_planted_changes(planted):
    _, out = run(planted["paths"])
    (l0, _), (l1, _), (l2, _) = out
    assert l1["inserted"] == 5 and l1["updated"] == 0 and l1["unchanged"] == l0["snapshot_rows"]
    assert l2["inserted"] == 4
    assert l2["updated"] == len(planted["revised"] | planted["restatused"]) == 5
    assert l2["deleted"] == 1
    assert l2["aged_out"] == len(planted["aged_out"]) > 0
    assert all(r["ok"] for _, r in out)


def test_each_change_names_the_columns_that_moved(planted):
    con, _ = run(planted["paths"])
    rows = dict(con.execute("select id, changed_columns from target.earthquake_changes "
                            "where change_type = 'update'").fetchall())
    assert {i for i, c in rows.items() if c == "mag"} == planted["revised"]
    assert {i for i, c in rows.items() if c == "status"} == planted["restatused"]


def test_target_keeps_events_that_left_the_feed_and_says_why(planted):
    con, _ = run(planted["paths"])
    gone = dict(con.execute("select id, left_feed_as from target.earthquakes where not in_feed").fetchall())
    assert {i for i, w in gone.items() if w == "deleted"} == planted["deleted"]
    assert {i for i, w in gone.items() if w == "aged_out"} == planted["aged_out"]
    legacy_ids = {r[0] for r in con.execute("select id from legacy.earthquakes").fetchall()}
    assert not legacy_ids & set(gone)


def test_reloading_the_same_snapshot_changes_nothing():
    con = duckdb.connect()
    setup(con)
    load_target(con, REAL)
    again = load_target(con, REAL)
    assert again["unchanged"] == again["snapshot_rows"]
    assert again["inserted"] == again["updated"] == again["deleted"] == again["aged_out"] == 0


def test_an_event_that_comes_back_is_logged_as_returned(planted, tmp_path):
    df = raw()
    gone = write(tmp_path, df.iloc[1:], T0 + timedelta(minutes=5))
    back = write(tmp_path, df, T0 + timedelta(minutes=10))
    con, out = run([REAL, gone, back])
    assert out[1][0]["deleted"] == 1 and out[2][0]["returned"] == 1
    assert all(r["ok"] for _, r in out)


def test_the_event_time_watermark_is_caught(planted):
    _, out = run(planted["paths"], "event_time_watermark")
    row, rec = out[2]
    assert not rec["ok"]
    assert set(rec["rows_differing"]) == planted["revised"] | planted["restatused"]
    assert rec["differing_by_column"] == {"mag": 3, "status": 2}
    assert set(rec["only_in_target"]) == planted["deleted"] | planted["aged_out"]
    assert not rec["checks"]["aggregates"]
    assert "MISMATCH" in to_markdown(rec, "x")


def test_reconciliation_does_not_trust_the_loaders_hash():
    con = duckdb.connect()
    setup(con)
    load_target(con, REAL)
    load_legacy(con, REAL)
    assert reconcile(con)["ok"]
    victim = con.execute("select id from target.earthquakes order by id limit 1").fetchone()[0]
    con.execute("update target.earthquakes set depth = depth + 1 where id = ?", [victim])  # row_hash left as is
    rec = reconcile(con)
    assert not rec["ok"] and rec["rows_differing"] == [victim] and rec["differing_by_column"] == {"depth": 1}
    con.execute("delete from target.earthquakes where id = ?", [victim])
    rec = reconcile(con)
    assert rec["only_in_legacy"] == [victim] and not rec["checks"]["row_count"]


def test_checklist_finds_a_reader_of_the_legacy_table(tmp_path):
    (tmp_path / "dbt").mkdir()
    (tmp_path / "dbt" / "report.sql").write_text("select * from legacy.earthquakes")
    (tmp_path / "dbt" / "fine.sql").write_text("select * from target.earthquakes")
    assert checklist.legacy_readers(tmp_path) == ["dbt/report.sql"]
    assert checklist.legacy_readers() == []


def test_checklist_items_follow_the_results(planted):
    s = replay(planted["paths"])
    items = {name: ok for ok, name, _ in checklist.items(s)}
    assert items["Every legacy column has a target column"]
    assert items["Parallel run: the last 3+ loads reconcile with zero differences"]
    assert items["The reconciliation catches a broken loader (event-time watermark run fails)"]
    assert not items["legacy.earthquakes dropped after a 14-day grace period"]
    s["hash_merge"]["loads"][-1]["reconciliation"]["ok"] = False
    assert checklist.trailing_clean_loads(s["hash_merge"]["loads"]) == 0


def test_committed_results_match_the_committed_snapshots():
    s = replay()
    assert json.loads((RESULTS / "summary.json").read_text()) == compact(s)
    assert (RESULTS / "retirement_checklist.md").read_text() == checklist.to_markdown(s)
    assert all(ld["reconciliation"]["ok"] for ld in s["hash_merge"]["loads"])
