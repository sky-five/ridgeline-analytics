"""The two loaders run side by side during the migration.

legacy.earthquakes   the old way: truncate and reload the whole feed every day. Cheap to reason about, but
                     it keeps no history (an event that ages out of the 30-day window is gone) and every
                     load rewrites every row.
target.earthquakes   the replacement: an incremental merge keyed on id. A change-capture step compares a row
                     hash of the snapshot with the stored hash, so only new and changed rows are written, and
                     each change is logged in target.earthquake_changes with the columns that moved. Rows that
                     leave the feed are kept with in_feed = false, marked aged_out (older than the window) or
                     deleted (dropped by the source while still inside the window).

A third strategy, event_time_watermark, is the shortcut people often take: load only events newer than the
newest one already loaded. It is here as a negative control; reconciliation must catch it.
"""
from datetime import timedelta
from pathlib import Path

import duckdb

from migration_kit.feed import COLUMNS, WINDOW_DAYS, fetched_at, read_sql

COLS = list(COLUMNS)
# The minute in a snapshot's name is when it was fetched, give or take 60 s; this margin keeps an event
# that crossed the 30-day line in that minute from being counted as a deletion.
AGE_OUT_MARGIN = timedelta(minutes=10)
STRATEGIES = ("hash_merge", "event_time_watermark")


def row_hash(alias: str = "") -> str:
    """md5 over every feed column, nulls spelled out so null and '' differ."""
    p = f"{alias}." if alias else ""
    parts = ", ".join(f"coalesce(cast({p}\"{c}\" as varchar), '<null>')" for c in COLS)
    return f"md5(concat_ws('|', {parts}))"


def _q(c: str) -> str:
    return f'"{c}"'


def setup(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists legacy")
    con.execute("create schema if not exists target")
    typed = ", ".join(f"{_q(c)} {t}" for c, t in COLUMNS.items())
    con.execute(f"""
        create table if not exists target.earthquakes (
            {typed},
            row_hash varchar not null,
            in_feed boolean not null,
            left_feed_as varchar,          -- aged_out | deleted, while in_feed is false
            first_load_id integer not null,
            last_changed_load_id integer not null,
            last_seen_load_id integer not null,
            primary key (id)
        )""")
    con.execute("""
        create table if not exists target.earthquake_changes (
            load_id integer, id varchar, change_type varchar, changed_columns varchar,
            old_hash varchar, new_hash varchar
        )""")
    con.execute("""
        create table if not exists target.load_log (
            load_id integer, snapshot varchar, strategy varchar, snapshot_rows integer, inserted integer,
            updated integer, returned integer, aged_out integer, deleted integer, unchanged integer
        )""")


def load_legacy(con: duckdb.DuckDBPyConnection, snapshot: Path) -> int:
    """Full reload: whatever the feed says today, nothing more."""
    con.execute(f"create or replace table legacy.earthquakes as select * from {read_sql(snapshot)}")
    return con.execute("select count(*) from legacy.earthquakes").fetchone()[0]


def _changed_columns() -> str:
    cases = ", ".join(f"case when s.{_q(c)} is distinct from t.{_q(c)} then '{c}' end" for c in COLS)
    return f"concat_ws(',', {cases})"


def load_target(con: duckdb.DuckDBPyConnection, snapshot: Path, strategy: str = "hash_merge") -> dict:
    """Merge one snapshot into target.earthquakes. Returns the load_log row."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    load_id = con.execute("select coalesce(max(load_id), 0) + 1 from target.load_log").fetchone()[0]
    con.execute(f"create or replace temp table snap as select *, {row_hash()} as row_hash from {read_sql(snapshot)}")
    snapshot_rows = con.execute("select count(*) from snap").fetchone()[0]

    if strategy == "hash_merge":
        stage = "snap"
    else:  # only events newer than the newest already loaded; revisions and removals are never seen
        con.execute("""create or replace temp table stage_wm as select * from snap
                       where time > (select coalesce(max(time), '1900-01-01') from target.earthquakes)""")
        stage = "stage_wm"

    # 1. change capture: compare the staged rows with what the target holds
    con.execute(f"""
        insert into target.earthquake_changes
        select {load_id}, s.id,
               case when t.id is null then 'insert' when not t.in_feed then 'returned' else 'update' end,
               case when t.id is null then null else {_changed_columns()} end,
               t.row_hash, s.row_hash
        from {stage} s left join target.earthquakes t on t.id = s.id
        where t.id is null or t.row_hash <> s.row_hash or not t.in_feed""")
    if strategy == "hash_merge":
        window_start = fetched_at(snapshot) - timedelta(days=WINDOW_DAYS) + AGE_OUT_MARGIN
        con.execute(f"""
            insert into target.earthquake_changes
            select {load_id}, t.id,
                   case when t.time < '{window_start:%Y-%m-%d %H:%M:%S}'::timestamp then 'aged_out' else 'deleted' end,
                   null, t.row_hash, null
            from target.earthquakes t
            where t.in_feed and not exists (select 1 from snap s where s.id = t.id)""")

    # 2. apply it
    sets = ", ".join(f"{_q(c)} = s.{_q(c)}" for c in COLS)
    cols = ", ".join(_q(c) for c in COLS)
    vals = ", ".join(f"s.{_q(c)}" for c in COLS)
    con.execute(f"""
        merge into target.earthquakes t using {stage} s on t.id = s.id
        when matched and (t.row_hash <> s.row_hash or not t.in_feed) then update set
            {sets}, row_hash = s.row_hash, in_feed = true, left_feed_as = null,
            last_changed_load_id = {load_id}, last_seen_load_id = {load_id}
        when matched then update set last_seen_load_id = {load_id}
        when not matched then insert ({cols}, row_hash, in_feed, left_feed_as, first_load_id,
                                      last_changed_load_id, last_seen_load_id)
            values ({vals}, s.row_hash, true, null, {load_id}, {load_id}, {load_id})""")
    con.execute(f"""
        update target.earthquakes t set in_feed = false, left_feed_as = c.change_type
        from target.earthquake_changes c
        where c.load_id = {load_id} and c.id = t.id and c.change_type in ('aged_out', 'deleted')""")

    counts = dict(con.execute(f"""select change_type, count(*) from target.earthquake_changes
                                  where load_id = {load_id} group by 1""").fetchall())
    changed = sum(counts.values()) - counts.get("aged_out", 0) - counts.get("deleted", 0)
    row = {
        "load_id": load_id, "snapshot": snapshot.name, "strategy": strategy, "snapshot_rows": snapshot_rows,
        "inserted": counts.get("insert", 0), "updated": counts.get("update", 0),
        "returned": counts.get("returned", 0), "aged_out": counts.get("aged_out", 0),
        "deleted": counts.get("deleted", 0),
        "unchanged": snapshot_rows - changed if strategy == "hash_merge" else None,
    }
    con.execute("insert into target.load_log values ($load_id, $snapshot, $strategy, $snapshot_rows, $inserted, "
                "$updated, $returned, $aged_out, $deleted, $unchanged)", row)
    return row
