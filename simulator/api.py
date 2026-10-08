"""A fake SaaS API over the simulated world: paginated, with an `updated_at` cursor."""
import json
from collections.abc import Iterator
from datetime import date, datetime

import numpy as np
import pandas as pd

from simulator.config import SEED
from simulator.world import TABLES, world_as_of


def _to_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for c in out.select_dtypes("datetime").columns:
        out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%S").where(out[c].notna(), None)
    out = out.astype(object).where(out.notna(), None)
    records = out.to_dict("records")
    for r in records:  # numpy scalars -> plain Python, so json.dumps works
        for k, v in r.items():
            if isinstance(v, np.generic):
                r[k] = v.item()
    return records


class MockApi:
    def __init__(self, as_of: date, seed: int = SEED):
        self.as_of = as_of
        self._world = world_as_of(as_of, seed)

    def fetch(self, table: str, updated_since: datetime | None = None,
              page_size: int = 5000) -> Iterator[list[dict]]:
        spec = TABLES[table]  # KeyError for unknown tables
        df = self._world[table]
        if updated_since is not None:
            df = df[df.updated_at > pd.Timestamp(updated_since)]
        df = df.sort_values(["updated_at", spec.primary_key], kind="stable")
        if table == "events":
            df = df.assign(properties=[json.loads(json.dumps({"value_usd": v})) if pd.notna(v) else {}
                                       for v in df.value_usd]).drop(columns="value_usd")
        for start in range(0, len(df), page_size):
            yield _to_records(df.iloc[start:start + page_size])
