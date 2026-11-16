"""One simulated book and one built book-health warehouse for every test module (simulate + load + dbt build,
about 15 s)."""
import pytest

from book_health.load import dbt_build, load
from book_health.simulate import simulate


@pytest.fixture(scope="session")
def book():
    return simulate()


@pytest.fixture(scope="session")
def db(tmp_path_factory, book):
    path = tmp_path_factory.mktemp("book") / "book.duckdb"
    load(path, book)
    dbt_build(path)
    return path
