"""Read-only SQL for agents, enforced three ways so one slip can't become a write.

1. Connection: the DuckDB file is opened read_only, so the engine refuses writes.
2. Session: external access (files, URLs, extensions) is switched off and the config locked,
   so a query can't read local files or change those settings back.
3. Statement: exactly one statement, and it must parse as a SELECT (WITH ... SELECT included).

Results are capped in rows and time.
"""
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("RIDGELINE_DUCKDB_PATH", ROOT / "warehouse" / "ridgeline.duckdb"))
MAX_ROWS = 200
TIMEOUT_S = 20.0
SESSION_CONFIG = {"enable_external_access": False, "autoload_known_extensions": False, "lock_configuration": True}


class UnsafeSQL(ValueError):
    """The statement isn't a single read-only SELECT."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool

    def as_dict(self) -> dict:
        return {"columns": self.columns, "rows": self.rows, "row_count": len(self.rows),
                "truncated": self.truncated}


def check_sql(sql: str) -> str:
    """Return the single statement if it's a SELECT, else raise UnsafeSQL."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise UnsafeSQL("empty query")
    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as e:
        raise UnsafeSQL(f"could not parse: {e}") from None
    if len(statements) != 1:
        raise UnsafeSQL(f"one statement only (got {len(statements)})")
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        raise UnsafeSQL(f"only SELECT is allowed (got {kind.name})")
    return text


def connect(db_path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"warehouse not found: {db_path} (run scripts/run_all.py first)")
    # Settings go in at open time: DuckDB shares one database per file within a process, and once
    # locked they can't be set again, so a second connection would fail if it tried.
    return duckdb.connect(str(db_path), read_only=True, config=SESSION_CONFIG)


def run_sql(con: duckdb.DuckDBPyConnection, sql: str, max_rows: int = MAX_ROWS,
            timeout_s: float = TIMEOUT_S) -> QueryResult:
    """Run one checked SELECT; returns at most max_rows rows (values made JSON-friendly)."""
    text = check_sql(sql)
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        rel = con.sql(text)
        columns = list(rel.columns)
        fetched = rel.fetchmany(max_rows + 1)
    except duckdb.InterruptException:
        raise TimeoutError(f"query ran longer than {timeout_s:.0f}s") from None
    finally:
        timer.cancel()
    rows = [[_plain(v) for v in r] for r in fetched[:max_rows]]
    return QueryResult(columns, rows, truncated=len(fetched) > max_rows)


def _plain(v):
    if v is None or isinstance(v, bool | int | float | str):
        return v
    try:
        return float(v)  # Decimal, numpy numbers
    except (TypeError, ValueError):
        return str(v)  # dates, timestamps, intervals
