"""Every governed metric agrees with its independent check on the built warehouse, and the check has teeth.

Needs a built warehouse: run scripts/run_all.py first. Marked `warehouse`. Lives next to test_metrics.py: like
it, it opens MetricFlow's connection, which must come after the tests that open the warehouse read-only.
"""
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "warehouse" / "ridgeline.duckdb"
pytestmark = [pytest.mark.warehouse, pytest.mark.skipif(not DB.exists(), reason="build the warehouse first")]


def test_all_27_governed_metrics_reconcile_month_by_month():
    from metric_glossary.reconcile import reconcile

    results = reconcile(DB)
    assert len(results) == 27
    assert {r.name: r.mismatches[:3] for r in results if not r.ok} == {}
    assert min(r.months for r in results) >= 30  # history starts 2024-01


def test_a_wrong_definition_is_caught(monkeypatch):
    # a check that forgets reactivations no longer matches net new MRR in the months that had one
    from metric_glossary import checks
    from metric_glossary.reconcile import check_by_month, compare, governed_by_month

    broken = replace(checks.CHECKS["net_new_mrr"], sql=checks.CHECKS["net_new_mrr"].sql.replace(", 'reactivation'", ""))
    monkeypatch.setitem(checks.CHECKS, "net_new_mrr", broken)
    with duckdb.connect(str(DB)) as con:
        got = check_by_month(con, "net_new_mrr", "2026-01-01")
    r = compare("net_new_mrr", governed_by_month(["net_new_mrr"])["net_new_mrr"], got)
    assert len(r.mismatches) >= 10


def test_glossary_table_is_exported_for_the_site():
    from scripts.export_reporting import export

    export(DB)
    with duckdb.connect(str(DB)) as con:
        rows = con.sql("select name, reconciled, version, months_compared, description, check_sql "
                       "from reporting.metric_glossary").fetchall()
    assert len(rows) == 27
    assert all(ok and v >= 1 and n >= 30 and desc and "select" in sql for _, ok, v, n, desc, sql in rows)
