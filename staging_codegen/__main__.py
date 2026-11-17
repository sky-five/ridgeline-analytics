import argparse
import sys
from pathlib import Path

from staging_codegen.generate import STAGING, SpecError, build, problems, write

p = argparse.ArgumentParser(
    prog="python -m staging_codegen",
    description="Write dbt staging models and tests from one YAML spec per source.",
)
p.add_argument("--check", action="store_true", help="fail if a generated file is missing, hand-edited or stale")
p.add_argument("--draft", metavar="SOURCE", help="print a starting spec for SOURCE from its raw tables in DuckDB")
p.add_argument("--db", type=Path, help="DuckDB file for --draft (default: $RIDGELINE_DUCKDB_PATH)")
args = p.parse_args()

if args.draft:
    import os

    import duckdb

    from staging_codegen.draft import draft

    db = args.db or Path(os.environ.get("RIDGELINE_DUCKDB_PATH", "warehouse/ridgeline.duckdb"))
    with duckdb.connect(str(db), read_only=True) as con:
        print(draft(con, args.draft), end="")
    sys.exit(0)

try:
    expected = build()
except SpecError as e:
    sys.exit(f"spec error: {e}")

if args.check:
    found = problems(STAGING, expected)
    if found:
        print("\n".join(found))
        sys.exit("staging files differ from the specs: edit the spec, then run python -m staging_codegen")
    print(f"{len(expected)} staging files match their specs")
else:
    changed = write(expected)
    for path in changed:
        print(f"wrote {path.relative_to(STAGING.parent.parent.parent)}")
    print(f"{len(expected)} files from {len({p.parent for p in expected})} specs, {len(changed)} changed")
