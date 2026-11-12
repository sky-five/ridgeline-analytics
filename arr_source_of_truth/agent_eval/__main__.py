import argparse
import json
import sys
import tempfile
from pathlib import Path

from analyst import llm
from arr_source_of_truth.agent_baseline import KeywordClient
from arr_source_of_truth.agent_eval import RESULTS, replay, run, table, verify_tools
from arr_source_of_truth.load import AS_OF, dbt_build, load

p = argparse.ArgumentParser(prog="python -m arr_source_of_truth.agent_eval")
p.add_argument("--provider", choices=["baseline", *sorted(llm.PROVIDERS)], default="baseline")
p.add_argument("--model", default=None)
p.add_argument("--pace", type=float, default=0.0, help="seconds between model requests (free-tier limits)")
p.add_argument("--record", action="store_true", help="save the run to results/<model>.json")
p.add_argument("--replay", type=Path, help="rescore a saved run; with --db, also rerun its tool calls")
p.add_argument("--db", type=Path, help="a built ARR warehouse as of 2026-09-30 (default: build a fresh one)")
args = p.parse_args()


def _db() -> Path:
    if args.db:
        return args.db
    path = Path(tempfile.mkdtemp()) / "arr.duckdb"
    load(AS_OF, path)
    dbt_build(AS_OF, path)
    return path


if args.replay:
    report = replay(args.replay)
    if args.db:
        bad = verify_tools(report, args.db)
        if bad:
            sys.exit(f"tool results differ from the recording: {', '.join(bad)}")
    print(table(report))
    sys.exit(0)

if args.provider == "baseline":
    client = KeywordClient()
else:
    client = llm.make_client(args.provider, args.model, min_interval_seconds=args.pace)
report = run(client, _db())
print(table(report))
if args.record:
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{report['model']}.json"
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")
