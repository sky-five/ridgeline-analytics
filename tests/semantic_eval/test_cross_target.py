import json

import pytest

from semantic_eval import cross_target as ct
from semantic_eval.answer_key import KEY


def snap(target, answers, as_of="2026-11-02"):
    return {"target": target, "as_of": as_of, "answers": answers}


def test_same_tolerates_fixed_point_rounding_only():
    assert ct.same(0.31311475409836065, 0.313115)          # Snowflake's 6-decimal division
    assert ct.same(882.8132443531828, 882.813244)
    assert ct.same(243419.0, 243419)
    assert not ct.same(0.3131, 0.3132)
    assert not ct.same(243419.0, 243420.0)


def test_same_text_is_exact():
    assert ct.same("lt_5m", "lt_5m")
    assert not ct.same("lt_5m", "LT_5M")
    assert not ct.same("2026-06", 2026.06)


def test_same_missing_answer_never_matches_a_value():
    assert not ct.same(None, 1.0)
    assert ct.same(None, None)


def test_compare_counts_matches_and_names_the_diff():
    left = snap("snowflake", {"a": 1.0, "b": "x", "c": 0.5})
    right = snap("duckdb", {"a": 1.0000000001, "b": "x", "c": 0.6})
    report = ct.compare(left, right)
    assert report["targets"] == ["snowflake", "duckdb"]
    assert (report["matched"], report["total"]) == (2, 3)
    assert [r["id"] for r in report["rows"] if not r["match"]] == ["c"]
    assert report["max_abs_diff"] == pytest.approx(0.1)
    assert not ct.ok(report)


def test_question_missing_on_one_side_is_a_diff():
    report = ct.compare(snap("snowflake", {"a": 1.0}), snap("duckdb", {"a": 1.0, "b": 2.0}))
    assert (report["matched"], report["total"]) == (1, 2)


def test_different_as_of_dates_fail_even_when_answers_match():
    report = ct.compare(snap("snowflake", {"a": 1.0}, "2026-11-01"), snap("duckdb", {"a": 1.0}))
    assert report["matched"] == 1 and not report["same_as_of"]
    assert not ct.ok(report)


def test_committed_key_against_itself_is_25_of_25():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    report = ct.compare(snap("snowflake", key["answers"]), snap("duckdb", key["answers"]))
    assert ct.ok(report) and report["matched"] == report["total"] == 25
    text = ct.markdown(report)
    assert "25 / 25 match" in text and "DIFF" not in text


def test_compare_cli_exit_code(tmp_path, monkeypatch):
    key = json.loads(KEY.read_text(encoding="utf-8"))
    path = tmp_path / "sf.json"
    path.write_text(json.dumps(snap("snowflake", key["answers"])))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(ct, "snapshot", lambda: snap("duckdb", dict(key["answers"])))
    assert ct.main(["compare", str(path), "--out", str(tmp_path / "r.json")]) == 0
    assert json.loads((tmp_path / "r.json").read_text())["matched"] == 25

    changed = dict(key["answers"], cac_2025=900.0)
    monkeypatch.setattr(ct, "snapshot", lambda: snap("duckdb", changed))
    assert ct.main(["compare", str(path)]) == 1


def test_target_defaults_to_duckdb(monkeypatch):
    monkeypatch.delenv("RIDGELINE_DBT_TARGET", raising=False)
    assert ct.target() == "duckdb"
    monkeypatch.setenv("RIDGELINE_DBT_TARGET", "snowflake")
    assert ct.target() == "snowflake"


def test_recorded_snowflake_run_matches_duckdb():
    path = KEY.parent / "results" / "governed-snowflake-vs-duckdb-2026-11-03.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["targets"] == ["snowflake", "duckdb"]
    assert ct.ok(report) and report["matched"] == report["total"] == 25
    assert report["run"].startswith("https://github.com/sky-five/ridgeline-analytics/actions/runs/")
