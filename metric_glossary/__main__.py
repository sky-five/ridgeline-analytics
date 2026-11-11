"""python -m metric_glossary [--warehouse PATH]

Recomputes every governed metric month by month with plain SQL (checks.py) and compares it with MetricFlow.
Exits 1 if any metric disagrees in any month, or if a governed metric has no check.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m metric_glossary")
    p.add_argument("--warehouse", type=Path,
                   default=Path(os.environ.get("RIDGELINE_DUCKDB_PATH", ROOT / "warehouse" / "ridgeline.duckdb")))
    args = p.parse_args(argv)
    os.environ["RIDGELINE_DUCKDB_PATH"] = str(args.warehouse)
    from metric_glossary.reconcile import reconcile

    results = reconcile(args.warehouse)
    for r in results:
        print(f"{'OK  ' if r.ok else 'FAIL'} {r.name:26}{r.months:>4} months")
        for month, g, c in r.mismatches[:5]:
            print(f"       {month}: governed {g} vs check {c}")
    bad = [r.name for r in results if not r.ok]
    print(f"{len(results) - len(bad)} of {len(results)} governed metrics reconcile with their independent check")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
