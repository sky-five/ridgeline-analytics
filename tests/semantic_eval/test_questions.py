import json
from datetime import date

import pytest

from semantic_eval.answer_key import KEY, load_questions, pick_answer, validate

QUESTIONS = load_questions()


def test_question_set_is_valid():
    assert len(QUESTIONS) == 25
    assert validate(QUESTIONS) == []


def test_covers_every_business_area():
    assert {q["category"] for q in QUESTIONS} == {
        "revenue", "retention", "funnel", "acquisition", "contractor_outcomes", "operations"}


def test_committed_key_answers_every_question():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    assert set(key["answers"]) == {q["id"] for q in QUESTIONS}
    for q in QUESTIONS:
        a = key["answers"][q["id"]]
        assert isinstance(a, str) if q["type"] == "text" else isinstance(a, float), q["id"]
        if q["type"] == "ratio":
            assert 0 <= a <= 1, q["id"]


def test_validate_catches_bad_questions():
    bad = [
        {"id": "a", "question": "?", "category": "x", "metric": "mrr", "type": "count", "trap": "t"},
        {"id": "a", "question": "?", "category": "x", "metric": "mrr", "type": "number", "trap": "t",
         "answer": "top", "by": "account__channel", "pick": {"metric_time__year": "2025"}, "colour": 1},
        {"id": "b", "question": "?", "category": "x", "metric": "nope", "type": "number", "trap": ""},
    ]
    errors = "\n".join(validate(bad, {"mrr": ("metric_time__day",)}))
    for expected in ["a: type must be", "a: duplicate id", "unknown fields ['colour']", "`by` must be",
                     "a top/bottom answer is a text answer", "picks on metric_time__year", "b: missing trap",
                     "no governed metric 'nope'"]:
        assert expected in errors


def test_validate_checks_dimensions_against_metric():
    q = {"id": "a", "question": "?", "category": "x", "metric": "mrr", "type": "number", "trap": "t",
         "group_by": ["metric_time__year", "account__channel"]}
    assert validate([q], {"mrr": ("metric_time__day",)}) == ["a: mrr has no dimension account__channel"]


ROWS = [
    {"metric_time__year": "2024-01-01", "account__channel": "referral", "m": 0.30},
    {"metric_time__year": "2025-01-01", "account__channel": "referral", "m": 0.25},
    {"metric_time__year": "2025-01-01", "account__channel": "facebook", "m": 0.05},
    {"metric_time__year": "2025-01-01", "account__channel": "organic", "m": None},
]


def test_pick_value_after_filtering():
    q = {"id": "q", "metric": "m", "pick": {"metric_time__year": "2024"}}
    assert pick_answer(q, ROWS) == 0.30


def test_pick_value_needs_exactly_one_row():
    with pytest.raises(ValueError, match="expected one row"):
        pick_answer({"id": "q", "metric": "m", "pick": {"metric_time__year": "2025"}}, ROWS)


def test_pick_top_and_bottom_ignore_missing_values():
    q = {"id": "q", "metric": "m", "pick": {"metric_time__year": "2025"}, "by": "account__channel"}
    assert pick_answer({**q, "answer": "top"}, ROWS) == "referral"
    assert pick_answer({**q, "answer": "bottom"}, ROWS) == "facebook"


def test_pick_absolute_and_month_labels():
    rows = [{"metric_time__month": date(2026, 4, 1), "m": -10.0}, {"metric_time__month": date(2026, 5, 1), "m": 30.0}]
    assert pick_answer({"id": "q", "metric": "m", "answer": "top", "by": "metric_time__month"}, rows) == "2026-05"
    assert pick_answer({"id": "q", "metric": "m", "absolute": True, "pick": {"metric_time__month": "2026-04"}},
                       rows) == 10.0
