"""Load billing and CRM as of a date into DuckDB (schemas raw_billing, raw_crm), then build the dbt project.

    python -m arr_source_of_truth --as-of 2026-09-30

The planted-defect labels from crm_side.py are not loaded: the warehouse sees what the two exports show,
and score.py checks the reconciliation against the labels.
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb

from arr_source_of_truth.crm_side import won_deals_as_of
from pipelines.engine import billing_as_of

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "warehouse" / "arr.duckdb"
AS_OF = date(2026, 9, 30)  # the snapshot the README and tests are pinned to (same as revrec)


def load(as_of: date, db_path: Path = DEFAULT_DB) -> dict[str, int]:
    """Replace the raw tables with both systems as of `as_of`. Returns rows per table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tables = {
        "raw_billing.subscription_changes": billing_as_of(as_of)["subscription_changes"],
        "raw_crm.won_deals": won_deals_as_of(as_of),
    }
    with duckdb.connect(str(db_path)) as con:
        for name, df in tables.items():  # noqa: B007 (df is read by DuckDB below)
            con.execute(f"create schema if not exists {name.split('.')[0]}")
            con.execute(f"create or replace table {name} as select * from df")
    return {name: len(df) for name, df in tables.items()}


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt_build(as_of: date, db_path: Path = DEFAULT_DB) -> None:
    env = {**os.environ, "ARR_DUCKDB_PATH": str(db_path)}
    subprocess.run(
        [_dbt(), "build", "--profiles-dir", ".", "--vars", f"{{as_of_date: '{as_of}'}}", "--quiet"],
        cwd=HERE / "dbt", env=env, check=True,
    )
