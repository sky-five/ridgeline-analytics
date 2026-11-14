"""A seeded, simulated onboarding event log for four account programs run on one platform, 25 weeks of
starts from 2026-01-05 to 2026-06-28, cut off at the end of 2026-06-30.

Each person starts an application in one program, uploads an identity document, submits, gets a KYC
(know-your-customer) result (pass, fail with a reason, or manual review), funds the account and makes a first
transaction. People drop out at every step. Someone who left before submitting may come back once, and someone
whose document was unreadable or whose selfie did not match may try again.

Three things are planted:

- the cross-border app from 2026-04-06 starts a fresh application id when a person resumes or retries, often
  with the email typed in a different case, so counting application ids double-counts people from that week;
- the consumer card's selfie check gets stricter from 2026-05-11: a real drop in KYC passes;
- about 1.5% of events are delivered twice with the same event id.

The true person behind every application id is kept in `labels`, out of the event log, so the dedupe can be scored.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

SEED = 515
FIRST_DAY = date(2026, 1, 5)
WEEKS = 25
AS_OF = date(2026, 6, 30)
CUTOFF = datetime(2026, 6, 30, 23, 59, 59)  # events after this are not in the export yet
PEOPLE = 24_000
RESUME_BUG_PROGRAM, RESUME_BUG_START = "cross_border", date(2026, 4, 6)
SELFIE_PROGRAM, SELFIE_START, SELFIE_FAIL_AFTER = "consumer_card", date(2026, 5, 11), 0.09
DUPLICATE_DELIVERY = 0.015
RESUME = 0.25  # chance someone who left before submitting comes back once
RETRY = 0.60  # chance of trying again after an unreadable document or a selfie mismatch (at most twice)
RETRYABLE = ("document_unreadable", "selfie_mismatch")


@dataclass(frozen=True)
class Program:
    share: float
    upload: float  # started -> document uploaded
    submit: float  # uploaded -> submitted
    fail: dict  # KYC fail reason -> chance on a submitted application
    review: float  # chance KYC sends it to manual review
    review_pass: float
    review_hours: float  # mean
    fund: float  # passed -> funded
    fund_hours: float  # median, pass -> funded
    transact: float  # funded -> first transaction
    transact_hours: float  # median, funded -> first transaction


PROGRAMS = {
    "consumer_card": Program(0.40, 0.84, 0.90, {"document_unreadable": 0.05, "selfie_mismatch": 0.03,
                                                "address_unverified": 0.02, "watchlist_hit": 0.005},
                             0.06, 0.70, 20, 0.72, 18, 0.86, 40),
    "gig_payouts": Program(0.25, 0.90, 0.94, {"document_unreadable": 0.04, "selfie_mismatch": 0.02,
                                              "address_unverified": 0.01, "watchlist_hit": 0.005},
                           0.04, 0.75, 16, 0.93, 30, 0.95, 12),
    "business_expense": Program(0.15, 0.72, 0.80, {"document_unreadable": 0.04, "selfie_mismatch": 0.01,
                                                   "address_unverified": 0.10, "watchlist_hit": 0.01},
                                0.18, 0.60, 52, 0.78, 70, 0.88, 96),
    "cross_border": Program(0.20, 0.80, 0.86, {"document_unreadable": 0.07, "selfie_mismatch": 0.03,
                                               "address_unverified": 0.03, "watchlist_hit": 0.015},
                            0.08, 0.65, 26, 0.66, 36, 0.82, 60),
}


@dataclass
class Log:
    events: pd.DataFrame  # the export: one row per delivered event, duplicates included
    labels: pd.DataFrame  # application_id -> the true person (not in the export)


def _hours(rng, median: float) -> timedelta:
    return timedelta(hours=float(median * rng.lognormal(0, 0.8)))


def _email(rng, n: int, retry_with_new_id: bool) -> str:
    email = f"person{n:05d}@example.test"
    if not retry_with_new_id:
        return email
    u = rng.random()
    return email.upper() if u < 0.25 else email.capitalize() if u < 0.45 else f" {email}" if u < 0.55 else email


def _kyc_fail_rates(name: str, prog: Program, when: datetime) -> dict:
    fail = dict(prog.fail)
    if name == SELFIE_PROGRAM and when.date() >= SELFIE_START:
        fail["selfie_mismatch"] = SELFIE_FAIL_AFTER
    return fail


def _kyc_fail(rng, fail: dict) -> str | None:
    u, edge = rng.random(), 0.0
    for reason, p in fail.items():
        edge += p
        if u < edge:
            return reason
    return None


def _person(rng, n: int, program: str, start: datetime) -> tuple[list[dict], list[str]]:
    prog = PROGRAMS[program]
    dob = (date(1960, 1, 1) + timedelta(days=int(rng.integers(0, 15_000)))).isoformat()
    events, app_ids = [], []

    def emit(app_id: str, event_type: str, at: datetime, email: str, detail: str | None = None):
        events.append({"application_id": app_id, "program": program, "event_type": event_type, "event_at": at,
                       "email": email, "date_of_birth": dob, "detail": detail})

    def new_application(at: datetime, is_retry: bool) -> tuple[str, str]:
        app_id = f"A{n:05d}-{len(app_ids) + 1}"
        app_ids.append(app_id)
        email = _email(rng, n, is_retry)
        emit(app_id, "application_started", at, email)
        return app_id, email

    app_id, email = new_application(start, False)
    t, resumed, retries = start, False, 0
    while True:  # one pass per attempt, from the document upload onwards
        uploaded = rng.random() < prog.upload
        if uploaded:
            t += timedelta(minutes=float(rng.exponential(12)))
            emit(app_id, "document_uploaded", t, email)
        if not uploaded or rng.random() >= prog.submit:  # left before submitting
            if resumed or rng.random() >= RESUME:
                break
            resumed = True
            t += _hours(rng, 30)
            app_id, email = _come_back(program, t, app_id, email, new_application, emit)
            continue
        t += timedelta(minutes=float(rng.exponential(6)))
        emit(app_id, "application_submitted", t, email)
        t += timedelta(minutes=float(1 + rng.exponential(20)))
        reason = _kyc_fail(rng, _kyc_fail_rates(program, prog, t))
        if reason in RETRYABLE and retries < 2 and rng.random() < RETRY:
            emit(app_id, "kyc_result", t, email, reason)
            retries += 1
            t += _hours(rng, 6)
            app_id, email = _come_back(program, t, app_id, email, new_application, emit)
            continue
        if reason is not None:
            emit(app_id, "kyc_result", t, email, reason)
            break
        if rng.random() < prog.review:
            emit(app_id, "kyc_result", t, email, "review")
            t += timedelta(hours=float(rng.exponential(prog.review_hours)))
            if rng.random() >= prog.review_pass:
                emit(app_id, "kyc_review_result", t, email, "manual_review_declined")
                break
            emit(app_id, "kyc_review_result", t, email, "pass")
        else:
            emit(app_id, "kyc_result", t, email, "pass")
        if rng.random() < prog.fund:
            t += _hours(rng, prog.fund_hours)
            emit(app_id, "account_funded", t, email)
            if rng.random() < prog.transact:
                t += _hours(rng, prog.transact_hours)
                emit(app_id, "first_transaction", t, email)
        break
    return events, app_ids


def _come_back(program, t, app_id, email, new_application, emit):
    """Resume or retry: the cross-border app opens a new application from the bug date, the others resume."""
    if program == RESUME_BUG_PROGRAM and t.date() >= RESUME_BUG_START:
        return new_application(t, True)
    emit(app_id, "application_resumed", t, email)
    return app_id, email


def simulate(seed: int = SEED) -> Log:
    rng = np.random.default_rng(seed)
    names = list(PROGRAMS)
    shares = [PROGRAMS[p].share for p in names]
    days = WEEKS * 7
    rows, labels = [], []
    for n in range(1, PEOPLE + 1):
        program = str(rng.choice(names, p=shares))
        day = FIRST_DAY + timedelta(days=int(rng.integers(0, days)))
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=float(rng.uniform(7, 23)))
        events, app_ids = _person(rng, n, program, start)
        rows += events
        labels += [{"application_id": a, "person_id": f"person{n:05d}", "program": program} for a in app_ids]
    events = pd.DataFrame(rows)
    events = events[events["event_at"] <= CUTOFF]
    events = events.sort_values(["event_at", "application_id"], kind="stable").reset_index(drop=True)
    events.insert(0, "event_id", [f"E{i:07d}" for i in range(1, len(events) + 1)])
    events["received_at"] = events["event_at"] + pd.to_timedelta(rng.exponential(30, len(events)), unit="s")
    dup = events[rng.random(len(events)) < DUPLICATE_DELIVERY].copy()
    dup["received_at"] += pd.to_timedelta(rng.uniform(60, 3_600, len(dup)), unit="s")
    events = pd.concat([events, dup]).sort_values(["received_at", "event_id"], kind="stable").reset_index(drop=True)
    events["event_at"] = events["event_at"].dt.floor("s")
    events["received_at"] = events["received_at"].dt.floor("s")
    started = set(events["application_id"])
    labels = pd.DataFrame(labels)
    labels = labels[labels["application_id"].isin(started)].reset_index(drop=True)
    return Log(events=events, labels=labels)
