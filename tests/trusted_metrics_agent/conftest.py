import pytest

from trusted_metrics_agent.load import dbt_build, load


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    """The HR warehouse, built once for the folder's tests (load + dbt build, about 8 seconds)."""
    path = tmp_path_factory.mktemp("hr") / "trusted_metrics.duckdb"
    load(path)
    dbt_build(path)
    return path
