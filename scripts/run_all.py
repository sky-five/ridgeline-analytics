"""Simulate -> load (dlt) -> transform (dbt), end to end.

    python scripts/run_all.py [--as-of YYYY-MM-DD] [--fresh] [--skip-load] [--skip-dbt] [--destination duckdb]

The as-of date defaults to yesterday (UTC): the last full simulated day. Without --fresh the load is
incremental: each dlt pipeline only pulls rows whose updated_at is past its saved cursor. A run refuses to
go back in time (an earlier as-of date than the warehouse already holds needs --fresh), and dlt state
without its warehouse file is thrown away, so a lost warehouse is rebuilt instead of left empty.
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
    env = {**os.environ, "RIDGELINE_DUCKDB_PATH": str(warehouse.resolve())}  # dbt runs from dbt/
    print("+", " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, cwd=DBT_DIR, env=env, check=True)


def loaded_as_of_path(warehouse: Path) -> Path:
    """Small marker file next to the warehouse: the as-of date of its last load."""
    return warehouse.with_name(warehouse.name + ".as_of")


def prepare(warehouse: Path, dlt_dir: Path, as_of: date, fresh: bool) -> str:
    """Decide between a full and an incremental load and clear old state if needed. Returns the mode."""
    marker = loaded_as_of_path(warehouse)
    if not fresh and warehouse.exists() and marker.exists():
        loaded = date.fromisoformat(marker.read_text().strip())
        if as_of < loaded:
            raise SystemExit(f"warehouse already holds {loaded}; use --fresh to load the earlier date {as_of}")
        return "incremental"
    # fresh by request, or nothing usable to build on: start both the warehouse and dlt state over
    warehouse.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    shutil.rmtree(dlt_dir, ignore_errors=True)
    return "full"


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
    args.warehouse, args.dlt_dir = args.warehouse.resolve(), args.dlt_dir.resolve()

    args.warehouse.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_load:
        mode = "full"
        if args.destination == "duckdb":
            mode = prepare(args.warehouse, args.dlt_dir, args.as_of, args.fresh)
        elif args.fresh:
            shutil.rmtree(args.dlt_dir, ignore_errors=True)
        counts = load(args.as_of, args.destination, str(args.warehouse), pipelines_dir=str(args.dlt_dir))
        if args.destination == "duckdb":
            loaded_as_of_path(args.warehouse).write_text(f"{args.as_of}\n")
        print(f"{mode} load: {sum(counts.values()):,} rows as of {args.as_of}", flush=True)
    elif args.fresh:
        raise SystemExit("--fresh with --skip-load would leave an empty warehouse")
    if not args.skip_dbt:
        _dbt("deps", as_of=args.as_of, warehouse=args.warehouse)
        _dbt("build", as_of=args.as_of, warehouse=args.warehouse)
        from scripts.export_reporting import export  # dashboard tables from the governed metrics

        export(args.warehouse, args.as_of)
        from arr_source_of_truth.report import publish  # the ARR page's tables, from its own dbt project

        publish(args.as_of, args.warehouse, args.warehouse.with_name("arr.duckdb"))


if __name__ == "__main__":
    main()
