"""Prove the old and new tables hold the same data.

Compares legacy.earthquakes (what the feed says now) with the rows of target.earthquakes still in the feed.
The row hash is recomputed on both sides here rather than trusting the hash the loader stored, so a bug in
the loader's hashing cannot hide itself.

Checks, all must pass:
  row_count        same number of rows
  keys             no id on one side only
  rows             every shared id has identical values in all 22 feed columns
  aggregates       count by status and by event type, sum of magnitude, min/max event time
"""
import duckdb

from migration_kit.feed import COLUMNS
from migration_kit.loaders import row_hash

LEGACY = "legacy.earthquakes"
TARGET = "(select * from target.earthquakes where in_feed)"
AGGREGATES = {
    "rows by status": "select status as k, count(*) as v from {t} group by 1",
    "rows by type": "select type as k, count(*) as v from {t} group by 1",
    "sum of mag": "select 'all' as k, round(sum(mag), 2) as v from {t}",
    "event time range": "select 'min' as k, cast(min(time) as varchar) as v from {t} "
                        "union all select 'max', cast(max(time) as varchar) from {t}",
}


def reconcile(con: duckdb.DuckDBPyConnection) -> dict:
    n_legacy = con.execute(f"select count(*) from {LEGACY}").fetchone()[0]
    n_target = con.execute(f"select count(*) from {TARGET}").fetchone()[0]
    only_legacy = [r[0] for r in con.execute(
        f"select id from {LEGACY} except select id from {TARGET} order by 1").fetchall()]
    only_target = [r[0] for r in con.execute(
        f"select id from {TARGET} except select id from {LEGACY} order by 1").fetchall()]

    diffs = con.execute(f"""
        select l.id from {LEGACY} l join {TARGET} t using (id)
        where {row_hash('l')} <> {row_hash('t')} order by 1""").fetchall()
    differing = [r[0] for r in diffs]
    by_column = {}
    for c in COLUMNS:
        n = con.execute(f"""select count(*) from {LEGACY} l join {TARGET} t using (id)
                            where l."{c}" is distinct from t."{c}" """).fetchone()[0]
        if n:
            by_column[c] = n

    aggregates = {}
    for name, sql in AGGREGATES.items():
        left = dict(con.execute(sql.format(t=LEGACY)).fetchall())
        right = dict(con.execute(sql.format(t=TARGET)).fetchall())
        aggregates[name] = {"match": left == right, "legacy": left, "target": right}

    checks = {
        "row_count": n_legacy == n_target,
        "keys": not only_legacy and not only_target,
        "rows": not differing,
        "aggregates": all(a["match"] for a in aggregates.values()),
    }
    return {
        "ok": all(checks.values()), "checks": checks,
        "legacy_rows": n_legacy, "target_rows": n_target,
        "only_in_legacy": only_legacy, "only_in_target": only_target,
        "rows_differing": differing, "differing_by_column": by_column, "aggregates": aggregates,
    }


def to_markdown(result: dict, title: str) -> str:
    mark = {True: "pass", False: "FAIL"}
    lines = [f"### {title}: {'match' if result['ok'] else 'MISMATCH'}", "",
             "| check | result | detail |", "|---|---|---|"]
    lines.append(f"| row_count | {mark[result['checks']['row_count']]} | "
                 f"legacy {result['legacy_rows']:,}, target {result['target_rows']:,} |")
    lines.append(f"| keys | {mark[result['checks']['keys']]} | {len(result['only_in_legacy'])} only in legacy, "
                 f"{len(result['only_in_target'])} only in target |")
    cols = ", ".join(f"{c} {n}" for c, n in result["differing_by_column"].items()) or "none"
    lines.append(f"| rows | {mark[result['checks']['rows']]} | {len(result['rows_differing'])} shared ids "
                 f"differ; by column: {cols} |")
    bad = [k for k, a in result["aggregates"].items() if not a["match"]]
    lines.append(f"| aggregates | {mark[result['checks']['aggregates']]} | "
                 f"{len(result['aggregates']) - len(bad)}/{len(result['aggregates'])} match"
                 + (f"; off: {', '.join(bad)}" if bad else "") + " |")
    return "\n".join(lines) + "\n"
