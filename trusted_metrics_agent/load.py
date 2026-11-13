"""Load the HR and payroll exports into DuckDB (schemas raw_hr, raw_payroll), then build the dbt project.

    python -m trusted_metrics_agent          # load, dbt build, print the metric catalog

The warehouse is its own file (warehouse/trusted_metrics.duckdb); the main warehouse is not touched.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from trusted_metrics_agent.hr_data import AS_OF, exports

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "warehouse" / "trusted_metrics.duckdb"


def load(db_path: Path = DEFAULT_DB) -> dict[str, int]:
    """Replace the raw tables with the exports. Returns rows per table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tables = exports().tables()
    with duckdb.connect(str(db_path)) as con:
        for name, df in tables.items():  # noqa: B007 (df is read by DuckDB below)
            con.execute(f"create schema if not exists {name.split('.')[0]}")
            con.execute(f"create or replace table {name} as select * from df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, "TRUSTED_METRICS_DUCKDB_PATH": str(db_path.resolve())}  # dbt runs from its own folder
    subprocess.run(
        [_dbt(), "build", "--profiles-dir", ".", "--vars", f"{{as_of_date: '{AS_OF}'}}", "--quiet"],
        cwd=HERE / "dbt", env=env, check=True,
    )
