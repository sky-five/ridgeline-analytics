"""Load the simulated claims operation into DuckDB (schema raw_ops), then build the dbt project on it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from ops_daily.simulate import Operation, simulate

HERE = Path(__file__).resolve().parent
DBT_DIR = HERE / "dbt"
DEFAULT_DB = HERE.parent / "warehouse" / "ops_daily.duckdb"
DB_ENV = "OPS_DAILY_DUCKDB_PATH"  # read by dbt/profiles.yml
FEEDS = ["calls", "claims"]


def load(db_path: Path = DEFAULT_DB, op: Operation | None = None) -> dict[str, int]:
    """Replace the raw_ops feeds. Returns rows per table."""
    op = op or simulate()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists raw_ops")
        for f in FEEDS:
            df = getattr(op, f)
            con.register("df", df)
            con.execute(f"create or replace table raw_ops.{f} as select * from df")
            con.unregister("df")
    return {f"raw_ops.{f}": len(getattr(op, f)) for f in FEEDS}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, DB_ENV: str(Path(db_path).resolve())}
    subprocess.run([_dbt(), "build", "--profiles-dir", ".", "--quiet"], cwd=DBT_DIR, env=env, check=True)
