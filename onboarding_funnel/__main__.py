import argparse
import sys
from pathlib import Path

from onboarding_funnel.load import DEFAULT_DB, dbt_build, load
from onboarding_funnel.run import FINDINGS, SUMMARY, WEEKLY, findings, summary, to_json, weekly_csv

p = argparse.ArgumentParser(prog="python -m onboarding_funnel")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

for table, n in load(args.db).items():
    print(f"{table:24}{n:>9,}")
dbt_build(args.db)
s = summary(args.db)
fresh = {SUMMARY: to_json(s), WEEKLY: weekly_csv(args.db), FINDINGS: findings(s)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m onboarding_funnel")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[FINDINGS])
