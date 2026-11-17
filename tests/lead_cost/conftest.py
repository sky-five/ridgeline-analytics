"""One simulated world and one built lead-cost warehouse for every test module (simulate + load + dbt build,
about 15 s)."""
import pytest

from lead_cost.load import dbt_build, load
from lead_cost.simulate import simulate


@pytest.fixture(scope="session")
def world():
    return simulate()


@pytest.fixture(scope="session")
def lead_db(tmp_path_factory, world):
    path = tmp_path_factory.mktemp("lead_cost") / "lead_cost.duckdb"
    load(path, world.deliveries)
    dbt_build(path)
    return path
