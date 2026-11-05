"""python -m experiments [--check]: run the simulated A/B test analysis and write (or check) the results file."""

from __future__ import annotations

import argparse
import json
import sys

from experiments.analysis import RESULTS, _round, analyse, readout, write


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed results file is out of date")
    args = parser.parse_args()
    if args.check:
        fresh = json.loads(json.dumps(_round(analyse())))
        committed = json.loads(RESULTS.read_text(encoding="utf-8"))
        if fresh != committed:
            print(f"{RESULTS} is out of date: run python -m experiments", file=sys.stderr)
            return 1
        print(readout(committed))
        return 0
    print(readout(write()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
