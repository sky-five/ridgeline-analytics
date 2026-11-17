import argparse
import sys
from pathlib import Path

from lead_cost.load import DEFAULT_DB, dbt_build, load
from lead_cost.run import (
    CAMPAIGN_COST,
    CLIENT_COST,
    FAULTS_FILE,
    SUMMARY,
    campaign_cost_csv,
    client_cost_csv,
    faults,
    summary,
    to_json,
)
from lead_cost.simulate import simulate

p = argparse.ArgumentParser(prog="python -m lead_cost")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

w = simulate()
for table, n in load(args.db, w.deliveries).items():
    print(f"{table:24}{n:>9,}")
dbt_build(args.db)
s = summary(args.db, w)
fresh = {SUMMARY: to_json(s), CAMPAIGN_COST: campaign_cost_csv(args.db), CLIENT_COST: client_cost_csv(args.db),
         FAULTS_FILE: to_json(faults(w, s["headline"]))}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m lead_cost")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[CLIENT_COST])
