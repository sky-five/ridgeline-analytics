"""On a built warehouse: the call list matches the score mart, and every template note passes the checker."""
from pathlib import Path

import duckdb
import pytest

from outbound_notes import check, draft, leads

pytestmark = [pytest.mark.warehouse,
              pytest.mark.skipif(not Path(leads.warehouse_path()).exists(), reason="build the warehouse first")]


@pytest.fixture(scope="module")
def data():
    return leads.load()


def test_leads_are_the_top_decile_call_list(data):
    df, _ = data
    with duckdb.connect(str(leads.warehouse_path()), read_only=True) as con:
        n, low = con.sql("select count(*), min(score_model) from fct_pqa_scores "
                         "where decile = 10 and call_list_eligible").fetchone()
        below = con.sql("select max(score_model) from fct_pqa_scores where decile < 10").fetchone()[0]
    assert len(df) == n > 0 and df.account_id.is_unique
    assert df.score_model.is_monotonic_decreasing and df.score_model.min() == low >= below


def test_every_template_note_passes_and_quotes_its_own_numbers(data):
    df, as_of = data
    for _, row in df.iterrows():
        f = leads.facts(row, as_of)
        assert 14 <= f["days_since_signup"] <= 45
        r = check.check(draft.template(f), f)
        assert r.ok, (f["account_id"], r.problems)
        assert r.numbers >= 3
