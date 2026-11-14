import argparse
import json
import sys
from pathlib import Path

from quote_funnel import memo
from quote_funnel.run import build, run, weekly

RESULTS = Path(__file__).resolve().parent / "results"

p = argparse.ArgumentParser(prog="python -m quote_funnel")
p.add_argument("--check", action="store_true", help="fail if the committed results are out of date")
args = p.parse_args()

def rounded(x):
    """6 significant figures, so the committed files do not depend on the last bits of a solver."""
    if isinstance(x, float):
        return float(f"{x:.6g}")
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list):
        return [rounded(v) for v in x]
    return x


summary = rounded(run())
files = {
    RESULTS / "summary.json": json.dumps(summary, indent=2, default=str) + "\n",
    RESULTS / "memo.md": memo.to_markdown(summary),
    RESULTS / "funnel_weekly.csv": weekly(build()[0]).to_csv(index=False, float_format="%.6g"),
}
if args.check:
    stale = [p.name for p, text in files.items() if not p.exists() or p.read_text() != text]
    if stale:
        sys.exit(f"out of date: {', '.join(stale)}; run python -m quote_funnel")
    print("quote funnel results match the committed files")
    sys.exit(0)
RESULTS.mkdir(exist_ok=True)
for path, text in files.items():
    path.write_text(text)
print(files[RESULTS / "memo.md"])
