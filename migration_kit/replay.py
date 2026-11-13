"""Replay snapshots through both loaders, reconciling after every load."""
import json
from collections import Counter
from pathlib import Path

import duckdb

from migration_kit.feed import snapshots
from migration_kit.loaders import STRATEGIES, load_legacy, load_target, setup
from migration_kit.reconcile import reconcile

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TOTALS = ("inserted", "updated", "returned", "aged_out", "deleted")


def run(paths: list[Path], strategy: str, con: duckdb.DuckDBPyConnection) -> dict:
    setup(con)
    loads = []
    for path in paths:
        row = load_target(con, path, strategy)
        row["legacy_rows"] = load_legacy(con, path)
        row["reconciliation"] = reconcile(con)
        loads.append(row)
    columns = Counter()
    for (cols,) in con.execute("select changed_columns from target.earthquake_changes "
                               "where change_type = 'update'").fetchall():
        columns.update(cols.split(","))
    return {
        "loads": loads,
        "totals": {k: sum(ld[k] for ld in loads[1:]) for k in TOTALS},
        "updated_columns": dict(sorted(columns.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def replay(paths: list[Path] | None = None, db: Path | None = None) -> dict:
    """Both strategies on the same snapshots; the hash merge's tables are left in `db` if given."""
    paths = paths or snapshots()
    out = {"snapshots": [p.name for p in paths]}
    for strategy in STRATEGIES:
        keep = db is not None and strategy == "hash_merge"
        if keep:
            db.parent.mkdir(parents=True, exist_ok=True)
            db.unlink(missing_ok=True)
        with duckdb.connect(str(db) if keep else ":memory:") as con:
            out[strategy] = run(paths, strategy, con)
            if strategy == "hash_merge":
                out["target_columns"] = [r[0] for r in con.execute(
                    "select column_name from information_schema.columns where table_schema = 'target' "
                    "and table_name = 'earthquakes' order by ordinal_position").fetchall()]
                out["history_kept"] = con.execute(
                    "select count(*) from target.earthquakes where not in_feed").fetchone()[0]
    return out


def compact(summary: dict) -> dict:
    """What goes in results/summary.json: id lists shortened to counts plus the first few ids."""
    def shrink(rec: dict) -> dict:
        r = dict(rec)
        for k in ("only_in_legacy", "only_in_target", "rows_differing"):
            r[k] = {"count": len(rec[k]), "first": rec[k][:5]}
        r["aggregates"] = {k: a["match"] for k, a in rec["aggregates"].items()}
        return r
    out = json.loads(json.dumps(summary, default=str))
    for strategy in STRATEGIES:
        for ld in out[strategy]["loads"]:
            ld["reconciliation"] = shrink(ld["reconciliation"])
    return out
