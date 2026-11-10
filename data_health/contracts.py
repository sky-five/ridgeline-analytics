"""The contract for product events, written down as data, and a checker that returns every broken rule.

A batch is the set of events that arrived for one day. The checker never raises: it returns one row per
(rule, event) that failed, so a caller can print them, count them or fail a build on them.
"""
from dataclasses import dataclass

import pandas as pd

COLUMNS = {  # column -> pandas dtype kind ("O"/"T" = text, "M" = timestamp, "f" = float)
    "event_id": "text",
    "account_id": "text",
    "event_type": "text",
    "occurred_at": "timestamp",
    "value_usd": "float",
    "updated_at": "timestamp",
}
REQUIRED = ["event_id", "account_id", "event_type", "occurred_at", "updated_at"]
EVENT_ID_PATTERN = r"EVT-\d{6}-\d{6}"
ACCOUNT_ID_PATTERN = r"ACC-\d{6}"


@dataclass(frozen=True)
class EventType:
    has_value: bool  # value_usd must be set (and in range) when True, and empty when False
    min_value: float = 0.0
    max_value: float = 0.0


EVENT_TYPES = {
    "login": EventType(has_value=False),
    "measurement_ordered": EventType(has_value=False),
    "job_created": EventType(has_value=False),
    "invoice_paid": EventType(has_value=False),
    "proposal_sent": EventType(has_value=True, min_value=100.0, max_value=250_000.0),
    "proposal_signed": EventType(has_value=True, min_value=100.0, max_value=250_000.0),
}

RULES = {
    "schema.missing_column": "every contract column is present",
    "schema.extra_column": "no column outside the contract",
    "schema.type": "each column has its contract type",
    "required": "event_id, account_id, event_type, occurred_at and updated_at are never empty",
    "event_id.format": "event_id looks like EVT-<6 digits>-<6 digits>",
    "event_id.unique": "event_id is unique in the batch and not already loaded",
    "event_id.account": "the account number inside event_id matches account_id",
    "account_id.format": "account_id looks like ACC-<6 digits>",
    "account_id.known": "account_id is an account that exists",
    "event_type.allowed": "event_type is one of the six known types",
    "value_usd.present": "proposal events carry a value",
    "value_usd.absent": "other events carry no value",
    "value_usd.range": "proposal values are whole dollars between $100 and $250,000",
    "occurred_at.after_signup": "no event before the account signed up",
    "occurred_at.in_batch_day": "the event happened on the batch day, not later",
    "updated_at.equals_occurred_at": "events are append-only: updated_at equals occurred_at",
}


def _kind(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "timestamp"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        return "text"
    return str(series.dtype)


def check_batch(batch: pd.DataFrame, accounts: pd.DataFrame, day: str | None,
                loaded_ids: pd.Series | None = None) -> pd.DataFrame:
    """Every broken rule in one day's batch of events, as rows of (rule, event_id, detail).

    accounts needs account_id and signup_at. loaded_ids are event_ids already in the warehouse. day=None
    checks a whole history at once and skips the batch-day rule.
    """
    out = []

    def fail(rule, mask, detail):
        rows = batch.loc[mask]
        ids = rows["event_id"] if "event_id" in rows else pd.Series([None] * len(rows), index=rows.index)
        details = detail(rows) if callable(detail) else [detail] * len(rows)
        out.append(pd.DataFrame({"rule": rule, "event_id": ids.to_numpy(), "detail": list(details)}))

    missing = [c for c in COLUMNS if c not in batch]
    for c in missing:
        out.append(pd.DataFrame({"rule": ["schema.missing_column"], "event_id": [None], "detail": [c]}))
    for c in batch.columns.difference(list(COLUMNS)):
        out.append(pd.DataFrame({"rule": ["schema.extra_column"], "event_id": [None], "detail": [c]}))
    typed = {}
    for c, kind in COLUMNS.items():
        if c in batch:
            got = _kind(batch[c])
            if got != kind:
                out.append(pd.DataFrame({"rule": ["schema.type"], "event_id": [None],
                                         "detail": [f"{c} is {got}, expected {kind}"]}))
            else:
                typed[c] = batch[c]
    if missing or len(typed) < len(COLUMNS):  # row rules need the full, typed schema
        return _frame(out)

    for c in REQUIRED:
        fail("required", batch[c].isna(), f"{c} is empty")
    eid, acc, typ, ts, val = (batch[c] for c in ["event_id", "account_id", "event_type", "occurred_at",
                                                    "value_usd"])
    fail("event_id.format", eid.notna() & ~eid.fillna("").str.fullmatch(EVENT_ID_PATTERN), lambda r: r.event_id)
    seen = loaded_ids if loaded_ids is not None else pd.Series([], dtype=object)
    fail("event_id.unique", eid.notna() & (eid.duplicated(keep="first") | eid.isin(seen)), "duplicate event_id")
    ok_ids = eid.fillna("").str.fullmatch(EVENT_ID_PATTERN) & acc.fillna("").str.fullmatch(ACCOUNT_ID_PATTERN)
    fail("event_id.account", ok_ids & (eid.str[4:10] != acc.str[4:]), lambda r: r.account_id)
    fail("account_id.format", acc.notna() & ~acc.fillna("").str.fullmatch(ACCOUNT_ID_PATTERN),
         lambda r: r.account_id)
    signup = acc.map(accounts.set_index("account_id")["signup_at"])
    fail("account_id.known", acc.notna() & signup.isna(), lambda r: r.account_id)
    fail("event_type.allowed", typ.notna() & ~typ.isin(list(EVENT_TYPES)), lambda r: r.event_type)

    wants_value = typ.map({k: t.has_value for k, t in EVENT_TYPES.items()})
    fail("value_usd.present", (wants_value == True) & val.isna(), lambda r: r.event_type)  # noqa: E712
    fail("value_usd.absent", (wants_value == False) & val.notna(), lambda r: r.event_type)  # noqa: E712
    lo = typ.map({k: t.min_value for k, t in EVENT_TYPES.items()})
    hi = typ.map({k: t.max_value for k, t in EVENT_TYPES.items()})
    bad_range = (wants_value == True) & val.notna() & ((val < lo) | (val > hi) | (val % 1 != 0))  # noqa: E712
    fail("value_usd.range", bad_range, lambda r: [f"{v:g}" for v in r.value_usd])

    fail("occurred_at.after_signup", ts.notna() & signup.notna() & (ts < signup), lambda r: r.occurred_at.astype(str))
    if day is not None:
        start = pd.Timestamp(day)
        fail("occurred_at.in_batch_day", ts.notna() & ((ts < start) | (ts >= start + pd.Timedelta(days=1))),
             lambda r: r.occurred_at.astype(str))
    fail("updated_at.equals_occurred_at", ts.notna() & batch.updated_at.notna() & (batch.updated_at != ts),
         lambda r: r.updated_at.astype(str))
    return _frame(out)


def _frame(parts) -> pd.DataFrame:
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame({"rule": pd.Series(dtype=object), "event_id": pd.Series(dtype=object),
                             "detail": pd.Series(dtype=object)})
    return pd.concat(parts, ignore_index=True)


def summary(violations: pd.DataFrame) -> pd.DataFrame:
    """One row per rule: how many events broke it (0 for rules that held)."""
    counts = violations["rule"].value_counts()
    return pd.DataFrame({"rule": list(RULES), "meaning": list(RULES.values()),
                         "failed": [int(counts.get(r, 0)) for r in RULES]})
