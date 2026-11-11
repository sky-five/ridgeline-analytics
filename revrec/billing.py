"""Subscription billing for the revenue-recognition demo, read from saas-world-sim's billing pack.

The engine simulates one fixed, seeded billing history to 2027-12-31 and `billing_as_of(date)` cuts it at the
end of a date, so the same date always gives the same rows and an earlier date is a prefix of a later one.
This module turns that cut into the two row lists the SQL models and the Python reference read:

- ``subscription_changes``: the contract side. Every time a subscription's MRR changes
  (new, upgrade, seat change, churn, cancel with refund) there is one row with the new MRR from that date.
- ``invoice_lines``: the billing side. Each line covers a service period [period_start, period_end)
  and is one of: ``subscription`` (the period's charge, billed in advance), ``proration``
  (a mid-period upgrade, charged for the rest of the period) or ``credit`` (a refund for the
  rest of the period when a customer cancels immediately).

ARR comes from the contract side, revenue from the billing side, as in a real finance stack.
``Billing`` and ``Subscription`` are kept so tests can write small hand-calculated cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from pipelines.engine import BILLING_PLANS as PLANS
from pipelines.engine import BILLING_TABLES, add_months, billing_as_of, prorate

__all__ = ["AS_OF", "PLANS", "Billing", "Subscription", "add_months", "from_engine", "prorate", "yesterday"]

# The snapshot the README numbers and the tests are pinned to. The CLI and CI use yesterday instead.
AS_OF = date(2026, 9, 30)


def yesterday() -> date:
    """The last full simulated day, the same date the nightly build uses."""
    return datetime.now(UTC).date() - timedelta(days=1)


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


@dataclass
class Billing:
    subscription_changes: list[dict] = field(default_factory=list)
    invoice_lines: list[dict] = field(default_factory=list)

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
        n = len(self.invoice_lines) + 1
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


def _rows(df) -> list[dict]:
    ints = [c for c in df.columns if c.endswith("_cents")]
    return [{k: int(v) if k in ints else v for k, v in row.items()} for row in df.to_dict("records")]


def from_engine(as_of: date = AS_OF, seed: int | None = None, customers: int | None = None) -> Billing:
    """Billing as an export would show it at the end of ``as_of``.

    ``seed`` picks another seeded history (default: the engine's seed). ``customers`` keeps only the
    first N customer ids, for small, fast test cases.
    """
    tables = billing_as_of(as_of) if seed is None else billing_as_of(as_of, seed=seed)
    if customers is not None:
        keep = {f"cus_{c:04d}" for c in range(1, customers + 1)}
        tables = {n: df[df["customer_id"].isin(keep)] for n, df in tables.items()}
    return Billing(**{name: _rows(tables[name][cols]) for name, cols in BILLING_TABLES.items()})
