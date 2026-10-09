"""Simulate -> load (dlt) -> transform (dbt), end to end.

    python scripts/run_all.py [--as-of YYYY-MM-DD] [--fresh] [--skip-load] [--skip-dbt] [--destination duckdb]

The as-of date defaults to yesterday (UTC): the last full simulated day.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.run import load  # noqa: E402

DBT_DIR = ROOT / "dbt"
DUCKDB_PATH = ROOT / "warehouse" / "ridgeline.duckdb"
DLT_DIR = ROOT / ".dlt_pipelines"


def _dbt(*args: str, as_of: date, warehouse: Path) -> None:
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    cmd = [str(exe), *args, "--profiles-dir", ".", "--vars", f"{{as_of_date: '{as_of}'}}"]
    env = {**os.environ, "RIDGELINE_DUCKDB_PATH": str(warehouse)}
    print("+", " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, cwd=DBT_DIR, env=env, check=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1))
    p.add_argument("--fresh", action="store_true", help="delete the warehouse and dlt state first")
    p.add_argument("--skip-load", action="store_true")
    p.add_argument("--skip-dbt", action="store_true")
    p.add_argument("--destination", default="duckdb", choices=["duckdb", "snowflake"])
    p.add_argument("--warehouse", type=Path, default=DUCKDB_PATH, help="DuckDB file")
    p.add_argument("--dlt-dir", type=Path, default=DLT_DIR, help="dlt pipeline state folder")
    args = p.parse_args()

    if args.fresh:
        args.warehouse.unlink(missing_ok=True)
        shutil.rmtree(args.dlt_dir, ignore_errors=True)
    args.warehouse.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_load:
        counts = load(args.as_of, args.destination, str(args.warehouse), pipelines_dir=str(args.dlt_dir))
        print(f"loaded {sum(counts.values()):,} rows as of {args.as_of}", flush=True)
    if not args.skip_dbt:
        _dbt("deps", as_of=args.as_of, warehouse=args.warehouse)
        _dbt("build", as_of=args.as_of, warehouse=args.warehouse)
        from scripts.export_reporting import export  # dashboard tables from the governed metrics

        export(args.warehouse)


if __name__ == "__main__":
    main()
