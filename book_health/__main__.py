import argparse
import sys
from pathlib import Path

from book_health.load import DEFAULT_DB, dbt_build, load
from book_health.run import (
    BACKTEST,
    BACKTEST_PATH,
    BRIEF,
    FORECAST,
    PROVINCE_MONTH,
    SEGMENT_WATCH,
    SUMMARY,
    backtest,
    backtest_csv,
    backtest_path_csv,
    brief,
    forecast_csv,
    province_month_csv,
    segment_watch_csv,
    summary,
    to_json,
)

p = argparse.ArgumentParser(prog="python -m book_health")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

for table, n in load(args.db).items():
    print(f"{table:24}{n:>9,}")
dbt_build(args.db)
bt = backtest(args.db)
s = summary(args.db, bt)
fresh = {SUMMARY: to_json(s), PROVINCE_MONTH: province_month_csv(args.db), BACKTEST: backtest_csv(bt),
         FORECAST: forecast_csv(args.db, bt), BRIEF: brief(s),
         SEGMENT_WATCH: segment_watch_csv(args.db), BACKTEST_PATH: backtest_path_csv(bt)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m book_health")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[BRIEF])
