"""The eval scorer: tolerances, percent vs fraction, text, sets, unanswerable, grounding; and answer parsing."""
import pytest

from analyst.evals.score import correct, grounded
from analyst.prompt import parse_answer


@pytest.mark.parametrize("qtype,answer,truth,ok", [
    ("number", 243712, 243700.0, True),
    ("number", "$243,712.40", 243700.0, True),
    ("number", 250000, 243700.0, False),
    ("number", 12.4, 12.0, False),
    ("ratio", 0.391, 0.39, True),
    ("ratio", 39.1, 0.39, True),
    ("ratio", "39.1%", 0.39, True),
    ("ratio", 0.40, 0.39, False),
    ("text", "referral", "referral", True),
    ("text", "Supplier partner", "supplier_partner", True),
    ("text", "facebook", "referral", False),
    ("set", ["app_db.subscriptions", "app_db.accounts"], ["app_db.accounts", "app_db.subscriptions"], True),
    ("set", "app_db.subscriptions, app_db.accounts", ["app_db.accounts", "app_db.subscriptions"], True),
    ("set", ["app_db.subscriptions"], ["app_db.accounts", "app_db.subscriptions"], False),
    ("unanswerable", None, None, True),
    ("unanswerable", "not available in the warehouse", None, True),
    ("unanswerable", 42, None, False),
    ("number", None, 10.0, False),
])
def test_correct(qtype, answer, truth, ok):
    assert correct(qtype, answer, truth) is ok


def test_custom_tolerance():
    assert correct("number", 101.5, 100.0, tolerance=0.02)
    assert not correct("number", 103, 100.0, tolerance=0.02)


def test_grounded():
    assert grounded(["fct_mrr_daily", "fct_mrr_movements"], ["main.fct_mrr_movements"])
    assert not grounded(["fct_mrr_daily"], ["stg_subscriptions"])
    assert grounded([], None)


def test_parse_answer_takes_the_last_json_block():
    text = 'thinking\n```json\n{"answer": 1}\n```\nthen\n```json\n{"answer": 2, "models": ["x"]}\n```'
    assert parse_answer(text) == {"answer": 2, "models": ["x"]}
    assert parse_answer('final: {"answer": null, "unit": "text"}') == {"answer": None, "unit": "text"}
    assert parse_answer("no json here") is None
