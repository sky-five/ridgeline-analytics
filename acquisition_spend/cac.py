"""Channel CAC over signups whose 60-day outcome is known.

CAC here = ad spend in the window / signups from that window that paid within 60 days. Spend and signups use
the same calendar window, the way a monthly budget review would. Channels with no spend (referral, organic)
show a CAC of 0 and are kept, because they still bring paying accounts into the blended number.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

OUTCOME_DAYS = 60


@dataclass(frozen=True)
class Window:
    start: pd.Timestamp  # first signup day, inclusive
    end: pd.Timestamp  # last signup day, inclusive

    @classmethod
    def last_mature_months(cls, as_of: pd.Timestamp, months: int) -> Window:
        """The last `months` whole calendar months in which every signup is at least 60 days old."""
        last_mature = pd.Timestamp(as_of).normalize() - pd.Timedelta(days=OUTCOME_DAYS)
        end = (last_mature + pd.Timedelta(days=1)).to_period("M").start_time - pd.Timedelta(days=1)
        start = (end.to_period("M") - (months - 1)).start_time
        return cls(start, end)

    def label(self) -> str:
        return f"{self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}"


def in_window(df: pd.DataFrame, col: str, w: Window) -> pd.DataFrame:
    return df[(df[col] >= w.start) & (df[col] <= w.end)]


def channel_cac(signups: pd.DataFrame, spend: pd.DataFrame, w: Window) -> pd.DataFrame:
    """One row per channel plus a 'paid channels' and an 'all channels' row."""
    s = in_window(signups, "signup_date", w)
    if not s.is_mature.all():
        raise ValueError(f"window {w.label()} has signups whose 60-day outcome is not known yet")
    sp = in_window(spend, "date_day", w).groupby("channel").spend_usd.sum()
    g = s.groupby("channel").agg(signups=("account_id", "size"), paid_60d=("is_paid_60d", "sum"))
    g["spend_usd"] = sp.reindex(g.index).fillna(0.0)

    paid_channels = g[g.spend_usd > 0]
    rows = [g, pd.DataFrame([paid_channels.sum(numeric_only=True)], index=["paid channels"]),
            pd.DataFrame([g.sum(numeric_only=True)], index=["all channels"])]
    out = pd.concat(rows)
    out.index.name = "channel"
    out["signups"] = out.signups.astype(int)
    out["paid_60d"] = out.paid_60d.astype(int)
    out["conversion"] = out.paid_60d / out.signups
    out["cost_per_signup"] = out.spend_usd / out.signups
    out["cac_usd"] = out.spend_usd / out.paid_60d.where(out.paid_60d > 0)
    order = sorted(g.index, key=lambda c: (g.spend_usd[c] == 0, out.cac_usd[c]))
    return out.loc[order + ["paid channels", "all channels"]].reset_index()
