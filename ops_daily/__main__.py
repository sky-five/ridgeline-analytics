import argparse
import sys
from pathlib import Path

from ops_daily.load import DEFAULT_DB, dbt_build, load
from ops_daily.run import FLAGS, OPS_DAY, SUMMARY, TODAY, flags_csv, ops_day_csv, summary, to_json, today

p = argparse.ArgumentParser(prog="python -m ops_daily")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

for table, n in load(args.db).items():
    print(f"{table:18}{n:>9,}")
dbt_build(args.db)
s = summary(args.db)
fresh = {SUMMARY: to_json(s), TODAY: today(args.db, s), FLAGS: flags_csv(args.db), OPS_DAY: ops_day_csv(args.db)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m ops_daily")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[TODAY])
