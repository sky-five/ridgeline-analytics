"""Load the simulated auction into DuckDB (schema raw_auction), then build the dbt project on it.

    python -m vehicle_auction

The planted counterfactual (each test vehicle's first-run outcome under the other arm) stays out of
the warehouse; readout.py checks the test's estimate against it.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

from vehicle_auction.simulate import Auction, simulate

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "warehouse" / "auction.duckdb"


def raw_tables(auction: Auction) -> dict[str, pd.DataFrame]:
    """What the auction system would export: no truth columns, an assignment log for the test."""
    assignments = auction.truth[["vehicle_id", "arm"]].merge(
        auction.vehicles[["vehicle_id", "consigned_on"]], on="vehicle_id"
    ).rename(columns={"consigned_on": "assigned_on"})
    return {
        "vehicles": auction.vehicles,
        "listings": auction.listings,
        "bids": auction.bids,
        "test_assignments": assignments,
    }


def load(db_path: Path = DEFAULT_DB, auction: Auction | None = None) -> dict[str, int]:
    """Replace raw_auction.* with the simulated auction. Returns rows per table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tables = raw_tables(auction or simulate())
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists raw_auction")
        for name, df in tables.items():
            con.register("df", df)
            con.execute(f"create or replace table raw_auction.{name} as select * from df")
            con.unregister("df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, "AUCTION_DUCKDB_PATH": str(Path(db_path).resolve())}
    subprocess.run([_dbt(), "build", "--profiles-dir", ".", "--quiet"], cwd=HERE / "dbt", env=env, check=True)
