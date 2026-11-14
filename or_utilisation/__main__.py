import argparse
import sys
from pathlib import Path

from or_utilisation.load import DEFAULT_DB, dbt_build, load
from or_utilisation.run import SUMMARY, WEEKLY, summary, to_json, weekly_csv
from or_utilisation.simulate import simulate

p = argparse.ArgumentParser(prog="python -m or_utilisation")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

suite = simulate()
for table, n in load(args.db, suite).items():
    print(f"{table:10}{n:>8,}")
dbt_build(args.db)
fresh = {SUMMARY: to_json(summary(args.db, suite)), WEEKLY: weekly_csv(args.db)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m or_utilisation")
    print("results/summary.json and results/utilisation_weekly.csv match")
else:
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[SUMMARY])
