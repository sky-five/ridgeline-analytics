"""The PQA Python model must run on Snowflake too, where dbt.ref() returns a Snowpark DataFrame
(`.to_pandas()`, UPPERCASE column names) instead of a DuckDB relation (`.df()`)."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODEL = Path(__file__).resolve().parents[2] / "dbt" / "models" / "marts" / "sales" / "fct_pqa_scores.py"


def _load_model():
    spec = importlib.util.spec_from_file_location("fct_pqa_scores", MODEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _funnel(n=400) -> pd.DataFrame:
    r = np.random.default_rng(0)
    wk1 = r.random(n) < 0.3
    return pd.DataFrame({
        "account_id": [f"A{i}" for i in range(n)],
        "signup_at": pd.to_datetime("2025-01-01") + pd.to_timedelta(r.integers(0, 600, n), unit="D"),
        "channel": r.choice(["google_ads", "referral", "facebook"], n),
        "crew_size": r.choice(["1", "2-5", "6-15"], n),
        "is_paid_60d": wk1 & (r.random(n) < 0.6) | (r.random(n) < 0.05),
        "is_mature": True,
        "proposal_wk1": wk1,
        "measurements_14d": r.integers(0, 5, n),
        "proposals_14d": r.integers(0, 3, n),
        "signed_14d": r.integers(0, 2, n),
        "logins_14d": r.integers(0, 9, n),
        "active_days_14d": r.integers(0, 9, n),
        "first_paid_at": pd.NaT,
    })


class _SnowparkFrame:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df.rename(columns=str.upper)


class _Config:
    def __call__(self, **kwargs):
        pass

    def get(self, key):
        return {"as_of_date": "2026-10-07"}[key]


class _FakeDbt:
    config = _Config()

    def __init__(self, frame):
        self._frame = frame

    def ref(self, name):
        assert name == "fct_account_funnel"
        return self._frame


def test_runs_on_snowpark_style_ref():
    out = _load_model().model(_FakeDbt(_SnowparkFrame(_funnel())), session=None)
    assert len(out) == 400
    assert out.columns.str.lower().tolist() == out.columns.tolist() or out.columns.str.isupper().all()
    assert {"score_model", "score_points", "decile"} <= set(out.columns.str.lower())
