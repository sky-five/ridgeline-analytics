"""dlt sources: one per simulated system, one incremental resource per table."""
from datetime import datetime

import dlt
from dlt.sources import DltResource

from simulator.api import MockApi
from simulator.world import TABLES

SCHEMA_CONTRACT = {"tables": "evolve", "columns": "evolve", "data_type": "freeze"}
EPOCH = datetime(1970, 1, 1)


def _table_resource(api: MockApi, table: str) -> DltResource:
    spec = TABLES[table]

    @dlt.resource(
        name=table,
        primary_key=spec.primary_key,
        # merge on the primary key for every table, logs included: a reload after lost state
        # (renamed pipeline, wiped state) then overwrites instead of duplicating
        write_disposition="merge",
        schema_contract=SCHEMA_CONTRACT,
    )
    def rows(updated_at=dlt.sources.incremental("updated_at", initial_value=EPOCH)):  # noqa: B008 (dlt idiom)
        last = updated_at.last_value
        since = None if last is None or last == EPOCH else datetime.fromisoformat(str(last)).replace(tzinfo=None)
        yield from api.fetch_arrow(table, updated_since=since)

    return rows


def ridgeline_source(system: str, api: MockApi):
    tables = [name for name, spec in TABLES.items() if spec.system == system]

    @dlt.source(name=f"ridgeline_{system}")
    def source():
        return [_table_resource(api, t) for t in tables]

    return source()


SYSTEMS = sorted({spec.system for spec in TABLES.values()})
