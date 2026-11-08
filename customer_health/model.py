"""A hand-weighted health score and a logistic-regression churn model, compared on held-out accounts.

The score is the kind a customer-success team writes down: start at 100 and take points off for each
warning sign. The weights were set by hand before looking at any held-out results and are not fitted.
The model sees the same snapshot columns (FEATURES) and learns its own weights on the training accounts.
"""
from __future__ import annotations

import json
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from customer_health.features import FEATURES, HORIZON_DAYS, build_snapshots

RESULTS = Path(__file__).resolve().parent / "results" / "summary.json"
TEST_SHARE = 0.3
RISK_SHARE = 0.2  # the "at risk" list is the worst-scored 20% of live accounts

# (column, rule, points off). Plain enough to read out in a meeting.
SCORE_RULES: list[tuple[str, str, int]] = [
    ("crew_size_rank", "== 0", 20),            # one-person crew
    ("crew_size_rank", "== 1", 10),            # crew of 2-5
    ("had_redo_60d", "== 1", 15),              # asked for a re-measure in the last 60 days
    ("accuracy_tickets_30d", ">= 1", 10),      # complained about a measurement this month
    ("late_invoices_90d", ">= 1", 10),         # paid an invoice more than 7 days late
    ("login_trend", "<= -0.3", 10),            # logins fell by a third or more vs the month before
    ("logins_30d", "== 0", 15),                # nobody logged in this month
    ("tenure_months", "< 3", 5),               # still in the first three months
]


def health_score(snaps: pd.DataFrame) -> pd.Series:
    """0-100, higher is healthier."""
    score = pd.Series(100, index=snaps.index)
    for col, rule, points in SCORE_RULES:
        score -= np.where(snaps.eval(f"`{col}` {rule}"), points, 0)
    return score.clip(0, 100).rename("health_score")


def is_test_account(account_id: str) -> bool:
    """Stable split by account, so one account's snapshots never sit on both sides."""
    return zlib.crc32(account_id.encode()) % 100 < TEST_SHARE * 100


def fit_model(train: pd.DataFrame):
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    return model.fit(train[FEATURES], train.churned_60d)


def churn_in_riskiest(risk: pd.Series, churned: pd.Series, share: float = RISK_SHARE) -> tuple[float, float]:
    """Churn rate among the riskiest `share` of rows (by snapshot), and the share of all churners caught there."""
    df = pd.DataFrame({"risk": risk, "churned": churned})
    # rank inside each snapshot month: the list a team would work from that month
    rank = df.groupby(level="snapshot").risk.rank(pct=True, method="first")
    top = df[rank > 1 - share]
    return float(top.churned.mean()), float(top.churned.sum() / df.churned.sum())


@dataclass
class Summary:
    snapshots: int
    snapshot_months: int
    accounts: int
    test_accounts: int
    horizon_days: int
    churn_rate: float
    auc_health_score: float
    auc_model: float
    riskiest_share: float
    churn_in_riskiest_score: float
    churn_in_riskiest_model: float
    churners_caught_score: float
    churners_caught_model: float
    model_weights: dict[str, float]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def evaluate(snaps: pd.DataFrame | None = None) -> Summary:
    snaps = build_snapshots() if snaps is None else snaps
    snaps = snaps.set_index(["snapshot", "account_id"]).sort_index()
    test_mask = snaps.index.get_level_values("account_id").map(is_test_account).to_numpy(bool)
    train, test = snaps[~test_mask], snaps[test_mask]
    model = fit_model(train)
    risk_model = pd.Series(model.predict_proba(test[FEATURES])[:, 1], index=test.index)
    risk_score = 100 - health_score(test)
    top_s, caught_s = churn_in_riskiest(risk_score, test.churned_60d)
    top_m, caught_m = churn_in_riskiest(risk_model, test.churned_60d)
    coefs = model[-1].coef_[0]
    r = lambda x: round(float(x), 3)  # noqa: E731
    return Summary(
        snapshots=len(snaps),
        snapshot_months=snaps.index.get_level_values("snapshot").nunique(),
        accounts=snaps.index.get_level_values("account_id").nunique(),
        test_accounts=test.index.get_level_values("account_id").nunique(),
        horizon_days=HORIZON_DAYS,
        churn_rate=r(snaps.churned_60d.mean()),
        auc_health_score=r(roc_auc_score(test.churned_60d, risk_score)),
        auc_model=r(roc_auc_score(test.churned_60d, risk_model)),
        riskiest_share=RISK_SHARE,
        churn_in_riskiest_score=r(top_s),
        churn_in_riskiest_model=r(top_m),
        churners_caught_score=r(caught_s),
        churners_caught_model=r(caught_m),
        model_weights={f: r(c) for f, c in sorted(zip(FEATURES, coefs, strict=True), key=lambda x: -abs(x[1]))},
    )
