"""The leads a note is written for, and the facts a note may use.

A lead is an account in the top lead-score decile that is on the call list (signed up 14 to 45 days ago, not
paid yet). The facts are the account's own first-14-day signals and the score's top reasons, nothing else.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "warehouse" / "ridgeline.duckdb"
TOP_DECILE = 10

CHANNEL_NAMES = {"referral": "a referral", "supplier_partner": "a supplier partner", "trade_show": "a trade show",
                 "organic": "search", "facebook": "Facebook", "google_ads": "a Google ad"}


def warehouse_path() -> Path:
    return Path(os.environ.get("RIDGELINE_DUCKDB_PATH", DEFAULT_DB))


def load(db: Path | None = None) -> tuple[pd.DataFrame, pd.Timestamp]:
    """(leads, as_of): top-decile call-list accounts, highest score first, ties by account_id."""
    with duckdb.connect(str(db or warehouse_path()), read_only=True) as con:
        leads = con.sql(f"""
            select s.account_id, a.company_name, a.region, s.channel, s.crew_size,
                   cast(s.signup_at as date) as signup_date, s.score_model, s.top_reasons,
                   s.proposal_wk1, s.measurements_14d, s.proposals_14d, s.signed_14d,
                   s.logins_14d, s.active_days_14d
            from fct_pqa_scores as s
            inner join dim_accounts as a using (account_id)
            where s.decile = {TOP_DECILE} and s.call_list_eligible
            order by s.score_model desc, s.account_id
        """).df()
        as_of = con.sql("select max(date_day) from fct_mrr_daily").fetchone()[0]
    return leads, pd.Timestamp(as_of)


def facts(row: pd.Series, as_of: pd.Timestamp) -> dict:
    """Everything a note about this lead may say. Plain types, so it serialises and hashes the same everywhere."""
    reasons = [r for r in str(row.top_reasons).split("; ") if r and r != "no strong signal"]
    return {
        "account_id": str(row.account_id),
        "company": str(row.company_name),
        "region": str(row.region),
        "channel": str(row.channel),
        "came_from": CHANNEL_NAMES.get(str(row.channel), str(row.channel).replace("_", " ")),
        "crew_size": str(row.crew_size),
        "days_since_signup": int((as_of.normalize() - pd.Timestamp(row.signup_date)).days),
        "proposal_wk1": bool(row.proposal_wk1),
        "measurements_14d": int(row.measurements_14d),
        "proposals_14d": int(row.proposals_14d),
        "signed_14d": int(row.signed_14d),
        "logins_14d": int(row.logins_14d),
        "active_days_14d": int(row.active_days_14d),
        "reasons": reasons,
    }


def fingerprint(f: dict) -> str:
    """Short hash of a lead's facts: a recorded draft only replays against the facts it was drafted from."""
    return hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:12]
