"""Cut the simulated history into daily batches, and break a clean batch on purpose."""
import pandas as pd

from pipelines.engine import world_as_of


def day_batch(world: dict, day: str) -> tuple[pd.DataFrame, pd.Series]:
    """The events that happened on `day`, and the event_ids loaded before it."""
    ev = world["events"]
    start = pd.Timestamp(day)
    in_day = (ev.occurred_at >= start) & (ev.occurred_at < start + pd.Timedelta(days=1))
    return ev.loc[in_day].reset_index(drop=True), ev.loc[ev.occurred_at < start, "event_id"]


def load_day(day: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    world = world_as_of(day)
    batch, loaded = day_batch(world, day)
    return batch, world["accounts"], loaded


def _first(batch, event_type):
    return batch.index[batch.event_type == event_type][0]


# Each fault takes a clean batch and returns a broken copy plus the rule that must catch it.
def _unknown_type(b):
    b.loc[0, "event_type"] = "page_view"
    return b


def _missing_account(b):
    b.loc[0, "account_id"] = None
    return b


def _orphan_account(b):
    b.loc[0, "account_id"] = "ACC-999999"
    b.loc[0, "event_id"] = "EVT-999999" + b.loc[0, "event_id"][10:]
    return b


def _duplicate_id(b):
    b.loc[1, "event_id"] = b.loc[0, "event_id"]
    return b


def _replayed_batch(b):  # caught against loaded ids, see FAULTS
    return b


def _bad_id(b):
    b.loc[0, "event_id"] = "evt_1"
    return b


def _swapped_account(b):
    other = b.account_id[b.account_id != b.loc[0, "account_id"]].iloc[0]
    b.loc[0, "account_id"] = other
    return b


def _proposal_without_value(b):
    b.loc[_first(b, "proposal_sent"), "value_usd"] = float("nan")
    return b


def _value_on_login(b):
    b.loc[_first(b, "login"), "value_usd"] = 1.0
    return b


def _value_in_cents(b):
    i = _first(b, "proposal_sent")
    b.loc[i, "value_usd"] = b.loc[i, "value_usd"] * 100
    return b


def _negative_value(b):
    i = _first(b, "proposal_sent")
    b.loc[i, "value_usd"] = -b.loc[i, "value_usd"]
    return b


def _tomorrow(b):
    b.loc[0, ["occurred_at", "updated_at"]] = b.loc[0, "occurred_at"] + pd.Timedelta(days=1)
    return b


def _before_signup(b, accounts):
    signup = accounts.set_index("account_id").signup_at
    i = b.index[b.account_id.map(signup) > b.occurred_at.min().normalize()][0]
    b.loc[i, ["occurred_at", "updated_at"]] = b.occurred_at.min().normalize()
    return b


def _edited_later(b):
    b.loc[0, "updated_at"] = b.loc[0, "updated_at"] + pd.Timedelta(hours=3)
    return b


def _dropped_column(b):
    return b.drop(columns="value_usd")


def _extra_column(b):
    b["session_id"] = "s"
    return b


def _value_as_text(b):
    b["value_usd"] = b["value_usd"].astype(str)
    return b


def _epoch_seconds(b):
    b["occurred_at"] = b["occurred_at"].astype("int64") // 10**6
    return b


FAULTS = {  # name -> (break the batch, rule that must catch it)
    "unknown_event_type": (_unknown_type, "event_type.allowed"),
    "missing_account_id": (_missing_account, "required"),
    "orphan_account": (_orphan_account, "account_id.known"),
    "duplicate_event_id": (_duplicate_id, "event_id.unique"),
    "replayed_batch": (_replayed_batch, "event_id.unique"),
    "malformed_event_id": (_bad_id, "event_id.format"),
    "event_on_wrong_account": (_swapped_account, "event_id.account"),
    "proposal_without_value": (_proposal_without_value, "value_usd.present"),
    "value_on_login": (_value_on_login, "value_usd.absent"),
    "value_in_cents": (_value_in_cents, "value_usd.range"),
    "negative_value": (_negative_value, "value_usd.range"),
    "event_from_tomorrow": (_tomorrow, "occurred_at.in_batch_day"),
    "event_before_signup": (_before_signup, "occurred_at.after_signup"),
    "edited_after_the_fact": (_edited_later, "updated_at.equals_occurred_at"),
    "dropped_column": (_dropped_column, "schema.missing_column"),
    "extra_column": (_extra_column, "schema.extra_column"),
    "value_as_text": (_value_as_text, "schema.type"),
    "timestamp_as_epoch": (_epoch_seconds, "schema.type"),
}


def inject(fault: str, batch: pd.DataFrame, accounts: pd.DataFrame, loaded: pd.Series):
    """A broken copy of the batch and the loaded ids to check it against."""
    breaker, _ = FAULTS[fault]
    b = batch.copy()
    b = breaker(b, accounts) if fault == "event_before_signup" else breaker(b)
    if fault == "replayed_batch":
        loaded = pd.concat([loaded, batch.event_id.head(5)])
    return b, loaded


def arrivals(day: str, days_before: int) -> dict[str, pd.DataFrame]:
    """Every table's daily batches from `days_before` days before `day` up to `day`, stacked.

    A batch is what an incremental load picks up that day: the rows whose updated_at falls on it, as they
    were then. A row changed on three days shows up in three batches, so counts and empty values per day
    are what the loader saw, not what the latest version of the table says.
    """
    from pipelines.engine import TABLES

    end = pd.Timestamp(day)
    parts: dict[str, list[pd.DataFrame]] = {name: [] for name in TABLES}
    for d in pd.date_range(end - pd.Timedelta(days=days_before), end, freq="D"):
        world = world_as_of(str(d.date()))
        for name, spec in TABLES.items():
            df = world[name]
            on_day = df[df.updated_at.dt.floor("D") == d]
            parts[name].append(on_day.drop(columns=[c for c in spec.internal_cols if c in df]))
    return {name: pd.concat(p, ignore_index=True) for name, p in parts.items()}


# Table faults for the health scorecard: each takes one table's stacked batches and the day, and returns a
# broken copy. Unlike the contract faults above, these leave every row valid; what breaks is the shape of
# the day: it is late, short, doubled or half empty.
def _stuck_loader(df, day):  # nothing has arrived for the last four days
    return df[df.updated_at < pd.Timestamp(day) - pd.Timedelta(days=3)]


def _half_batch(df, day):  # half of the day's rows never arrived
    today = df.updated_at.dt.floor("D") == pd.Timestamp(day)
    drop = df.index[today][::2]
    return df.drop(index=drop)


def _empty_batch(df, day):  # the day's load ran and brought nothing
    return df[df.updated_at.dt.floor("D") != pd.Timestamp(day)]


def _double_load(df, day):  # the day's batch was appended twice
    today = df[df.updated_at.dt.floor("D") == pd.Timestamp(day)]
    return pd.concat([df, today], ignore_index=True)


def _account_id_dropped(df, day):  # an upstream change stops filling account_id on a fifth of the day's rows
    if "account_id" not in df:
        raise ValueError("this table has no account_id column")
    df = df.copy()
    today = df.index[df.updated_at.dt.floor("D") == pd.Timestamp(day)]
    df.loc[today[::5], "account_id"] = None
    return df


TABLE_FAULTS = {  # name -> (break the table, check that must turn red)
    "stuck_loader": (_stuck_loader, "freshness"),
    "half_batch": (_half_batch, "volume"),
    "empty_batch": (_empty_batch, "volume"),
    "double_load": (_double_load, "volume"),
    "account_id_dropped": (_account_id_dropped, "null_rate"),
}


def inject_table(fault: str, tables: dict[str, pd.DataFrame], table: str, day: str) -> dict[str, pd.DataFrame]:
    """A copy of the stacked batches with one table broken by `fault` on `day`."""
    breaker, _ = TABLE_FAULTS[fault]
    return {**tables, table: breaker(tables[table], day)}
