import pytest


@pytest.fixture(autouse=True, scope="module")
def _release_warehouse():
    """Close the analyst's read-only connection so later tests can open the warehouse read-write."""
    yield
    from analyst import tools

    tools.close()
