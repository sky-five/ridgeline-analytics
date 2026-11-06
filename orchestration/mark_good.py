"""Last step of the DAG: record the as-of date as the last good build.

Runs only after dbt tests, the warehouse tests and source freshness all passed. It checks that the
reporting tables the site reads are there and not empty, then writes a small JSON marker. A publisher
(the Pages deploy) would ship only the build named in this file, so a failed night keeps the last good one.

    python -m orchestration.mark_good --warehouse warehouse/ridgeline.duckdb --as-of 2026-11-02 \
        --out warehouse/last_good.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

REQUIRED = ("kpi_monthly", "metric_catalog", "source_loads")


def mark_good(warehouse: Path, as_of: date, out: Path) -> dict:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        tables = {r[0] for r in con.sql(
            "select table_name from information_schema.tables where table_schema = 'reporting'").fetchall()}
        missing = [t for t in REQUIRED if t not in tables]
        if missing:
            raise SystemExit(f"reporting tables missing: {', '.join(missing)}")
        rows = {t: con.sql(f"select count(*) from reporting.{t}").fetchone()[0] for t in sorted(tables)}
    empty = [t for t in REQUIRED if rows[t] == 0]
    if empty:
        raise SystemExit(f"reporting tables empty: {', '.join(empty)}")
    marker = {"as_of": as_of.isoformat(), "marked_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "reporting_rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(marker, indent=2) + "\n")
    return marker


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--warehouse", type=Path, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    m = mark_good(a.warehouse, a.as_of, a.out)
    print(f"last good build: as of {m['as_of']}, {len(m['reporting_rows'])} reporting tables")


if __name__ == "__main__":
    main()
