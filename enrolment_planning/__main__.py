import argparse
import sys
from pathlib import Path

from enrolment_planning import public
from enrolment_planning.load import DEFAULT_DB, dbt_build, load
from enrolment_planning.run import SCORES, SUMMARY, scores_csv, summary, to_json

p = argparse.ArgumentParser(prog="python -m enrolment_planning")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
p.add_argument("--refresh", action="store_true", help="download both public sources again and stop if they changed")
args = p.parse_args()

if args.refresh:
    print(f"unchanged: {', '.join(public.refresh())}")
for table, n in load(args.db).items():
    print(f"{table:36}{n:>9,}")
dbt_build(args.db)
s = summary(args.db)
fresh = {SUMMARY: to_json(s), SCORES: scores_csv(args.db)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m enrolment_planning")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
e = s["enrolments"]
print(f"fall {e['last_fall']}: {e['international']:,} international of {e['total']:,} enrolments "
      f"({e['international_share']:.1%})")
for b in s["backtest"]["next_12_months_best_rule"]:
    if b["series"] == "CA":
        print(f"{b['period']:26}best rule {b['rule']:22}WAPE {b['wape']:.1%}  bias {b['bias']:+.1%}")
