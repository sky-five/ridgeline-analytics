"""One simulated book and one built margin warehouse for every margin-risk test module (simulate + load + dbt
build, about 10 s)."""
import pytest

from margin_risk.load import dbt_build, load
from margin_risk.simulate import simulate


@pytest.fixture(scope="session")
def book():
    return simulate()


@pytest.fixture(scope="session")
def db(tmp_path_factory, book):
    path = tmp_path_factory.mktemp("margin") / "margin.duckdb"
    load(path, book)
    dbt_build(path)
    return path
