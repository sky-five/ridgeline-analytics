"""The tables behind the "Raw tables vs governed metrics" page, from the committed runs. No warehouse, no model."""
import json
import re
from pathlib import Path

import pytest

from semantic_eval.report import FORM_ONLY, fmt_answer, load_runs, run_label, tables

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "reports" / "pages" / "raw-vs-governed.md"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"


@pytest.fixture(scope="module")
def t():
    return tables()


def test_every_recorded_run_is_on_the_page(t):
    files = sorted(p.name for p in (ROOT / "semantic_eval" / "results").glob("raw-vs-governed*.json"))
    assert sorted(t["eval_scores"]["file"].unique()) == files
    # the Snowflake parity file has another shape and stays off this page
    assert not any("snowflake" in f for f in files)


def test_scores_are_the_recorded_summaries(t):
    for run in load_runs():
        rows = t["eval_scores"][t["eval_scores"]["file"] == run["file"]].set_index("arm")
        for arm, s in run["summary"]["arms"].items():
            assert rows.loc[arm, "correct"] == s["correct"]
            assert rows.loc[arm, "total"] == s["total"] == 25
        cats = t["eval_categories"][t["eval_categories"]["run"] == run_label(run)]
        assert cats.groupby("arm")["correct"].sum().to_dict() == {
            arm: s["correct"] for arm, s in run["summary"]["arms"].items()}


def test_the_numbers_quoted_in_the_readme(t):
    # semantic_eval/README.md quotes these; the page must show the same
    got = {(r.model, r.arm): (r.correct, r.correct_on_substance) for r in t["eval_scores"].itertuples()}
    assert got == {
        ("claude-sonnet-5-5", "raw"): (17, 19), ("claude-sonnet-5-5", "governed"): (25, 25),
        ("gemini-3.5-flash-lite", "raw"): (12, 14), ("gemini-3.5-flash-lite", "governed"): (24, 24),
    }


def test_failure_examples_match_the_recorded_outcomes(t):
    q = t["eval_questions"]
    for run in load_runs():
        mine = q[q["run"] == run_label(run)]
        assert len(mine) == 25 and list(mine["n"]) == list(range(1, 26))
        assert sorted(mine.loc[mine["outcome"] == "only governed right", "id"]) == sorted(
            run["summary"]["only_governed_right"])
        # the page says no question was right only on raw tables
        assert run["summary"]["only_raw_right"] == []
        assert (mine["outcome"] == "only raw right").sum() == 0
    failures = q[q["outcome"] == "only governed right"]
    assert len(failures) == 8 + 12
    assert (failures["trap"] != "").all() and (failures["governed_query"] != "").all()


def test_form_only_notes_sit_on_real_raw_misses(t):
    q = t["eval_questions"].merge(t["eval_scores"][["run", "model"]].drop_duplicates(), on="run")
    noted = q[q["form_only_note"] != ""]
    assert {(r.model, r.id) for r in noted.itertuples()} == set(FORM_ONLY)
    assert not noted["raw_correct"].any() and noted["governed_correct"].all()


def test_cap_hits_show_as_no_answer(t):
    q = t["eval_questions"]
    capped = q[q["raw_error"] != ""]
    assert len(capped) == 3
    assert (capped["raw_answer"] == "no answer").all()


@pytest.mark.parametrize("value,kind,unit,want", [
    (243419.0, "number", "usd", "$243,419"),
    (882.8132, "number", "usd", "$883"),
    (12.5, "number", "usd", "$12.50"),
    (0.3131, "ratio", "ratio", "31.3%"),
    (0.0559, "ratio", "count", "5.6%"),
    (3762, "ratio", "count", "3,762"),
    (552.0, "number", "count", "552"),
    (4.25, "number", "minutes", "4.2 min"),
    ("lt_5m", "text", "text", "lt_5m"),
    (None, "ratio", "ratio", "no answer"),
])
def test_fmt_answer(value, kind, unit, want):
    assert fmt_answer(value, kind, unit) == want


def test_other_result_shapes_are_skipped(tmp_path):
    (tmp_path / "raw-vs-governed-parity.json").write_text(json.dumps({"pairs": []}))
    assert tables(tmp_path) == {}


def test_page_reads_only_exported_tables_and_columns(t):
    page = PAGE.read_text(encoding="utf-8")
    used = set(re.findall(r"ridgeline\.(\w+)", page))
    assert used == {"eval_scores", "eval_categories", "eval_questions"} <= set(t)
    for name in used:
        assert (SOURCES / f"{name}.sql").read_text().strip().startswith(f"select * from reporting.{name}")
    fields = set(re.findall(r"\{(?:#if )?f\.(\w+)\}?", page))
    assert fields and fields <= set(t["eval_questions"].columns)
    lift_cols = {"run_order", "arm", "run", "model", "ran_on", "as_of", "correct", "total", "accuracy",
                 "correct_on_substance", "errors", "median_tool_calls"}
    assert lift_cols <= set(t["eval_scores"].columns)
