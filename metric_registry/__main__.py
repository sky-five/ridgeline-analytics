import argparse
import sys
from pathlib import Path

from metric_registry import compile as registry
from metric_registry.load import DEFAULT_DB, dbt_build, load
from metric_registry.run import SUMMARY, summary, to_json
from metric_registry.simulate import simulate

p = argparse.ArgumentParser(prog="python -m metric_registry")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the generated files or results are out of date")
args = p.parse_args()

if registry.main(["--check"] if args.check else []):
    sys.exit(1)
net = simulate()
for table, n in load(args.db, net).items():
    print(f"{table:12}{n:>8,}")
dbt_build(args.db)
fresh = to_json(summary(args.db, net))
if args.check:
    if not SUMMARY.exists() or SUMMARY.read_text() != fresh:
        sys.exit(f"{SUMMARY} is out of date: run python -m metric_registry")
    print(f"results/{SUMMARY.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    SUMMARY.write_text(fresh)
    print(fresh)
