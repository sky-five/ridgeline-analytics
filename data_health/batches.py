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
