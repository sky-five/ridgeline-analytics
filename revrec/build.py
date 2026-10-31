"""Load billing into DuckDB and run the SQL models in order."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from revrec.billing import AS_OF, Billing

SQL_DIR = Path(__file__).parent / "sql"

SOURCES = {
    "invoice_lines": {
        "line_id": "varchar", "invoice_id": "varchar", "customer_id": "varchar", "subscription_id": "varchar",
        "kind": "varchar", "issued_on": "date", "period_start": "date", "period_end": "date",
        "amount_cents": "bigint",
    },
    "subscription_changes": {
        "subscription_id": "varchar", "customer_id": "varchar", "effective_on": "date", "mrr_cents": "bigint",
        "reason": "varchar",
    },
}


def build(billing: Billing, as_of: date = AS_OF, path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path)
    for table, columns in SOURCES.items():
        con.execute(f"create or replace table {table} ({', '.join(f'{c} {t}' for c, t in columns.items())})")
        rows = getattr(billing, table)
        if rows:
            con.register("src_df", pd.DataFrame(rows, columns=list(columns)))
            con.execute(f"insert into {table} select * from src_df")
            con.unregister("src_df")
    con.execute("create or replace table params as select ?::date as as_of", [as_of])

    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        con.execute(sql_file.read_text())
    return con
