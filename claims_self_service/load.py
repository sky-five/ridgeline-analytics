"""Load the simulated book into DuckDB (schema raw_claims), then build the dbt project on it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from claims_self_service.simulate import Book, simulate

HERE = Path(__file__).resolve().parent
DBT_DIR = HERE / "dbt"
DEFAULT_DB = HERE.parent / "warehouse" / "claims_self_service.duckdb"
DB_ENV = "CLAIMS_DUCKDB_PATH"  # read by dbt/profiles.yml


def load(db_path: Path = DEFAULT_DB, book: Book | None = None) -> dict[str, int]:
    """Replace raw_claims.* with the simulated book. Returns rows per table."""
    book = book or simulate()
    tables = {"policies": book.policies, "perils": book.perils, "claims": book.claims}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists raw_claims")
        for name, df in tables.items():
            con.register("df", df)
            con.execute(f"create or replace table raw_claims.{name} as select * from df")
            con.unregister("df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    """dbt build also writes target/semantic_manifest.json, which MetricFlow reads."""
    env = {**os.environ, DB_ENV: str(Path(db_path).resolve())}
    subprocess.run([_dbt(), "build", "--profiles-dir", ".", "--quiet"], cwd=DBT_DIR, env=env, check=True)
