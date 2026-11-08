"""python -m customer_health [--check]: build the snapshots, compare score and model, write (or check) results."""
import argparse
import json
import sys

from customer_health.model import RESULTS, evaluate

p = argparse.ArgumentParser(prog="python -m customer_health")
p.add_argument("--check", action="store_true", help="fail if the committed results file is out of date")
args = p.parse_args()
summary = evaluate()
if args.check:
    if json.loads(summary.to_json()) != json.loads(RESULTS.read_text()):
        sys.exit(f"{RESULTS} is out of date: run python -m customer_health")
else:
    RESULTS.write_text(summary.to_json() + "\n")
print(summary.to_json())
