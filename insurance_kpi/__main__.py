import argparse
import sys

from insurance_kpi.run import RESULTS, build, outputs

p = argparse.ArgumentParser(prog="python -m insurance_kpi")
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

fresh = outputs(build())
if args.check:
    for path, text in fresh.items():
        if not path.exists() or path.read_text() != text:
            sys.exit(f"{path} is out of date: run python -m insurance_kpi")
        print(f"results/{path.name} matches")
else:
    RESULTS.mkdir(exist_ok=True)
    for path, text in fresh.items():
        path.write_text(text)
    print(fresh[RESULTS / "kpi_tree.md"])
