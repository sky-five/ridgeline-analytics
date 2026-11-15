"""One built warehouse for every enrolment-planning test module (load + dbt build, about 10 s)."""
import pytest

from enrolment_planning.load import dbt_build, load


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("enrolment") / "enrolment.duckdb"
    load(path)
    dbt_build(path)
    return path
