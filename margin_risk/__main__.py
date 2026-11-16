import argparse
import sys
from pathlib import Path

from margin_risk.load import DEFAULT_DB, dbt_build, load
from margin_risk.run import (
    CONCENTRATION,
    FINDINGS,
    FIRM_DAILY,
    MARGIN_CALLS,
    SECTOR_DAILY,
    SUMMARY,
    concentration_csv,
    findings,
    firm_daily_csv,
    margin_calls_csv,
    sector_daily_csv,
    summary,
    to_json,
)

p = argparse.ArgumentParser(prog="python -m margin_risk")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

for table, n in load(args.db).items():
    print(f"{table:28}{n:>9,}")
dbt_build(args.db)
s = summary(args.db)
fresh = {SUMMARY: to_json(s), FIRM_DAILY: firm_daily_csv(args.db), FINDINGS: findings(s),
         MARGIN_CALLS: margin_calls_csv(args.db), SECTOR_DAILY: sector_daily_csv(args.db),
         CONCENTRATION: concentration_csv(args.db)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m margin_risk")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[FINDINGS])
