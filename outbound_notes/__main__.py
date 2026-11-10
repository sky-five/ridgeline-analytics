"""python -m outbound_notes [--check] [--record --provider gemini --model M --pace S]

Reads the warehouse (RIDGELINE_DUCKDB_PATH, default warehouse/ridgeline.duckdb).
  (no flags)  write results/notes-template.json: the no-model drafts, checked
  --check     fail if notes-template.json is out of date, or any recorded model run no longer replays
  --record    draft every note with a model and write results/notes-<provider>-<model>.json (needs its key)
"""
import argparse
import json
import sys

from outbound_notes import leads, notes

p = argparse.ArgumentParser(prog="python -m outbound_notes")
p.add_argument("--check", action="store_true")
p.add_argument("--record", action="store_true")
p.add_argument("--provider", default="gemini")
p.add_argument("--model", default=None)
p.add_argument("--pace", type=float, default=6.0, help="seconds between model requests")
args = p.parse_args()

df, as_of = leads.load()
lead_facts = [leads.facts(row, as_of) for _, row in df.iterrows()]

if args.record:
    from analyst.llm import make_client

    client = make_client(args.provider, args.model)
    out = notes.record(lead_facts, as_of, client, pace=args.pace)
    path = notes.RESULTS / f"notes-{client.provider}-{client.model}.json"
    notes.RESULTS.mkdir(exist_ok=True)
    path.write_text(notes.dumps(out))
    print(f"{path.name}: {out['summary']}")
    sys.exit(0)

text = notes.dumps(notes.template_notes(lead_facts, as_of))
target = notes.RESULTS / notes.TEMPLATE_FILE
if not args.check:
    notes.RESULTS.mkdir(exist_ok=True)
    target.write_text(text)
    print(f"{target.name}: {notes.template_notes(lead_facts, as_of)['summary']}")
    sys.exit(0)

problems = [] if target.exists() and target.read_text() == text else [f"{target.name} is out of date"]
for path in notes.recorded_files():
    problems += [f"{path.name}: {x}" for x in notes.replay(json.loads(path.read_text()), lead_facts)]
if problems:
    sys.exit("\n".join(problems + ["rebuild the warehouse on 2026-06-30 and run python -m outbound_notes"]))
print(f"{target.name} and {len(notes.recorded_files())} recorded run(s) replay on {as_of:%Y-%m-%d}")
