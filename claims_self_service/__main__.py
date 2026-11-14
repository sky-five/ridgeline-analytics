import argparse
import sys
from pathlib import Path

from claims_self_service.load import DEFAULT_DB, dbt_build, load
from claims_self_service.run import CUBE, SUMMARY, cube, summary, to_csv, to_json
from claims_self_service.simulate import simulate

p = argparse.ArgumentParser(prog="python -m claims_self_service")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

book = simulate()
for table, n in load(args.db, book).items():
    print(f"{table:10}{n:>8,}")
dbt_build(args.db)
fresh = {SUMMARY: to_json(summary(args.db, book)), CUBE: to_csv(cube(args.db))}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m claims_self_service")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[SUMMARY])
