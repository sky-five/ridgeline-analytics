"""Check that an incrementally loaded warehouse holds the same data as a full rebuild.

    python -m pipelines.parity warehouse/ridgeline.duckdb warehouse_full/ridgeline.duckdb

Compares every table in the two DuckDB files (raw loads, dbt models, reporting tables): the same tables,
the same columns, the same row count and the same rows. Rows are compared as an order-free fingerprint
(the sum of one hash per row), so physical row order does not matter but a missing, extra or changed row
does. Doubles are rounded to 6 decimals first, because summing the same numbers in another order can move
the last bit.

Left out on purpose, because they describe the build rather than the data: dlt's own bookkeeping tables
and columns (_dlt_loads, _dlt_id, ...), dlt staging schemas, reporting.source_loads (it counts loads,
which is exactly what differs between a nightly increment and a rebuild) and build-time columns
(built_at, generated_at, execution_time_s).

dbt snapshots are compared on their current rows only (dbt_valid_to is null). The older versions are the
point of running incrementally: a rebuild from scratch starts the history over, so it cannot have them.
The report counts them separately.
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

SKIP_TABLES = {("reporting", "source_loads")}
BUILD_COLUMNS = {"built_at", "generated_at", "execution_time_s"}
SNAPSHOT_SCHEMA = "snapshots"
FLOAT_TYPES = {"DOUBLE", "FLOAT", "REAL"}


@dataclass(frozen=True)
class TableCheck:
    schema: str
    table: str
    rows_a: int | None
    rows_b: int | None
    problem: str | None  # None when the table matches
    history_a: int = 0  # snapshot rows no longer current, not compared
    history_b: int = 0

    @property
    def name(self) -> str:
        return f"{self.schema}.{self.table}"


def _tables(con: duckdb.DuckDBPyConnection, db: str) -> dict[tuple[str, str], dict[str, str]]:
    rows = con.execute(
        """
        select c.table_schema, c.table_name, c.column_name, c.data_type
        from information_schema.columns c
        join information_schema.tables t using (table_catalog, table_schema, table_name)
        where c.table_catalog = ? and t.table_type = 'BASE TABLE'
        """,
        [db],
    ).fetchall()
    out: dict[tuple[str, str], dict[str, str]] = {}
    for schema, table, column, dtype in rows:
        if schema.endswith("_staging") or table.startswith("_dlt") or (schema, table) in SKIP_TABLES:
            continue
        if column.startswith("_dlt_") or column in BUILD_COLUMNS:
            continue
        out.setdefault((schema, table), {})[column] = dtype
    return out


def _fingerprint(con: duckdb.DuckDBPyConnection, db: str, schema: str, table: str,
                 columns: dict[str, str]) -> tuple[int, int]:
    exprs = [
        f'round("{c}", 6)' if columns[c] in FLOAT_TYPES else f'"{c}"'
        for c in sorted(columns)
    ]
    row_hash = f"hash({', '.join(exprs)})" if exprs else "0"
    where = "where dbt_valid_to is null" if schema == SNAPSHOT_SCHEMA else ""
    count, total = con.execute(
        f'select count(*), coalesce(sum({row_hash}::hugeint), 0) from "{db}"."{schema}"."{table}" {where}'
    ).fetchone()
    return int(count), int(total)


def _history(con: duckdb.DuckDBPyConnection, db: str, schema: str, table: str) -> int:
    if schema != SNAPSHOT_SCHEMA:
        return 0
    return int(con.execute(
        f'select count(*) from "{db}"."{schema}"."{table}" where dbt_valid_to is not null').fetchone()[0])


def compare(a: Path, b: Path) -> list[TableCheck]:
    """One TableCheck per table found in either warehouse, sorted by name."""
    con = duckdb.connect()
    try:
        con.execute(f"attach '{a}' as wa (read_only)")
        con.execute(f"attach '{b}' as wb (read_only)")
        ta, tb = _tables(con, "wa"), _tables(con, "wb")
        checks: list[TableCheck] = []
        for key in sorted(ta.keys() | tb.keys()):
            schema, table = key
            if key not in tb:
                checks.append(TableCheck(schema, table, None, None, "only in the first warehouse"))
                continue
            if key not in ta:
                checks.append(TableCheck(schema, table, None, None, "only in the second warehouse"))
                continue
            if set(ta[key]) != set(tb[key]):
                diff = sorted(set(ta[key]) ^ set(tb[key]))
                checks.append(TableCheck(schema, table, None, None, f"columns differ: {', '.join(diff)}"))
                continue
            na, ha = _fingerprint(con, "wa", schema, table, ta[key])
            nb, hb = _fingerprint(con, "wb", schema, table, tb[key])
            if na != nb:
                problem = f"row count {na:,} vs {nb:,}"
            elif ha != hb:
                problem = "same row count, different rows"
            else:
                problem = None
            checks.append(TableCheck(schema, table, na, nb, problem,
                                     _history(con, "wa", schema, table), _history(con, "wb", schema, table)))
        return checks
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("incremental", type=Path, help="DuckDB file built by the nightly increments")
    p.add_argument("full", type=Path, help="DuckDB file rebuilt from scratch for the same date")
    args = p.parse_args()

    checks = compare(args.incremental, args.full)
    bad = [c for c in checks if c.problem]
    rows = sum(c.rows_a or 0 for c in checks if not c.problem)
    for c in bad:
        print(f"DIFF {c.name}: {c.problem}")
    for c in checks:
        if c.history_a or c.history_b:
            print(f"history {c.name}: {c.history_a:,} earlier versions vs {c.history_b:,} (not compared)")
    print(f"{len(checks) - len(bad)} of {len(checks)} tables match ({rows:,} rows)")
    sys.exit(1 if bad or not checks else 0)


if __name__ == "__main__":
    main()
