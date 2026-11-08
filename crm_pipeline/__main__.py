import argparse
from datetime import date
from pathlib import Path

from crm_pipeline.load import DEFAULT_DB, dbt_build, load
from crm_pipeline.score import RESULTS, score

p = argparse.ArgumentParser(prog="python -m crm_pipeline")
p.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 6, 30))
p.add_argument("--db", type=Path, default=DEFAULT_DB)
args = p.parse_args()

for table, n in load(args.as_of, args.db).items():
    print(f"{table:22}{n:>8,}")
dbt_build(args.as_of, args.db)
summary = score(args.as_of, args.db)
if args.as_of == date(2026, 6, 30):
    RESULTS.write_text(summary.to_json() + "\n")
print(summary.to_json())
