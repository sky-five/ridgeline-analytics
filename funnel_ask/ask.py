"""Answer a question with route.sql, the same query the site's "Ask the funnel" page runs in the browser."""
from pathlib import Path

import duckdb
import pandas as pd

ROUTE_SQL = (Path(__file__).resolve().parent / "route.sql").read_text(encoding="utf-8")


def literal(text: str) -> str:
    """A SQL string literal, quoted the way the site's text input quotes it."""
    return "'" + text.replace("'", "''") + "'"


def connect(answers: pd.DataFrame, vocab: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("funnel_answers", answers)
    con.register("funnel_vocab", vocab)
    return con


def ask(con: duckdb.DuckDBPyConnection, question: str) -> pd.DataFrame:
    """Rows with status 'answer' (one per channel for a by-channel question), or one 'refused'/'no_data' row."""
    return con.sql(ROUTE_SQL.replace("{question}", literal(question))).df()
