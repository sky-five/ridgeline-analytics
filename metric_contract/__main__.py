"""python -m metric_contract [--update] [--base PATH]

Needs the warehouse built as of the contract's snapshot date (scripts/run_all.py --as-of 2026-06-30).
"""
import argparse
import json
import sys
from pathlib import Path

from metric_contract import CONTRACT, check, defined_versions, load, save, snapshot_values, update


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m metric_contract")
    p.add_argument("--update", action="store_true", help="record new and version-bumped metrics")
    p.add_argument("--contract", type=Path, default=CONTRACT)
    p.add_argument("--base", type=Path, help="the base branch's contract.json, to catch hand-edited values")
    args = p.parse_args(argv)

    versions = defined_versions()
    contract = load(args.contract)
    values = snapshot_values(sorted(versions))

    if args.update:
        new, refused = update(versions, contract, values)
        save(new, args.contract)
        for line in refused:
            print(f"REFUSED {line}")
        print(f"contract: {len(new['metrics'])} metrics recorded on the {new['snapshot_as_of']} snapshot")
        return 1 if refused else 0

    base = json.loads(args.base.read_text(encoding="utf-8")) if args.base and args.base.exists() else None
    problems = check(versions, contract, values, base)
    for line in problems:
        print(f"FAIL {line}")
    if problems:
        print(f"{len(problems)} metric contract problem(s). A deliberate change: bump the metric's "
              "config.meta.version in dbt/models/semantic/_metrics.yml, then run `python -m metric_contract --update`.")
        return 1
    print(f"OK {len(versions)} governed metrics match their contract on the {contract['snapshot_as_of']} snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
