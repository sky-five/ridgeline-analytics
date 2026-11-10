"""python -m acquisition_spend [--check] [--move SRC DST USD]

Reads the warehouse (RIDGELINE_DUCKDB_PATH, default warehouse/ridgeline.duckdb), writes results/ or checks it.
--move prints one what-if on the monthly budget, e.g. --move trade_show google_ads 2000.
"""
import argparse
import sys

from acquisition_spend import report, whatif
from acquisition_spend.cac import in_window
from acquisition_spend.load import load

p = argparse.ArgumentParser(prog="python -m acquisition_spend")
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
p.add_argument("--move", nargs=3, metavar=("SRC", "DST", "USD"), help="one budget move on the monthly budget")
args = p.parse_args()

signups, spend, as_of = load()
if args.move:
    w = report.windows(as_of)["cac"]
    y = whatif.fit(signups, spend, w)
    monthly = in_window(spend, "date_day", w).groupby("channel").spend_usd.sum()
    budget = (monthly[monthly > 0] / report.CAC_MONTHS).round(0)
    r = whatif.move(y, budget, args.move[0], args.move[1], float(args.move[2]))
    print(f"move ${r['moved_usd']:,.0f}/month {r['src']} -> {r['dst']} (budget ${r['budget_usd']:,.0f}/month): "
          f"expected paid accounts {r['paid_before']:.1f} -> {r['paid_after']:.1f}, "
          f"CAC ${r['cac_before']:,.0f} -> ${r['cac_after']:,.0f}")
    sys.exit(0)

files = report.build(signups, spend, as_of)
stale = [n for n, text in files.items() if not (report.RESULTS / n).exists()
         or (report.RESULTS / n).read_text() != text]
if args.check:
    if stale:
        sys.exit(f"out of date: {', '.join(stale)}; rebuild the warehouse on 2026-06-30 and run python -m "
                 "acquisition_spend")
    print(f"results match the warehouse as of {as_of:%Y-%m-%d}")
else:
    report.RESULTS.mkdir(exist_ok=True)
    for n, text in files.items():
        (report.RESULTS / n).write_text(text)
    print(files["summary.json"])
