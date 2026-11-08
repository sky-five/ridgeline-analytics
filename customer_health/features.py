"""Monthly snapshots of every live subscription with the signals a customer-success team can see.

A snapshot at date T uses only rows timestamped before T (no status columns, which the app overwrites
later), and labels the account as churned if its subscription is cancelled in the next 60 days.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipelines.engine import world_as_of

HISTORY_END = date(2026, 6, 30)
HORIZON_DAYS = 60
WINDOW_DAYS = 30
# the three ticket subjects about a wrong measurement, the most common cancel reason in the history
ACCURACY_SUBJECTS = ("Report missing a facet", "Pitch on report is wrong", "Squares don't match my tape")
LATE_PAY_DAYS = 7

FEATURES = [
    "logins_30d", "login_trend", "measurements_30d", "proposals_30d", "jobs_30d",
    "tickets_30d", "accuracy_tickets_30d", "redos_30d", "had_redo_60d", "late_invoices_90d", "tenure_months",
    "is_scale_plan", "crew_size_rank",
]
CREW_RANK = {"1": 0, "2-5": 1, "6-15": 2, "16+": 3}


def snapshot_dates(first: date = date(2024, 7, 1), end: date = HISTORY_END) -> list[pd.Timestamp]:
    """First of each month whose churn window ends inside the history."""
    last = pd.Timestamp(end) - pd.Timedelta(days=HORIZON_DAYS)
    return list(pd.date_range(pd.Timestamp(first), last, freq="MS"))


def _live_at(changes: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Subscriptions whose last change before t is not a cancel, with their plan and MRR then."""
    before = changes[changes.changed_at < t].sort_values("changed_at")
    last = before.groupby("subscription_id").tail(1)
    first = before.groupby("subscription_id").changed_at.min().rename("first_start")
    live = last[last.change_type != "cancel"].join(first, on="subscription_id")
    return live[["subscription_id", "account_id", "plan_after", "mrr_after", "first_start"]]


def _count(df: pd.DataFrame, col: str, start: pd.Timestamp, end: pd.Timestamp, name: str) -> pd.Series:
    rows = df[(df[col] >= start) & (df[col] < end)]
    return rows.groupby("account_id").size().rename(name)


def build_snapshots(world: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    w = world if world is not None else world_as_of(HISTORY_END)
    changes = w["subscription_changes"]
    events, tickets, orders, invoices = w["events"], w["support_tickets"], w["measurement_orders"], w["invoices"]
    cancels = changes[changes.change_type == "cancel"]
    logins = events[events.event_type == "login"]
    usage = {k: events[events.event_type == k] for k in ("measurement_ordered", "proposal_sent", "job_created")}
    accuracy = tickets[tickets.subject.isin(ACCURACY_SUBJECTS)]
    inv = invoices.assign(late_at=invoices.issued_at + pd.Timedelta(days=LATE_PAY_DAYS))
    # an invoice counts as late once it is 7 days old and was not paid by then
    inv = inv[inv.paid_at.isna() | (inv.paid_at > inv.late_at)]

    crew = w["accounts"].set_index("account_id").crew_size.map(CREW_RANK).rename("crew_size_rank")
    out = []
    win = pd.Timedelta(days=WINDOW_DAYS)
    for t in snapshot_dates():
        live = _live_at(changes, t).set_index("account_id")
        s = pd.DataFrame(index=live.index)
        s["snapshot"] = t
        s["subscription_id"] = live.subscription_id
        s["mrr_usd"] = live.mrr_after
        s["is_scale_plan"] = (live.plan_after == "scale").astype(int)
        s["tenure_months"] = ((t - live.first_start).dt.days / 30.44).round(1)
        s = s.join(_count(logins, "occurred_at", t - win, t, "logins_30d"))
        s = s.join(_count(logins, "occurred_at", t - 2 * win, t - win, "logins_prev_30d"))
        s = s.join(_count(usage["measurement_ordered"], "occurred_at", t - win, t, "measurements_30d"))
        s = s.join(_count(usage["proposal_sent"], "occurred_at", t - win, t, "proposals_30d"))
        s = s.join(_count(usage["job_created"], "occurred_at", t - win, t, "jobs_30d"))
        s = s.join(_count(tickets, "created_at", t - win, t, "tickets_30d"))
        s = s.join(_count(accuracy, "created_at", t - win, t, "accuracy_tickets_30d"))
        s = s.join(_count(orders, "redo_requested_at", t - win, t, "redos_30d"))
        s = s.join(_count(orders, "redo_requested_at", t - 2 * win, t, "redos_60d"))
        s = s.join(_count(inv, "late_at", t - 3 * win, t, "late_invoices_90d"))
        s = s.join(crew)
        horizon = cancels[(cancels.changed_at >= t) & (cancels.changed_at < t + pd.Timedelta(days=HORIZON_DAYS))]
        s["churned_60d"] = s.subscription_id.isin(horizon.subscription_id).astype(int)
        out.append(s)

    snaps = pd.concat(out).reset_index()
    counts = [c for c in snaps.columns if c.endswith("_30d") or c.endswith("_90d")]
    snaps[counts] = snaps[counts].fillna(0).astype(int)
    snaps["had_redo_60d"] = (snaps.pop("redos_60d") > 0).astype(int)
    # change in logins vs the month before, from -1 (stopped logging in) to +1; 0 when both months are empty
    prev = snaps.pop("logins_prev_30d")
    tot = snaps.logins_30d + prev
    snaps["login_trend"] = np.where(tot > 0, (snaps.logins_30d - prev) / tot.where(tot > 0, 1), 0.0)
    return snaps
