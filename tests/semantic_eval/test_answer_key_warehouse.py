"""The answer key against a built warehouse: questions resolve, closed periods hold, and spot checks
agree with the marts. Run scripts/run_all.py first. Marked `warehouse`."""
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from semantic_eval.answer_key import KEY, build, load_questions

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


@pytest.fixture(scope="module")
def fresh():
    return build()


def sql(q):
    with duckdb.connect(str(DB)) as c:  # same config as MetricFlow's in-process connection
        return c.sql(q).fetchall()[0][0]


def test_every_question_resolves_against_the_semantic_layer(fresh):
    assert set(fresh["answers"]) == {q["id"] for q in load_questions()}


def test_closed_periods_match_the_committed_key(fresh):
    # The simulator's history does not change with the as-of date, so answers about periods that ended
    # well before the data's last day must not move between nightly builds.
    committed = json.loads(KEY.read_text(encoding="utf-8"))["answers"]
    cutoff = date.fromisoformat(fresh["as_of"]) - timedelta(days=30)
    closed = [q for q in load_questions() if q.get("period_end") and q["period_end"] <= cutoff]
    assert len(closed) >= 15
    for q in closed:
        want, got = committed[q["id"]], fresh["answers"][q["id"]]
        assert got == (want if isinstance(want, str) else pytest.approx(want)), q["id"]


def test_spot_checks_against_the_marts(fresh):
    a = fresh["answers"]
    assert a["mrr_end_sep_2026"] == pytest.approx(sql("select mrr from fct_mrr_daily where date_day = '2026-09-30'"))
    assert a["signups_2025"] == sql("select count(*) from fct_account_funnel where year(signup_at) = 2025")
    assert a["leads_2025"] == sql("select count(*) from fct_contractor_leads where year(created_at) = 2025")
    assert a["churned_mrr_2025"] == pytest.approx(
        -sql("select sum(churned_mrr) from fct_mrr_daily where year(date_day) = 2025"))



def test_eval_truth_matches_the_answer_key(fresh, tmp_path):
    """The eval computes truth through the read-only path; it must agree with semantic.query. Runs in another
    process on a copy: this process already holds the warehouse's write lock through dbt-duckdb."""
    import os
    import shutil
    import subprocess
    import sys

    copy = tmp_path / DB.name
    shutil.copy(DB, copy)

    code = ("import json; from semantic_eval.answer_key import load_questions; from semantic_eval.run import truth; "
            "print(json.dumps({q['id']: truth(q) for q in load_questions()}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                         env={**os.environ, "RIDGELINE_DUCKDB_PATH": str(copy)}).stdout
    assert json.loads(out.strip().splitlines()[-1]) == fresh["answers"]
