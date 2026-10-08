"""Product-qualified account (PQA) score.

Two scores side by side:
  - score_points: a transparent rule-based score a sales lead can read
  - score_model:  logistic regression on the same first-14-day signals
Trained on mature accounts that signed up before 2026-01-01, back-tested on mature 2026 signups.
Target: paid within 60 days of signup.
"""
import datetime  # noqa: F401 -- dbt renders the as_of_date config as a datetime.date literal

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

TRAIN_BEFORE = pd.Timestamp("2026-01-01")
COUNTS = ["measurements_14d", "proposals_14d", "signed_14d", "logins_14d", "active_days_14d"]
CHANNELS = ["referral", "supplier_partner", "trade_show", "organic", "facebook"]
CREWS = ["2-5", "6-15", "16+"]
LABELS = {
    "proposal_wk1": "sent a proposal in week 1",
    "measurements_14d": "ordered measurements",
    "proposals_14d": "sent several proposals",
    "signed_14d": "got a proposal signed",
    "logins_14d": "logs in often",
    "active_days_14d": "active on many days",
    "ch_referral": "came by referral",
    "ch_supplier_partner": "came via supplier partner",
    "ch_trade_show": "met at a trade show",
    "ch_organic": "found us organically",
    "ch_facebook": "facebook signup",
    "crew_2-5": "crew of 2-5",
    "crew_6-15": "crew of 6-15",
    "crew_16+": "crew of 16+",
}


def points(r) -> int:
    p = 40 if r.proposal_wk1 else 0
    p += min(int(r.measurements_14d), 5) * 5
    p += 15 if r.signed_14d > 0 else 0
    p += 10 if r.channel in ("referral", "supplier_partner") else 0
    p += 10 if r.crew_size in ("6-15", "16+") else 0
    return min(p, 100)


def _to_pandas(relation) -> pd.DataFrame:
    """DuckDB gives a relation with .df(); Snowflake gives a Snowpark DataFrame with UPPERCASE columns."""
    df = relation.to_pandas() if hasattr(relation, "to_pandas") else relation.df()
    return df.rename(columns=str.lower)


def model(dbt, session):
    dbt.config(materialized="table", packages=["scikit-learn", "pandas", "numpy"])
    as_of = pd.Timestamp(dbt.config.get("as_of_date"))
    df = _to_pandas(dbt.ref("fct_account_funnel"))
    df["signup_at"] = pd.to_datetime(df.signup_at)

    df["proposal_wk1"] = df.proposal_wk1.astype(int)
    for c in CHANNELS:
        df[f"ch_{c}"] = (df.channel == c).astype(int)
    for c in CREWS:
        df[f"crew_{c}"] = (df.crew_size == c).astype(int)
    x_cols = ["proposal_wk1"] + COUNTS + [f"ch_{c}" for c in CHANNELS] + [f"crew_{c}" for c in CREWS]
    X = df[x_cols].astype(float)
    X[COUNTS] = np.log1p(X[COUNTS])
    y = df.is_paid_60d.astype(int)

    mature = df.is_mature.astype(bool)
    train = mature & (df.signup_at < TRAIN_BEFORE)
    test = mature & (df.signup_at >= TRAIN_BEFORE)

    clf = LogisticRegression(max_iter=2000)
    clf.fit(X[train], y[train])
    df["score_model"] = clf.predict_proba(X)[:, 1]
    df["score_points"] = df.apply(points, axis=1).astype(int)

    # top reasons = the biggest positive contributions to this account's log-odds
    contrib = X.to_numpy() * clf.coef_[0]
    order = np.argsort(-contrib, axis=1)[:, :3]
    df["top_reasons"] = [
        "; ".join(LABELS[x_cols[j]] for j in row if contrib[i, j] > 0.1) or "no strong signal"
        for i, row in enumerate(order)
    ]
    df["split"] = np.select([train, test], ["train", "test"], "not_labelled")
    df["decile"] = (pd.qcut(df.score_model.rank(method="first"), 10, labels=False) + 1).astype(int)
    days_since = (as_of - df.signup_at.dt.normalize()).dt.days
    df["call_list_eligible"] = (df.first_paid_at.isna() | (df.first_paid_at > as_of)) & days_since.between(14, 45)

    return df[[
        "account_id", "signup_at", "channel", "crew_size", "score_model", "score_points", "decile",
        "top_reasons", "split", "is_paid_60d", "call_list_eligible", "proposal_wk1", *COUNTS,
    ]]
