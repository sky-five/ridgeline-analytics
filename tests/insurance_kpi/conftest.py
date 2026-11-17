import duckdb
import pytest

from insurance_kpi.profile import load
from insurance_kpi.simulate import simulate


@pytest.fixture(scope="package")
def book():
    return simulate()


@pytest.fixture(scope="package")
def con(book):
    c = duckdb.connect()
    load(c, book)
    yield c
    c.close()
