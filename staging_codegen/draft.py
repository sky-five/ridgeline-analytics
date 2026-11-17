"""Draft a staging spec for a new source from its raw tables in DuckDB.

The draft is a starting point: column types come from the warehouse, the first *_id column of each
table gets unique + not_null, and accepted values and relationships are left for a person to add.
"""

from __future__ import annotations

import duckdb

DLT_COLUMNS = {"_dlt_load_id", "_dlt_id"}


def column_type(duckdb_type: str) -> str:
    t = duckdb_type.upper()
    if t.startswith("TIMESTAMP"):
        return "timestamp"
    if t == "DATE":
        return "date"
    if t.startswith(("DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC")):
        return "numeric"
    if t in {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"}:
        return "int"
    return "text"


def draft(con: duckdb.DuckDBPyConnection, source: str, schema: str | None = None) -> str:
    schema = schema or f"raw_{source}"
    rows = con.execute(
        """select table_name, column_name, data_type from information_schema.columns
           where table_schema = ? and table_name not like '\\_dlt\\_%' escape '\\'
           order by table_name, ordinal_position""",
        [schema],
    ).fetchall()
    if not rows:
        raise SystemExit(f"no tables in schema {schema}")
    lines = [
        f"# Staging spec for the {source} source. python -m staging_codegen writes the models and tests from it.",
        f"source: {source}",
        "tables:",
    ]
    current, keyed = None, False
    for table, column, dtype in rows:
        if column in DLT_COLUMNS:
            continue
        if table != current:
            if current is not None:
                lines.append("")
            lines += [f"  - table: {table}", "    columns:"]
            current, keyed = table, False
        parts = [f"name: {column}"]
        kind = column_type(dtype)
        if kind != "text":
            parts.append(f"type: {kind}")
        if not keyed and column.endswith("_id"):
            parts.append("tests: [unique, not_null]")
            keyed = True
        lines.append("      - {" + ", ".join(parts) + "}")
    return "\n".join(lines) + "\n"
