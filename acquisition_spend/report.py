"""Build the committed results from the warehouse: channel CAC, the per-dollar yield, every 10% budget move,
and the back-test. Fixed windows keep the numbers stable when the warehouse is built on 2026-06-30."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from acquisition_spend import whatif
from acquisition_spend.cac import Window, channel_cac, in_window

RESULTS = Path(__file__).parent / "results"
CAC_MONTHS = 12
MOVE_SHARE = 0.10


def windows(as_of: pd.Timestamp) -> dict[str, Window]:
    """The CAC window is the last 12 mature months; the back-test fits on its first 8 and tests on the last 4."""
    cac = Window.last_mature_months(as_of, CAC_MONTHS)
    split = (cac.start.to_period("M") + 8).start_time
    return {"cac": cac, "fit": Window(cac.start, split - pd.Timedelta(days=1)), "test": Window(split, cac.end)}


def build(signups: pd.DataFrame, spend: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, str]:
    """File name -> contents."""
    w = windows(as_of)
    cac = channel_cac(signups, spend, w["cac"])
    y = whatif.fit(signups, spend, w["cac"])
    monthly = in_window(spend, "date_day", w["cac"]).groupby("channel").spend_usd.sum()
    budget = (monthly[monthly > 0] / CAC_MONTHS).round(0)
    yld = pd.concat([budget.rename("monthly_budget_usd"), y.paid_per_signup, y.paid_per_1k, y.top_decile_cost()],
                    axis=1).loc[budget.index].sort_values("paid_per_1k_usd", ascending=False)
    yld.index.name = "channel"
    moves = whatif.all_moves(y, budget, MOVE_SHARE)
    bt = whatif.backtest(signups, spend, w["fit"], w["test"])
    total = bt.iloc[-1]
    summary = {
        "as_of": f"{as_of:%Y-%m-%d}",
        "windows": {k: v.label() for k, v in w.items()},
        "blended_cac_usd": round(float(cac.set_index("channel").cac_usd["all channels"]), 2),
        "paid_channel_cac_usd": round(float(cac.set_index("channel").cac_usd["paid channels"]), 2),
        "decile_paid_rate": {int(d): round(float(r), 4) for d, r in y.decile_rate.items()},
        "monthly_budget_usd": float(budget.sum()),
        "best_move": _round(moves.iloc[0].to_dict()),
        "worst_move": _round(moves.iloc[-1].to_dict()),
        "backtest_paid_channels": {"predicted": round(float(total.predicted_paid), 1),
                                   "actual": int(total.actual_paid),
                                   "error_pct": round(100 * float(total.error / total.actual_paid), 1)},
    }
    return {
        "channel_cac.csv": cac.round(4).to_csv(index=False),
        "channel_yield.csv": yld.round(4).reset_index().to_csv(index=False),
        "budget_moves.csv": moves.round(4).to_csv(index=False),
        "backtest.csv": bt.round(4).to_csv(index=False),
        "summary.json": json.dumps(summary, indent=2) + "\n",
    }


def _round(d: dict) -> dict:
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
