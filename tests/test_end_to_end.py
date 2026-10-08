import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.e2e
@pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="set RUN_E2E=1")
def test_full_run_early_date_has_no_failures(tmp_path):
    subprocess.run(
        [sys.executable, "scripts/run_all.py", "--fresh", "--as-of", "2024-06-30",
         "--warehouse", str(tmp_path / "wh.duckdb"), "--dlt-dir", str(tmp_path / "dlt")],
        cwd=ROOT, check=True,
    )
    results = json.loads((ROOT / "dbt" / "target" / "run_results.json").read_text())["results"]
    bad = [r["unique_id"] for r in results if r["status"] in ("error", "fail")]
    assert results and not bad
