"""python -m funnel_ask "What was CAC for Google Ads in March 2026?" [--warehouse PATH]

Builds the panel's tables from the governed metrics on the warehouse and answers the question with the same
SQL the site's "Ask the funnel" page runs. Exits 1 when the question is refused or has no value.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m funnel_ask")
    p.add_argument("question")
    p.add_argument("--warehouse", type=Path,
                   default=Path(os.environ.get("RIDGELINE_DUCKDB_PATH", ROOT / "warehouse" / "ridgeline.duckdb")))
    args = p.parse_args(argv)
    os.environ["RIDGELINE_DUCKDB_PATH"] = str(args.warehouse)
    import duckdb

    from funnel_ask.answers import answers_table, vocab_table
    from funnel_ask.ask import ask, connect

    with duckdb.connect(str(args.warehouse)) as wh:
        as_of = wh.sql("select max(date_day) from fct_mrr_daily").fetchone()[0]
    answers = answers_table(as_of)
    out = ask(connect(answers, vocab_table(answers)), args.question)
    for row in out.itertuples():
        print(row.reply)
    if out["status"].iloc[0] == "answer":
        print(f"\nvia: {out['mf_query'].iloc[0]}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
