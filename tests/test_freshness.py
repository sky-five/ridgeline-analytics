import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.e2e
@pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="set RUN_E2E=1")
def test_freshness_tracks_pipeline_runs_not_business_time(tmp_path):
    # Data as of three weeks ago, loaded just now: the pipeline is fresh even though sparse tables
    # (e.g. CRM deals) have no recent business activity. Freshness must not fail CI on quiet days.
    wh = tmp_path / "wh.duckdb"
    subprocess.run([sys.executable, "scripts/run_all.py", "--fresh", "--skip-dbt", "--as-of", "2026-09-15",
                    "--warehouse", str(wh), "--dlt-dir", str(tmp_path / "dlt")], cwd=ROOT, check=True)
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    result = subprocess.run([str(exe), "source", "freshness", "--profiles-dir", "."], cwd=ROOT / "dbt",
                            env={**os.environ, "RIDGELINE_DUCKDB_PATH": str(wh)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-2000:]
