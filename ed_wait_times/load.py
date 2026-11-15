"""Load the simulated ED visits and bed census (schema raw_ed) and the public ICU file (schema raw_public) into
DuckDB, then build the dbt project on them."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

from ed_wait_times import public
from ed_wait_times.simulate import World, simulate, site_frame

HERE = Path(__file__).resolve().parent
DBT_DIR = HERE / "dbt"
DEFAULT_DB = HERE.parent / "warehouse" / "ed_wait_times.duckdb"
DB_ENV = "ED_WAIT_TIMES_DUCKDB_PATH"  # read by dbt/profiles.yml


def load(db_path: Path = DEFAULT_DB, world: World | None = None) -> dict[str, int]:
    """Replace the raw tables. Returns rows per table."""
    world = world or simulate()
    tables = {"raw_ed.visits": world.visits, "raw_ed.bed_census": world.census, "raw_ed.sites": site_frame(),
              "raw_public.ontario_icu_beds": public.read()}
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
