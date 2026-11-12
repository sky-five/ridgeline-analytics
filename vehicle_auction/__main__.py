import argparse
import sys
from pathlib import Path

from vehicle_auction.load import DEFAULT_DB, dbt_build, load
from vehicle_auction.readout import RESULTS, summary, to_json
from vehicle_auction.simulate import simulate

p = argparse.ArgumentParser(prog="python -m vehicle_auction")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if results/summary.json is out of date")
args = p.parse_args()

auction = simulate()
for table, n in load(args.db, auction).items():
    print(f"{table:18}{n:>8,}")
dbt_build(args.db)
out = to_json(summary(args.db, auction))
if args.check:
    if RESULTS.read_text() != out:
        sys.exit(f"{RESULTS} is out of date: run python -m vehicle_auction")
    print("results/summary.json matches")
else:
    RESULTS.write_text(out)
    print(out)
