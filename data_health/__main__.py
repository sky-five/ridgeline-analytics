"""python -m data_health [--day YYYY-MM-DD] [--inject FAULT]: check one day's product events against the
contract, print a rule-by-rule table, and exit 1 if any rule failed."""
import argparse
import sys

from data_health.batches import FAULTS, inject, load_day
from data_health.contracts import check_batch, summary

p = argparse.ArgumentParser(prog="python -m data_health")
p.add_argument("--day", default="2026-06-30", help="batch day (default: the last day of the cached history)")
p.add_argument("--inject", choices=sorted(FAULTS), help="break the batch on purpose to see the contract catch it")
args = p.parse_args()

batch, accounts, loaded = load_day(args.day)
if args.inject:
    batch, loaded = inject(args.inject, batch, accounts, loaded)
violations = check_batch(batch, accounts, args.day, loaded)
table = summary(violations)
print(f"product events on {args.day}: {len(batch):,} rows, {len(table)} rules, "
      f"{(table.failed > 0).sum()} failed" + (f" (injected: {args.inject})" if args.inject else ""))
print(table.to_string(index=False))
if len(violations):
    print("\nfirst failures:")
    print(violations.head(10).to_string(index=False))
    sys.exit(1)
