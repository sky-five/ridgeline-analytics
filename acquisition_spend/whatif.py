"""Spend what-if on lead-score deciles.

Each channel brings a different mix of signups across the ten lead-score deciles, and each decile converts at
its own rate whatever channel it came from. So a dollar on a channel buys:

    signups per dollar  x  sum over deciles (share of the channel's signups in the decile x decile paid rate)

Moving budget between paid channels changes expected paid accounts by that per-dollar yield. The model is
linear on purpose: it assumes cost per signup and the decile mix hold at the new spend. Real channels saturate,
so the what-if is for moves of a modest size, and the back-test below says how well it held on later months.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from acquisition_spend.cac import Window, in_window

DECILES = range(1, 11)


@dataclass(frozen=True)
class Yield:
    """What one window says each paid channel buys per dollar."""
    decile_rate: pd.Series  # decile -> share paid within 60 days, all channels pooled
    mix: pd.DataFrame  # channel x decile -> share of the channel's signups
    signups_per_usd: pd.Series  # paid channels only
    paid_per_signup: pd.Series  # expected, from mix x decile_rate

    @property
    def paid_per_1k(self) -> pd.Series:
        return (1000 * self.signups_per_usd * self.paid_per_signup.reindex(self.signups_per_usd.index)).rename(
            "paid_per_1k_usd")

    def top_decile_cost(self, top: int = 3) -> pd.Series:
        """Spend per signup landing in the top `top` deciles, by paid channel."""
        share = self.mix[[d for d in DECILES if d > 10 - top]].sum(axis=1)
        return (1 / (self.signups_per_usd * share.reindex(self.signups_per_usd.index))).rename(
            f"cost_per_top{top}_decile_signup")


def fit(signups: pd.DataFrame, spend: pd.DataFrame, w: Window) -> Yield:
    s = in_window(signups, "signup_date", w)
    if not s.is_mature.all():
        raise ValueError(f"window {w.label()} has signups whose 60-day outcome is not known yet")
    rate = s.groupby("decile").is_paid_60d.mean().reindex(DECILES)
    if rate.isna().any():
        raise ValueError(f"deciles with no signups in {w.label()}: {list(rate[rate.isna()].index)}")
    mix = pd.crosstab(s.channel, s.decile, normalize="index").reindex(columns=DECILES, fill_value=0.0)
    usd = in_window(spend, "date_day", w).groupby("channel").spend_usd.sum()
    usd = usd[usd > 0]
    n = s.channel.value_counts().reindex(usd.index)
    return Yield(rate, mix, (n / usd).rename("signups_per_usd"), (mix @ rate).rename("paid_per_signup"))


def predict_paid(y: Yield, budget: pd.Series) -> pd.Series:
    """Expected paid accounts (60-day) from a spend per paid channel."""
    unknown = set(budget.index) - set(y.signups_per_usd.index)
    if unknown:
        raise ValueError(f"no spend history for {sorted(unknown)}")
    return (budget * y.paid_per_1k.reindex(budget.index) / 1000).rename("expected_paid")


def move(y: Yield, budget: pd.Series, src: str, dst: str, usd: float) -> dict[str, float]:
    """Move `usd` from src to dst; return expected paid accounts and CAC before and after."""
    if usd > budget.get(src, 0):
        raise ValueError(f"cannot move ${usd:,.0f} out of {src}: its budget is ${budget.get(src, 0):,.0f}")
    after = budget.copy()
    after[src] -= usd
    after[dst] = after.get(dst, 0) + usd
    before_paid, after_paid = predict_paid(y, budget).sum(), predict_paid(y, after).sum()
    total = float(budget.sum())
    return {"src": src, "dst": dst, "moved_usd": float(usd), "budget_usd": total,
            "paid_before": float(before_paid), "paid_after": float(after_paid),
            "paid_change": float(after_paid - before_paid),
            "cac_before": total / before_paid, "cac_after": total / after_paid}


def all_moves(y: Yield, budget: pd.Series, share: float = 0.10) -> pd.DataFrame:
    """Every pairwise move of `share` of the source channel's budget, best first."""
    rows = [move(y, budget, a, b, share * budget[a]) for a in budget.index for b in budget.index if a != b]
    return pd.DataFrame(rows).sort_values("paid_change", ascending=False, ignore_index=True)


def backtest(signups: pd.DataFrame, spend: pd.DataFrame, fit_window: Window, test_window: Window) -> pd.DataFrame:
    """Fit on one window, then predict each paid channel's paid accounts on a later window from its spend alone."""
    if test_window.start <= fit_window.end:
        raise ValueError("the test window must start after the fit window ends")
    y = fit(signups, spend, fit_window)
    test_spend = in_window(spend, "date_day", test_window).groupby("channel").spend_usd.sum()
    test_spend = test_spend.reindex(y.signups_per_usd.index).fillna(0.0)
    s = in_window(signups, "signup_date", test_window)
    if not s.is_mature.all():
        raise ValueError(f"window {test_window.label()} has signups whose 60-day outcome is not known yet")
    actual = s.groupby("channel").is_paid_60d.sum().reindex(test_spend.index).fillna(0).astype(int)
    out = pd.DataFrame({"spend_usd": test_spend, "predicted_paid": predict_paid(y, test_spend), "actual_paid": actual})
    out.loc["paid channels"] = out.sum()
    out["error"] = out.predicted_paid - out.actual_paid
    out.index.name = "channel"
    return out.reset_index()
