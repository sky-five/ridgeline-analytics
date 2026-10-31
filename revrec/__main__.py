"""python -m revrec [--db PATH]: build the models, run the parallel check, print the month-end close."""

from __future__ import annotations

import argparse
import sys

from revrec.billing import AS_OF, generate
from revrec.build import build
from revrec.parallel_run import compare


def _usd(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=":memory:", help="DuckDB file to write (default: in memory)")
    args = parser.parse_args()

    billing = generate()
    con = build(billing, path=args.db)
    print(f"{len(billing.invoice_lines):,} invoice lines, {len(billing.subscription_changes):,} contract changes, "
          f"as of {AS_OF}\n")

    print("ARR bridge, last 6 months")
    print(f"{'month':<9}{'opening':>12}{'new':>10}{'react.':>9}{'expan.':>10}{'contr.':>10}{'churn':>11}"
          f"{'closing':>12}")
    for r in con.execute("select * from fct_arr_bridge order by month_start desc limit 6").fetchall()[::-1]:
        print(f"{r[0]:%Y-%m}  " + "".join(f"{_usd(v):>{w}}" for v, w in zip(r[1:8], [12, 10, 9, 10, 10, 11, 12],
                                                                          strict=True)))

    print("\nDeferred revenue rollforward, last 6 months")
    print(f"{'month':<9}{'opening':>12}{'billed':>12}{'recognized':>12}{'closing':>12}")
    for r in con.execute("select * from fct_deferred_revenue order by month_start desc limit 6").fetchall()[::-1]:
        print(f"{r[0]:%Y-%m}  " + "".join(f"{_usd(v):>12}" for v in r[1:]))

    future = con.execute(
        "select sum(recognized_cents) from fct_revenue_monthly where is_future"
    ).fetchone()[0]
    print(f"\nAlready billed, still to be earned after {AS_OF}: {_usd(future)}")

    compared, diffs = compare(con, billing, AS_OF)
    if diffs:
        print(f"\nParallel run: {len(diffs)} of {compared} numbers differ")
        print("\n".join(diffs[:20]))
        return 1
    print(f"\nParallel run: SQL and the Python reference agree on all {compared} numbers, to the cent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
