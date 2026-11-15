"""One simulated world and one built warehouse for every ED test module (the build takes about 10 s)."""
import pytest

from ed_wait_times.load import dbt_build, load
from ed_wait_times.simulate import simulate


@pytest.fixture(scope="session")
def world():
    return simulate()


@pytest.fixture(scope="session")
def db(tmp_path_factory, world):
    path = tmp_path_factory.mktemp("ed") / "ed.duckdb"
    load(path, world)
    dbt_build(path)
    return path
