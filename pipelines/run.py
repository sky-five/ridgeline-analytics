"""Load every simulated system into the warehouse as of a date.

    python -m pipelines.run --as-of 2026-10-07 [--destination duckdb|snowflake]
"""
import argparse
from datetime import date

import dlt

from pipelines.sources import SYSTEMS, ridgeline_source
from simulator.api import MockApi

DEFAULT_DUCKDB = "warehouse/ridgeline.duckdb"


def _destination(name: str, duckdb_path: str):
    if name == "duckdb":
        return dlt.destinations.duckdb(credentials=duckdb_path)
    if name == "snowflake":
        return dlt.destinations.snowflake()  # credentials from .dlt/secrets.toml or env (Phase 2)
    raise ValueError(f"unknown destination {name!r}")


def load(as_of: date, destination: str = "duckdb", duckdb_path: str = DEFAULT_DUCKDB,
         pipelines_dir: str | None = None) -> dict[str, int]:
    """Run one pipeline per system. Returns rows loaded per table."""
    api = MockApi(as_of)
    counts: dict[str, int] = {}
    for system in SYSTEMS:
        pipeline = dlt.pipeline(
            pipeline_name=f"ridgeline_{system}_{destination}",  # separate incremental state per warehouse
            destination=_destination(destination, duckdb_path),
            dataset_name=f"raw_{system}",
            pipelines_dir=pipelines_dir,
        )
        pipeline.run(ridgeline_source(system, api))
        row_counts = pipeline.last_trace.last_normalize_info.row_counts
        for table in (t for t, s in row_counts.items() if not t.startswith("_dlt")):
            counts[table] = row_counts[table]
    return counts


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--destination", default="duckdb", choices=["duckdb", "snowflake"])
    p.add_argument("--duckdb-path", default=DEFAULT_DUCKDB)
    args = p.parse_args()
    for table, n in sorted(load(args.as_of, args.destination, args.duckdb_path).items()):
        print(f"{table:24}{n:>10,}")


if __name__ == "__main__":
    main()
