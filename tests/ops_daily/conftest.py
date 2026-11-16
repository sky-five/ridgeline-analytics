"""One simulated operation and one built ops-daily warehouse for every test module (simulate + load + dbt build,
about 10 s)."""
import pytest

from ops_daily.load import dbt_build, load
from ops_daily.simulate import simulate


@pytest.fixture(scope="session")
def operation():
    return simulate()


@pytest.fixture(scope="session")
def ops_db(tmp_path_factory, operation):
    path = tmp_path_factory.mktemp("ops") / "ops.duckdb"
    load(path, operation)
    dbt_build(path)
    return path
