"""Check that DuckDB and Snowflake produce the same numbers from the same dbt project.

    python scripts/compare_targets.py   (needs SNOWFLAKE_PRIVATE_KEY_PATH, optional SNOWFLAKE_ACCOUNT)
"""
import os
import sys
from pathlib import Path

import duckdb
import snowflake.connector

ROOT = Path(__file__).resolve().parent.parent
CHECKS = {
    "mrr today": "select mrr, paying_accounts from fct_mrr_daily order by date_day desc limit 1",
    "funnel": "select count(*), sum(case when is_paid_60d then 1 else 0 end) from fct_account_funnel",
    "lead buckets": "select speed_bucket, count(*) from fct_contractor_leads group by 1 order by 1",
    "12m nrr": "select round(sum(retained_mrr) / sum(cohort_start_mrr), 4) from fct_cohort_retention "
               "where months_since_start = 12",
    "health bands": "select risk_band, count(*) from fct_account_health group by 1 order by 1",
}


def main() -> int:
    sf = snowflake.connector.connect(
        account=os.environ.get("SNOWFLAKE_ACCOUNT", "EOBKTCR-QDB70541"), user="RIDGELINE_SVC",
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"], warehouse="RIDGELINE_WH",
        role="RIDGELINE_REPORTER", database="RIDGELINE_ANALYTICS", schema="ANALYTICS",
    ).cursor()
    dk = duckdb.connect(str(ROOT / "warehouse" / "ridgeline.duckdb"), read_only=True)
    failed = 0
    for name, sql in CHECKS.items():
        a = [tuple(map(str, r)) for r in sf.execute(sql).fetchall()]
        b = [tuple(map(str, r)) for r in dk.sql(sql).fetchall()]
        failed += a != b
        print(f"{'MATCH' if a == b else 'DIFF '}  {name}" + ("" if a == b else f"  snowflake={a} duckdb={b}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
