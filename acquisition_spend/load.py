"""Read the two inputs from the built warehouse: one row per signup, and spend per channel per day."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "warehouse" / "ridgeline.duckdb"


def warehouse_path() -> Path:
    return Path(os.environ.get("RIDGELINE_DUCKDB_PATH", DEFAULT_DB))


def load(db: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """(signups, spend, as_of). signups: account, signup date, channel, 60-day outcome, maturity, score decile."""
    with duckdb.connect(str(db or warehouse_path()), read_only=True) as con:
        signups = con.sql("""
            select f.account_id, cast(f.signup_at as date) as signup_date, f.channel,
                   f.is_paid_60d, f.is_mature, s.decile
            from fct_account_funnel as f
            inner join fct_pqa_scores as s using (account_id)
        """).df()
        spend = con.sql("""
            select date_day, channel, cast(spend_usd as double) as spend_usd
            from fct_marketing_channel_daily
        """).df()
        as_of = con.sql("select max(date_day) from fct_mrr_daily").fetchone()[0]
    signups["signup_date"] = pd.to_datetime(signups.signup_date)
    spend["date_day"] = pd.to_datetime(spend.date_day)
    return signups, spend, pd.Timestamp(as_of)
