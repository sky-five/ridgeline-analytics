"""Load the sales CRM pack as of a date into DuckDB (schema raw_crm), then build the dbt project on it.

    python -m crm_pipeline --as-of 2026-06-30

The pack's label columns (which accounts are duplicates, which close dates are backdated) are not loaded:
the warehouse sees what a CRM export would show, and score.py checks the fixes against the labels.
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb

from pipelines.engine import SALES_CRM_TABLES, sales_crm_as_of

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "warehouse" / "crm.duckdb"


def load(as_of: date, db_path: Path = DEFAULT_DB) -> dict[str, int]:
    """Replace raw_crm.* with the CRM as of `as_of`. Returns rows per table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    crm = sales_crm_as_of(as_of)
    counts = {}
    with duckdb.connect(str(db_path)) as con:
        con.execute("create schema if not exists raw_crm")
        for name in SALES_CRM_TABLES:
            df = crm[name]  # noqa: F841 (read by DuckDB below)
            con.execute(f"create or replace table raw_crm.{name} as select * from df")
            counts[name] = len(crm[name])
    return counts


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(as_of: date, db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, "CRM_DUCKDB_PATH": str(db_path)}
    subprocess.run(
        [_dbt(), "build", "--profiles-dir", ".", "--vars", f"{{as_of_date: '{as_of}'}}", "--quiet"],
        cwd=HERE / "dbt", env=env, check=True,
    )
