"""The month-by-month comparison, and that every governed metric has a check. No warehouse needed."""
from pathlib import Path

import yaml

from metric_glossary.checks import CHECKS
from metric_glossary.reconcile import compare

METRICS_YML = Path(__file__).resolve().parents[2] / "dbt" / "models" / "semantic" / "_metrics.yml"


def test_every_governed_metric_has_exactly_one_check():
    names = {m["name"] for m in yaml.safe_load(METRICS_YML.read_text())["metrics"]}
    assert set(CHECKS) == names
    assert len(names) == 27


def test_every_check_returns_month_and_value():
    for name, check in CHECKS.items():
        sql = check.sql.lower()
        assert " as month" in sql and " as value" in sql, name
        assert check.source in check.sql, name


def test_every_governed_metric_has_a_description():
    for m in yaml.safe_load(METRICS_YML.read_text())["metrics"]:
        assert m.get("description", "").strip(), m["name"]


def test_matching_months_pass_and_float_noise_is_ignored():
    r = compare("x", {"2026-01-01": 10.0, "2026-02-01": 0.1 + 0.2}, {"2026-01-01": 10.0, "2026-02-01": 0.3})
    assert r.ok and r.months == 2 and r.mismatches == []


def test_a_month_that_differs_is_reported_with_both_values():
    r = compare("x", {"2026-01-01": 10.0, "2026-02-01": 12.0}, {"2026-01-01": 10.0, "2026-02-01": 12.5})
    assert not r.ok
    assert r.mismatches == [("2026-02-01", 12.0, 12.5)]


def test_a_month_missing_on_one_side_fails_unless_the_other_side_is_empty_or_zero():
    # the check sees January activity the governed metric does not
    assert not compare("x", {"2026-02-01": 5.0}, {"2026-01-01": 3.0, "2026-02-01": 5.0}).ok
    # zero or null on the side that has the month is fine (e.g. a month with no spend)
    assert compare("x", {"2026-02-01": 5.0}, {"2026-01-01": 0.0, "2026-02-01": 5.0}).ok
    assert compare("x", {"2026-01-01": None, "2026-02-01": 5.0}, {"2026-02-01": 5.0}).ok
    # a ratio with no denominator is null on both sides
    assert compare("x", {"2026-01-01": None}, {"2026-01-01": None}).ok
    assert not compare("x", {"2026-01-01": None}, {"2026-01-01": 0.5}).ok


def test_no_months_at_all_is_not_a_pass():
    assert not compare("x", {}, {}).ok


def test_latest_value_is_the_last_full_month():
    r = compare("x", {"2026-09-01": 1.0, "2026-10-01": 2.0, "2026-11-01": 0.4},
                {"2026-09-01": 1.0, "2026-10-01": 2.0, "2026-11-01": 0.4}, current_month="2026-11-01")
    assert (r.latest_month, r.latest_value) == ("2026-10-01", 2.0)
    # ratios whose recent months are not known yet (nulls) fall back to the last month with a value
    r = compare("x", {"2025-10-01": 0.7, "2025-11-01": None}, {"2025-10-01": 0.7, "2025-11-01": None},
                current_month="2026-11-01")
    assert (r.latest_month, r.latest_value) == ("2025-10-01", 0.7)
