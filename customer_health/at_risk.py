"""The renewals-at-risk list: every live subscription on the morning after the simulated history ends,
scored by the hand-weighted health score and by the churn model, with the reasons behind each score.

The model is the same one compared in model.py (fitted on the training accounts' labelled snapshots), so
the list and the held-out comparison on the page describe the same two methods.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from customer_health.features import FEATURES, HISTORY_END, build_snapshots
from customer_health.model import RISK_SHARE, SCORE_RULES, fit_model, health_score, is_test_account
from pipelines.engine import world_as_of

AT_RISK = Path(__file__).resolve().parent / "results" / "at_risk.csv"
AS_OF = pd.Timestamp(HISTORY_END) + pd.Timedelta(days=1)

# one plain reason per score rule, in SCORE_RULES order
REASONS: dict[tuple[str, str], str] = {
    ("crew_size_rank", "== 0"): "one-person crew",
    ("crew_size_rank", "== 1"): "crew of 2-5",
    ("had_redo_60d", "== 1"): "re-measure in last 60 days",
    ("accuracy_tickets_30d", ">= 1"): "measurement complaint this month",
    ("late_invoices_90d", ">= 1"): "late invoice in last 90 days",
    ("login_trend", "<= -0.3"): "logins down a third or more",
    ("logins_30d", "== 0"): "no logins this month",
    ("tenure_months", "< 3"): "first three months",
}

COLUMNS = ["account_id", "company_name", "region", "crew_size", "plan", "mrr_usd", "tenure_months",
           "health_score", "model_risk", "flagged_by_score", "flagged_by_model", "reasons"]


def _reasons(snaps: pd.DataFrame) -> pd.Series:
    fired = [snaps.eval(f"`{col}` {rule}").map({True: REASONS[(col, rule)], False: ""})
             for col, rule, _ in SCORE_RULES]
    return pd.concat(fired, axis=1).apply(lambda r: "; ".join(x for x in r if x), axis=1)


def _riskiest(risk: pd.Series, share: float = RISK_SHARE) -> pd.Series:
    """True for the riskiest `share` of rows; ties broken by row order (the list is sorted by account id)."""
    return risk.rank(pct=True, method="first") > 1 - share


def at_risk_list(world: dict[str, pd.DataFrame] | None = None, snaps: pd.DataFrame | None = None) -> pd.DataFrame:
    w = world if world is not None else world_as_of(HISTORY_END)
    snaps = build_snapshots(w) if snaps is None else snaps
    train = snaps[~snaps.account_id.map(is_test_account)]
    model = fit_model(train)

    now = build_snapshots(w, dates=[AS_OF]).drop(columns="churned_60d").sort_values("account_id")
    now = now.reset_index(drop=True)
    now["health_score"] = health_score(now)
    now["model_risk"] = model.predict_proba(now[FEATURES])[:, 1].round(3)
    now["flagged_by_score"] = _riskiest(100 - now.health_score)
    now["flagged_by_model"] = _riskiest(now.model_risk)
    now["reasons"] = _reasons(now)

    changes = w["subscription_changes"]
    plan = (changes[changes.changed_at < AS_OF].sort_values("changed_at")
            .groupby("subscription_id").plan_after.last().rename("plan"))
    now = now.join(plan, on="subscription_id")
    now = now.merge(w["accounts"][["account_id", "company_name", "region", "crew_size"]], on="account_id")
    return (now[COLUMNS].sort_values(["health_score", "model_risk", "account_id"], ascending=[True, False, True])
            .reset_index(drop=True))
