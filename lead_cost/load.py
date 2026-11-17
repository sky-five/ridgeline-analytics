"""Bronze: load every delivered export file into DuckDB as it arrived (schema bronze, all text, one table per
source, plus the batch, file and delivery time), and write bronze.load_audit with one row per file: the row count
its manifest declared, the rows that actually landed, and a checksum, so a short or repeated file is visible.
Then build the dbt project (Silver and Gold) on it."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

from lead_cost.simulate import Delivery, World, simulate

HERE = Path(__file__).resolve().parent
DBT_DIR = HERE / "dbt"
DEFAULT_DB = HERE.parent / "warehouse" / "lead_cost.duckdb"
DB_ENV = "LEAD_COST_DUCKDB_PATH"  # read by dbt/profiles.yml
SOURCES = ["search_spend", "social_spend", "search_clicks", "social_clicks", "calls", "tracking_numbers", "crm_leads"]


def _text(df: pd.DataFrame) -> pd.DataFrame:
    """The file as text, the way a CSV lands: empty cells stay empty (null)."""
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_datetime64_any_dtype(col):
            out[c] = col.dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            out[c] = col.map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
        out[c] = out[c].astype(object)
    return out


def checksum(d: Delivery) -> str:
    return hashlib.md5(_text(d.rows).to_csv(index=False).encode()).hexdigest()


def load(db_path: Path = DEFAULT_DB, deliveries: list[Delivery] | None = None) -> dict[str, int]:
    """Replace the bronze schema with the given deliveries (default: the simulated world's). Rows per table."""
    deliveries = deliveries if deliveries is not None else simulate().deliveries
    db_path.parent.mkdir(parents=True, exist_ok=True)
    frames: dict[str, list[pd.DataFrame]] = {s: [] for s in SOURCES}
    audit = []
    for batch, d in enumerate(deliveries, start=1):
        rows = _text(d.rows)
        rows["_batch_id"] = batch
        rows["_file"] = d.file
        rows["_delivered_at"] = d.delivered_at
        frames[d.source].append(rows)
        audit.append({"batch_id": batch, "source": d.source, "file": d.file, "delivered_at": d.delivered_at,
                      "declared_rows": d.declared_rows, "checksum": checksum(d)})
    with duckdb.connect(str(db_path)) as con:
        con.execute("drop schema if exists bronze cascade")
        con.execute("create schema bronze")
        for s in SOURCES:
            df = pd.concat(frames[s], ignore_index=True)
            con.register("df", df)
            con.execute(f"create table bronze.{s} as select * from df")
            con.unregister("df")
        con.register("audit", pd.DataFrame(audit))
        con.execute("create table bronze.load_audit as select * from audit")
        con.unregister("audit")
        # what actually landed, counted from the bronze tables (not from the manifest)
        landed = " union all ".join(f"select _batch_id, count(*) as n from bronze.{s} group by 1" for s in SOURCES)
        con.execute(f"""create or replace table bronze.load_audit as
                        select a.*, coalesce(l.n, 0)::int as loaded_rows
                        from bronze.load_audit a left join ({landed}) l on l._batch_id = a.batch_id
                        order by a.batch_id""")
        counts = {f"bronze.{s}": con.sql(f"select count(*) from bronze.{s}").fetchone()[0] for s in SOURCES}
        counts["bronze.load_audit"] = len(audit)
    return counts


def _dbt() -> str:
    """dbt from PATH, else the one next to this Python (a venv that is not activated)."""
    return shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")


def dbt(db_path: Path, command: str, target_path: Path | None = None, check: bool = True) -> int:
    """Run one dbt command (build, run, test, seed) on the warehouse at db_path. Returns the exit code."""
    env = {**os.environ, DB_ENV: str(Path(db_path).resolve())}
    args = [_dbt(), command, "--profiles-dir", ".", "--quiet"]
    if target_path:
        args += ["--target-path", str(target_path)]
    return subprocess.run(args, cwd=DBT_DIR, env=env, check=check, capture_output=not check).returncode


def dbt_build(db_path: Path = DEFAULT_DB) -> None:
    dbt(db_path, "build")


def world_and_load(db_path: Path = DEFAULT_DB) -> World:
    w = simulate()
    load(db_path, w.deliveries)
    return w
