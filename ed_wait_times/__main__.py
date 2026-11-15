import argparse
import sys
from pathlib import Path

from ed_wait_times import public
from ed_wait_times.load import DEFAULT_DB, dbt_build, load
from ed_wait_times.run import SITE_WEEK, SUMMARY, site_week_csv, summary, to_json

p = argparse.ArgumentParser(prog="python -m ed_wait_times")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
p.add_argument("--refresh", action="store_true", help="download the public ICU file again and stop if it changed")
args = p.parse_args()

if args.refresh:
    public.refresh()
    print(f"{public.PATH.name} is unchanged")
for table, n in load(args.db).items():
    print(f"{table:30}{n:>9,}")
dbt_build(args.db)
s = summary(args.db)
fresh = {SUMMARY: to_json(s), SITE_WEEK: site_week_csv(args.db)}
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m ed_wait_times")
        print(f"results/{path.name} matches")
else:
    SUMMARY.parent.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
w = s["last_week"]
print(f"week {w['week_start']} to {w['week_end']}: over the {w['target_hours']}-hour target: "
      f"{', '.join(w['breached']) or 'none'}; not reported: {', '.join(w['not_reported']) or 'none'}")
