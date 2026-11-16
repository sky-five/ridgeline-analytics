"""Load the simulated insurance book into DuckDB (schema raw_book), then build the dbt project on it.

Claims reported after the as-of date go to labels.late_claims, which the dbt models never read; run.py uses them
to say how far the last months' loss ratio is understated.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from book_health.simulate import Book, simulate

HERE = Path(__file__).resolve().parent
DBT_DIR = HERE / "dbt"
DEFAULT_DB = HERE.parent / "warehouse" / "book_health.duckdb"
DB_ENV = "BOOK_HEALTH_DUCKDB_PATH"  # read by dbt/profiles.yml
FEEDS = ["policies", "terms", "claims"]


def load(db_path: Path = DEFAULT_DB, book: Book | None = None) -> dict[str, int]:
    """Replace the raw_book feeds and labels.late_claims. Returns rows per table."""
    book = book or simulate()
    tables = {f"raw_book.{f}": getattr(book, f) for f in FEEDS} | {"labels.late_claims": book.late_claims}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        for name, df in tables.items():
            con.execute(f"create schema if not exists {name.split('.')[0]}")
            con.register("df", df)
            con.execute(f"create or replace table {name} as select * from df")
            con.unregister("df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, DB_ENV: str(Path(db_path).resolve())}
    subprocess.run([_dbt(), "build", "--profiles-dir", ".", "--quiet"], cwd=DBT_DIR, env=env, check=True)
