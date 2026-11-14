"""Builds the onboarding warehouse once (simulate + load + dbt build, about 10 s) and checks the simulator's
planted patterns, the dbt funnel against an independent pandas count keyed on the true person, the
metric-accuracy check on hand-made weeks, and the committed results."""
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd
import pytest

from onboarding_funnel import check
from onboarding_funnel.load import dbt_build, load
from onboarding_funnel.run import FINDINGS, SUMMARY, WEEKLY, findings, summary, to_json, weekly_csv
from onboarding_funnel.simulate import (
    CUTOFF,
    PEOPLE,
    RESUME_BUG_PROGRAM,
    RESUME_BUG_START,
    SELFIE_PROGRAM,
    SELFIE_START,
    simulate,
)

AS_OF = date(2026, 6, 30)
WINDOW = pd.Timedelta(days=30)


@pytest.fixture(scope="module")
def log():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, log):
    path = tmp_path_factory.mktemp("onboarding") / "onboarding.duckdb"
    load(path, log)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def con(db):
    with duckdb.connect(str(db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def truth(log) -> pd.DataFrame:
    """One row per true person, straight from the raw events and the labels (no email key)."""
    e = log.events.drop_duplicates("event_id").merge(log.labels[["application_id", "person_id"]])
    first = lambda kind: e[e["event_type"] == kind].groupby("person_id")["event_at"].min()  # noqa: E731
    passed = e[e["event_type"].isin(["kyc_result", "kyc_review_result"]) & (e["detail"] == "pass")]
    t = pd.DataFrame({"program": e.groupby("person_id")["program"].first(),
                      "started": first("application_started"), "submitted": first("application_submitted"),
                      "kyc_passed": passed.groupby("person_id")["event_at"].min(),
                      "funded": first("account_funded"), "first_txn": first("first_transaction")})
    week = t["started"].dt.to_period("W-SUN").dt.start_time
    t["mature"] = (week + pd.Timedelta(days=6) + WINDOW) <= pd.Timestamp(AS_OF)
    t["activated"] = t["first_txn"].notna() & (t["first_txn"] <= t["started"] + WINDOW)
    return t


# --- the simulator ---------------------------------------------------------------------------


def test_simulation_is_seeded(log):
    again = simulate()
    pd.testing.assert_frame_equal(log.events, again.events)
    pd.testing.assert_frame_equal(log.labels, again.labels)


def test_events_are_consistent(log):
    e = log.events
    assert (e["event_at"] <= CUTOFF).all() and (e["received_at"] >= e["event_at"]).all()
    assert set(e["application_id"]) == set(log.labels["application_id"])
    started = set(e.loc[e["event_type"] == "application_started", "application_id"])
    assert started == set(e["application_id"])  # every application id has its start
    copies = e[e.duplicated("event_id", keep=False)]
    assert len(copies) > 0
    assert copies.drop(columns="received_at").drop_duplicates().shape[0] == copies["event_id"].nunique()


def test_only_the_buggy_app_opens_second_ids(log):
    starts = log.events[log.events["event_type"] == "application_started"].drop_duplicates("event_id")
    starts = starts.merge(log.labels[["application_id", "person_id"]])
    later = starts[starts.duplicated("person_id")]  # second and later ids of the same person
    assert len(later) > 200
    assert set(later["program"]) == {RESUME_BUG_PROGRAM}
    assert (later["event_at"].dt.date >= RESUME_BUG_START).all()
    assert log.labels["person_id"].nunique() == PEOPLE


def test_the_selfie_check_gets_stricter(log):
    k = log.events[log.events["event_type"] == "kyc_result"].drop_duplicates("event_id")
    k = k[k["program"] == SELFIE_PROGRAM]
    after = k["event_at"].dt.date >= SELFIE_START
    rate = lambda m: (k.loc[m, "detail"] == "selfie_mismatch").mean()  # noqa: E731
    assert rate(after) > 2.5 * rate(~after)


# --- the dbt funnel against an independent count ---------------------------------------------


def test_one_application_per_true_person(con, truth):
    got = con.sql("select program, count(*) as n from fct_applications group by program").df()
    assert got.set_index("program")["n"].to_dict() == truth.groupby("program").size().to_dict()


def test_funnel_matches_pandas_on_the_true_person(con, truth):
    t = truth[truth["mature"]]
    want = pd.DataFrame({"started": t.groupby("program").size(),
                         "submitted": t.groupby("program")["submitted"].count(),
                         "kyc_passed": t.groupby("program")["kyc_passed"].count(),
                         "funded": t.groupby("program")["funded"].count(),
                         "activated": t.groupby("program")["activated"].sum()})
    got = con.sql("select * from funnel_by_program").df().set_index("program")[want.columns]
    pd.testing.assert_frame_equal(got.sort_index(), want.sort_index(), check_dtype=False, check_names=False)


def test_time_to_first_transaction_matches_pandas(con, truth):
    t = truth[truth["mature"] & truth["activated"]]
    days = (t["first_txn"] - t["started"]).dt.total_seconds() / 86_400
    got = con.sql("select program, median_days, share_within_7_days from time_to_first_transaction").df()
    got = got.set_index("program")
    for program, d in days.groupby(t["program"]):
        assert got.loc[program, "median_days"] == pytest.approx(d.median(), abs=1e-6)
        assert got.loc[program, "share_within_7_days"] == pytest.approx((d <= 7).mean())


def test_counting_ids_double_counts_only_the_buggy_program(con):
    w = con.sql("select program, sum(application_ids) - sum(applicants) as extra from funnel_weekly "
                "group by program").df().set_index("program")["extra"]
    assert w[RESUME_BUG_PROGRAM] > 200
    assert (w.drop(RESUME_BUG_PROGRAM) == 0).all()


# --- the accuracy check on hand-made weeks ----------------------------------------------------


def _weeks(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    return [start + timedelta(weeks=i) for i in range(n)]


def test_step_detector_finds_a_planted_step_and_ignores_noise():
    rng = np.random.default_rng(0)
    weeks = _weeks(20)
    flat = 0.5 + rng.normal(0, 0.01, 20)
    stepped = flat.copy()
    stepped[12:] -= 0.06
    w = np.full(20, 400.0)
    found = check.step(weeks, stepped, w)
    assert found["week"] == weeks[12].isoformat() and found["t"] <= -check.STEP_T
    assert abs(check.step(weeks, flat, w)["t"]) < check.STEP_T


def _frame(program: str, ids: list[int], people: list[int], act_ids: list[int], act: list[int]) -> pd.DataFrame:
    n = len(ids)
    return pd.DataFrame({"program": program, "cohort_week": _weeks(n), "is_mature": True,
                         "application_ids": ids, "applicants": people,
                         "application_ids_per_applicant": np.array(ids) / np.array(people),
                         "activated_application_ids": act_ids, "activated": act,
                         "activation_rate_per_id": np.array(act_ids) / np.array(ids),
                         "activation_rate": np.array(act) / np.array(people),
                         "submitted": people, "kyc_passed": people, "kyc_pass_rate": 1.0})


def test_ids_per_person_flags_the_first_week_over_the_limit():
    w = pd.concat([_frame("ok", [100] * 10, [100] * 10, [40] * 10, [40] * 10),
                   _frame("bad", [100] * 5 + [115] * 5, [100] * 10, [40] * 10, [40] * 10)])
    ids = check.ids_per_person(w)
    assert ids["ok"] == {"weeks_over_limit": 0, "first_week_over": None, "max": 1.0}
    assert ids["bad"]["first_week_over"] == _weeks(10)[5].isoformat() and ids["bad"]["weeks_over_limit"] == 5


def test_activation_gap_puts_a_counting_drop_on_the_counting():
    # people activate at 40% throughout; from week 6 there are 20% more ids, none of them activate
    w = _frame("bad", [1000] * 6 + [1200] * 6, [1000] * 12, [400] * 12, [400] * 12)
    g = check.activation_gap(w, "bad", _weeks(12)[6])
    assert g["per_person"]["change_pp"] == 0.0
    assert g["per_application_id"]["after"] == pytest.approx(400 / 1200, abs=1e-4)
    assert g["share_of_drop_from_counting"] == 1.0


def test_a_shift_is_read_as_counting_only_when_ids_per_person_jumps():
    rng = np.random.default_rng(1)
    base = 400 + rng.integers(-8, 8, 16)
    ids = [1000] * 8 + [1150] * 8
    found = check.steps(_frame("bad", ids, [1000] * 16, list(base), list(base)), {"bad": {
        "first_week_over": _weeks(16)[8].isoformat()}})
    by_rate = {r["rate"]: r for r in found}
    assert by_rate["activation_rate_per_id"]["reading"] == "counting artefact"
    assert not by_rate["activation_rate"]["shift"]
    dropped = list(base[:8]) + list(base[8:] - 60)
    real = check.steps(_frame("ok", [1000] * 16, [1000] * 16, dropped, dropped), {"ok": {"first_week_over": None}})
    assert {r["rate"]: r for r in real}["activation_rate"]["reading"] == "real"


# --- what the check finds on the simulated log, and the committed results ----------------------


def test_the_check_finds_both_planted_moves(db):
    r = check.run(db)
    assert r["checks"]["redelivery"]["passed"] and r["checks"]["person_key"]["passed"]
    assert r["checks"]["person_key"]["raw_email_key"]["people_split"] > 100  # the negative control
    assert r["checks"]["ids_per_person"]["programs_over"] == [RESUME_BUG_PROGRAM]
    shifts = {(s["program"], s["rate"]): s for s in r["steps"] if s["shift"]}
    assert shifts.keys() == {(RESUME_BUG_PROGRAM, "activation_rate_per_id"), (SELFIE_PROGRAM, "kyc_pass_rate")}
    assert shifts[(RESUME_BUG_PROGRAM, "activation_rate_per_id")]["week"] == RESUME_BUG_START.isoformat()
    assert shifts[(RESUME_BUG_PROGRAM, "activation_rate_per_id")]["reading"] == "counting artefact"
    assert shifts[(SELFIE_PROGRAM, "kyc_pass_rate")]["week"] == SELFIE_START.isoformat()
    assert shifts[(SELFIE_PROGRAM, "kyc_pass_rate")]["reading"] == "real"
    gap = r["counting_breaks"][0]
    lo, hi = gap["per_person"]["ci_pp"]
    assert lo < 0 < hi and gap["per_application_id"]["ci_pp"][1] < 0
    assert r["kyc_reason_shifts"][0]["reason"] == "selfie_mismatch"


def test_committed_results_are_current(db):
    s = summary(db)
    assert SUMMARY.read_text() == to_json(s)
    assert WEEKLY.read_text() == weekly_csv(db)
    assert FINDINGS.read_text() == findings(s)
