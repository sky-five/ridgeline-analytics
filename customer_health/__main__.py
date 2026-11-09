"""python -m customer_health [--check]: build the snapshots, compare score and model, write (or check) the
results and the renewals-at-risk list."""
import argparse
import io
import json
import sys

from customer_health.at_risk import AT_RISK, at_risk_list
from customer_health.features import HISTORY_END, build_snapshots
from customer_health.model import RESULTS, evaluate
from pipelines.engine import world_as_of

p = argparse.ArgumentParser(prog="python -m customer_health")
p.add_argument("--check", action="store_true", help="fail if the committed results files are out of date")
args = p.parse_args()
world = world_as_of(HISTORY_END)
snaps = build_snapshots(world)
summary = evaluate(snaps)
buf = io.StringIO()
at_risk_list(world, snaps).to_csv(buf, index=False)
if args.check:
    if json.loads(summary.to_json()) != json.loads(RESULTS.read_text()):
        sys.exit(f"{RESULTS} is out of date: run python -m customer_health")
    if buf.getvalue() != AT_RISK.read_text():
        sys.exit(f"{AT_RISK} is out of date: run python -m customer_health")
else:
    RESULTS.write_text(summary.to_json() + "\n")
    AT_RISK.write_text(buf.getvalue())
print(summary.to_json())
