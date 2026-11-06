"""The nightly build as a list of shell steps, kept free of Airflow imports so it can be tested anywhere.

The DAG in dags/daily_build.py turns each step into a BashOperator. Airflow runs in its own virtualenv
(its pins clash with dbt's), so every step calls the project's interpreter, not Airflow's.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Airflow template for the as-of date: the run for logical date D builds the warehouse as of D - 1,
# the last full simulated day, the same date the nightly GitHub workflow uses ("yesterday").
AS_OF_TEMPLATE = "{{ macros.ds_add(ds, -1) }}"


def as_of_for(logical_date: date) -> date:
    """Python twin of AS_OF_TEMPLATE, used by tests and the backfill example."""
    return logical_date - timedelta(days=1)


@dataclass(frozen=True)
class Settings:
    root: Path
    python: Path
    warehouse: Path
    dlt_dir: Path

    @property
    def dbt(self) -> Path:
        return self.python.parent / ("dbt.exe" if os.name == "nt" else "dbt")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        root = Path(env.get("RIDGELINE_ROOT", ROOT))
        python = Path(env.get("RIDGELINE_PYTHON", root / ".venv" / "bin" / "python"))
        # Fixed paths on purpose: the warehouse tests and MetricFlow read warehouse/ridgeline.duckdb.
        return cls(root=root, python=python, warehouse=root / "warehouse" / "ridgeline.duckdb",
                   dlt_dir=root / ".dlt_pipelines")


@dataclass(frozen=True)
class Step:
    task_id: str
    argv: tuple[str, ...]
    cwd: str  # "." for the repo root, "dbt" for the dbt project
    upstream: tuple[str, ...]
    doc: str


def steps(s: Settings, as_of: str = AS_OF_TEMPLATE) -> list[Step]:
    """Ordered steps; `as_of` is a date string or the Airflow template."""
    py, dbt = str(s.python), str(s.dbt)
    dbt_vars = f"{{as_of_date: '{as_of}'}}"
    return [
        Step("load", (py, "scripts/run_all.py", "--fresh", "--skip-dbt", "--as-of", as_of,
                      "--warehouse", str(s.warehouse), "--dlt-dir", str(s.dlt_dir)), ".", (),
             "Simulate the day and load every source with dlt into a fresh DuckDB file."),
        Step("dbt_deps", (dbt, "deps", "--profiles-dir", "."), "dbt", ("load",),
             "Install dbt packages."),
        Step("dbt_build", (dbt, "build", "--profiles-dir", ".", "--vars", dbt_vars), "dbt", ("dbt_deps",),
             "Run every model, snapshot, seed and dbt test in dependency order."),
        Step("report_refresh", (py, "scripts/export_reporting.py", "--warehouse", str(s.warehouse)), ".",
             ("dbt_build",), "Write the reporting.* tables the Evidence site reads, from the governed metrics."),
        Step("warehouse_tests", (py, "-m", "pytest", "-m", "warehouse", "-q", "-p", "no:cacheprovider"), ".",
             ("report_refresh",), "Governed metrics must agree with the marts and the reporting tables."),
        Step("source_freshness", (dbt, "source", "freshness", "--profiles-dir", ".", "--vars", dbt_vars), "dbt",
             ("report_refresh",), "Every source table was loaded by this run."),
        Step("mark_good", (py, "-m", "orchestration.mark_good", "--warehouse", str(s.warehouse), "--as-of", as_of,
                           "--out", str(s.warehouse.parent / "last_good.json")), ".",
             ("warehouse_tests", "source_freshness"),
             "Record this as-of date as the last good build; a publisher only ships a build marked good."),
    ]


def bash_command(step: Step, s: Settings) -> str:
    """One shell line for a BashOperator. The as-of template survives quoting because Jinja renders it
    before bash sees the line."""
    cwd = s.root / step.cwd if step.cwd != "." else s.root
    return f"cd {shlex.quote(str(cwd))} && " + " ".join(shlex.quote(a) for a in step.argv)


def step_env(s: Settings) -> dict[str, str]:
    """Environment for every step: dbt's profile reads RIDGELINE_DUCKDB_PATH."""
    return {"RIDGELINE_DUCKDB_PATH": str(s.warehouse), "PYTHONUNBUFFERED": "1"}
