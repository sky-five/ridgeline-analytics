"""Synthetic, Stripe-shaped subscription billing for the revenue-recognition demo.

Two outputs, both deterministic for a given seed:

- ``subscription_changes``: the contract side. Every time a subscription's MRR changes
  (start, upgrade, seat change, churn) there is one row with the new MRR from that date.
- ``invoice_lines``: the billing side. Each line covers a service period [period_start, period_end)
  and is one of: ``subscription`` (the period's charge, billed in advance), ``proration``
  (a mid-period upgrade, charged for the rest of the period) or ``credit`` (a refund for the
  rest of the period when a customer cancels immediately).

ARR comes from the contract side, revenue from the billing side, as in a real finance stack.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

START = date(2025, 1, 1)
AS_OF = date(2026, 9, 30)

# Monthly list price per seat, in cents. Annual plans cost 10 months up front.
PLANS = {"starter": 1_500, "team": 4_000, "business": 9_000}
PLAN_ORDER = ["starter", "team", "business"]


def add_months(d: date, months: int) -> date:
    """Same day-of-month ``months`` later, clamped to the month's last day."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def prorate(amount_cents: int, used_from: date, period_start: date, period_end: date) -> int:
    """Share of ``amount_cents`` for [used_from, period_end), rounded half away from zero."""
    total = (period_end - period_start).days
    remaining = (period_end - used_from).days
    q, r = divmod(abs(amount_cents) * remaining, total)
    q += 1 if 2 * r >= total else 0
    return q if amount_cents >= 0 else -q


@dataclass
class Subscription:
    subscription_id: str
    customer_id: str
    plan: str
    seats: int
    interval: str  # "month" or "year"

    @property
    def mrr_cents(self) -> int:
        return PLANS[self.plan] * self.seats

    @property
    def period_price_cents(self) -> int:
        return self.mrr_cents if self.interval == "month" else self.mrr_cents * 10


@dataclass
class Billing:
    subscription_changes: list[dict] = field(default_factory=list)
    invoice_lines: list[dict] = field(default_factory=list)
    _invoice_seq: int = 0

    def change(self, sub: Subscription, on: date, mrr_cents: int, reason: str) -> None:
        self.subscription_changes.append(
            {
                "subscription_id": sub.subscription_id,
                "customer_id": sub.customer_id,
                "effective_on": on,
                "mrr_cents": mrr_cents,
                "reason": reason,
            }
        )

    def line(self, sub: Subscription, kind: str, issued_on: date, start: date, end: date, amount: int) -> None:
        self._invoice_seq += 1
        n = self._invoice_seq
        self.invoice_lines.append(
            {
                "line_id": f"il_{n:06d}",
                "invoice_id": f"in_{n:06d}",
                "customer_id": sub.customer_id,
                "subscription_id": sub.subscription_id,
                "kind": kind,
                "issued_on": issued_on,
                "period_start": start,
                "period_end": end,
                "amount_cents": amount,
            }
        )


def _run_subscription(b: Billing, rng: random.Random, sub: Subscription, start: date, as_of: date) -> date | None:
    """Simulate one subscription from ``start``. Returns the date it ended, or None if still live."""
    b.change(sub, start, sub.mrr_cents, "new")
    months = 1 if sub.interval == "month" else 12
    period_start = start
    while period_start <= as_of:
        period_end = add_months(period_start, months)
        b.line(sub, "subscription", period_start, period_start, period_end, sub.period_price_cents)

        # At most one mid-period event: an upgrade (prorated charge) or an immediate cancel (prorated refund).
        days = (period_end - period_start).days
        mid = period_start + timedelta(days=rng.randrange(1, days))
        roll = rng.random()
        upgrade_p = 0.03 * months ** 0.5
        cancel_p = 0.01 * months ** 0.5
        if roll < upgrade_p and sub.plan != "business" and mid <= as_of:
            old_price = sub.period_price_cents
            sub.plan = PLAN_ORDER[PLAN_ORDER.index(sub.plan) + 1]
            b.change(sub, mid, sub.mrr_cents, "upgrade")
            b.line(sub, "proration", mid, mid, period_end, prorate(sub.period_price_cents - old_price, mid,
                                                                  period_start, period_end))
        elif roll < upgrade_p + cancel_p and mid <= as_of:
            b.change(sub, mid, 0, "cancel_refund")
            b.line(sub, "credit", mid, mid, period_end, prorate(-sub.period_price_cents, mid,
                                                               period_start, period_end))
            return mid

        # At renewal: churn, change seats, or renew unchanged.
        if period_end > as_of:
            return None
        churn_p = 0.035 if months == 1 else 0.18
        roll = rng.random()
        if roll < churn_p:
            b.change(sub, period_end, 0, "churn")
            return period_end
        if roll < churn_p + 0.10:
            new_seats = max(1, sub.seats + rng.choice([-2, -1, 1, 1, 2, 3]))
            if new_seats != sub.seats:
                reason = "seats_up" if new_seats > sub.seats else "seats_down"
                sub.seats = new_seats
                b.change(sub, period_end, sub.mrr_cents, reason)
        period_start = period_end
    return None


def generate(n_customers: int = 400, seed: int = 7, start: date = START, as_of: date = AS_OF) -> Billing:
    """Customers sign up evenly over [start, as_of]; some who churn come back later on a new subscription."""
    rng = random.Random(seed)
    b = Billing()
    span = (as_of - start).days
    for c in range(1, n_customers + 1):
        customer_id = f"cus_{c:04d}"
        signup = start + timedelta(days=rng.randrange(span + 1))
        n_sub = 0
        while signup is not None and signup <= as_of:
            n_sub += 1
            sub = Subscription(
                subscription_id=f"sub_{c:04d}_{n_sub}",
                customer_id=customer_id,
                plan=rng.choices(PLAN_ORDER, weights=[6, 3, 1])[0],
                seats=rng.randint(1, 12),
                interval="year" if rng.random() < 0.3 else "month",
            )
            ended = _run_subscription(b, rng, sub, signup, as_of)
            signup = ended + timedelta(days=rng.randint(30, 200)) if ended and rng.random() < 0.15 else None

    b.invoice_lines = [ln for ln in b.invoice_lines if ln["issued_on"] <= as_of]
    b.subscription_changes = [c for c in b.subscription_changes if c["effective_on"] <= as_of]
    return b
