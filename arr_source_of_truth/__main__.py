import argparse
from datetime import date
from pathlib import Path

from arr_source_of_truth.load import AS_OF, DEFAULT_DB, dbt_build, load
from arr_source_of_truth.score import RESULTS, score

p = argparse.ArgumentParser(prog="python -m arr_source_of_truth")
p.add_argument("--as-of", type=date.fromisoformat, default=AS_OF)
p.add_argument("--db", type=Path, default=DEFAULT_DB)
args = p.parse_args()

for table, n in load(args.as_of, args.db).items():
    print(f"{table:36}{n:>8,}")
dbt_build(args.as_of, args.db)
summary = score(args.as_of, args.db)
if args.as_of == AS_OF:
    RESULTS.write_text(summary.to_json() + "\n")
print(summary.to_json())
