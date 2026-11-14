"""Load the simulated surgical suite into DuckDB (schema raw_or), then build the dbt project on it.

The replay with the auto-release rule switched off stays out of the warehouse; roi.py checks the
estimate against it.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from or_utilisation.simulate import Suite, simulate

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "warehouse" / "or_utilisation.duckdb"


def load(db_path: Path = DEFAULT_DB, suite: Suite | None = None) -> dict[str, int]:
    """Replace raw_or.* with the simulated suite. Returns rows per table."""
    suite = suite or simulate()
    tables = {"services": suite.services, "blocks": suite.blocks, "releases": suite.releases, "cases": suite.cases}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists raw_or")
        for name, df in tables.items():
            con.register("df", df)
            con.execute(f"create or replace table raw_or.{name} as select * from df")
            con.unregister("df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, "OR_DUCKDB_PATH": str(Path(db_path).resolve())}
    subprocess.run([_dbt(), "build", "--profiles-dir", ".", "--quiet"], cwd=HERE / "dbt", env=env, check=True)
