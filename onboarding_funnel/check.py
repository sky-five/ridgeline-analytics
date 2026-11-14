"""The metric-accuracy check: is a move in the funnel real, or did the counting change?

1. redelivered events are counted once;
2. the person key (normalised email + date of birth) matches the true person behind every application id,
   with the raw email as a negative control;
3. application ids per person, week by week: a week above 1.02 means people are being counted more than once;
4. a step detector on each weekly rate finds the week a rate moved, unprompted; a move that lines up with a
   jump in ids per person is a counting artefact, one that does not is real;
5. activation per application id vs per person before and after the counting break, with a 95% CI.
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

IDS_PER_PERSON_LIMIT = 1.02
MIN_SIDE = 4  # weeks on each side of a step
STEP_T = 3.0  # a step this many standard errors from zero is called a shift


def weekly(con) -> pd.DataFrame:
    df = con.sql("select * from funnel_weekly order by program, cohort_week").df()
    df["cohort_week"] = pd.to_datetime(df["cohort_week"]).dt.date
    return df


def redelivery(con) -> dict:
    raw, distinct = con.sql("select count(*), count(distinct event_id) from raw_onboarding.events").fetchone()
    staged = con.sql("select count(*) from stg_onboarding__events").fetchone()[0]
    differ = con.sql("""
        select count(*) from (
            select event_id from raw_onboarding.events
            group by event_id
            having count(distinct (application_id, event_type, event_at, email, coalesce(detail, ''))) > 1)
    """).fetchone()[0]
    return {"delivered_rows": raw, "distinct_events": distinct, "redelivered": raw - distinct, "staged": staged,
            "copies_that_differ": differ, "passed": staged == distinct and differ == 0}


def person_key(con) -> dict:
    """Score a key against the labels: splits (one person, several keys) and merges (one key, several people)."""
    def score(table: str, key_sql: str) -> dict:
        splits, merges = con.sql(f"""
            with k as (
                select distinct e.program, {key_sql} as k, l.person_id
                from {table} as e
                inner join labels.applications as l on e.application_id = l.application_id
            )
            select
                (select count(*) from (select person_id, program from k group by all having count(distinct k) > 1)),
                (select count(*) from (select k, program from k group by all having count(distinct person_id) > 1))
        """).fetchone()
        return {"people_split": splits, "people_merged": merges}

    normalised = score("stg_onboarding__events", "e.applicant_key")
    raw_email = score("raw_onboarding.events", "e.email || '|' || e.date_of_birth")  # negative control
    people = con.sql("select count(distinct (person_id, program)) from labels.applications").fetchone()[0]
    applications = con.sql("select count(*) from fct_applications").fetchone()[0]
    ids = con.sql("select count(*) from fct_application_ids").fetchone()[0]
    return {"true_people": people, "applications": applications, "application_ids": ids,
            "normalised_key": normalised, "raw_email_key": raw_email,
            "passed": applications == people and normalised == {"people_split": 0, "people_merged": 0}}


def step(dates: list, values: np.ndarray, weights: np.ndarray) -> dict | None:
    """The split of a weekly rate into before/after with the largest weighted t-statistic."""
    best = None
    for i in range(MIN_SIDE, len(values) - MIN_SIDE + 1):
        a, b = values[:i], values[i:]
        wa, wb = weights[:i], weights[i:]
        ma, mb = np.average(a, weights=wa), np.average(b, weights=wb)
        resid = np.concatenate([a - ma, b - mb])
        w = np.concatenate([wa, wb])
        var = np.sum(w * resid**2) / np.sum(w) * len(values) / (len(values) - 2)  # weekly variance
        se = np.sqrt(var * (1 / len(a) + 1 / len(b)))
        t = (mb - ma) / se if se > 0 else 0.0
        if best is None or abs(t) > abs(best["t"]):
            best = {"week": dates[i].isoformat(), "before": round(float(ma), 4), "after": round(float(mb), 4),
                    "t": round(float(t), 1)}
    return best


def ids_per_person(w: pd.DataFrame) -> dict:
    out = {}
    for program, g in w.groupby("program"):
        over = g[g["application_ids_per_applicant"] > IDS_PER_PERSON_LIMIT]
        out[program] = {
            "weeks_over_limit": len(over),
            "first_week_over": over["cohort_week"].min().isoformat() if len(over) else None,
            "max": round(float(g["application_ids_per_applicant"].max()), 3),
        }
    return out


def steps(w: pd.DataFrame, ids: dict) -> list[dict]:
    """Run the step detector on each rate and program, and say whether a shift is real or a counting artefact."""
    rates = {"activation_rate_per_id": ("application_ids", True), "activation_rate": ("applicants", True),
             "kyc_pass_rate": ("submitted", False)}
    found = []
    for program, g in w.groupby("program"):
        for rate, (weight, mature_only) in rates.items():
            s = g[g["is_mature"]] if mature_only else g
            st = step(list(s["cohort_week"]), s[rate].to_numpy(float), s[weight].to_numpy(float))
            shift = st is not None and abs(st["t"]) >= STEP_T
            row = {"program": program, "rate": rate, **st, "shift": shift}
            if shift:
                first_over = ids[program]["first_week_over"]
                gap = abs((pd.Timestamp(st["week"]) - pd.Timestamp(first_over)).days) if first_over else None
                counting = gap is not None and gap <= 7  # the rate moved the week people began to be counted twice
                row["reading"] = "counting artefact" if counting else "real"
            found.append(row)
    return found


def _two_rates(a_hits, a_n, b_hits, b_n) -> dict:
    pa, pb = a_hits / a_n, b_hits / b_n
    se = np.sqrt(pa * (1 - pa) / a_n + pb * (1 - pb) / b_n)
    d = pb - pa
    return {"before": round(pa, 4), "after": round(pb, 4), "change_pp": round(100 * d, 1),
            "ci_pp": [round(100 * (d - 1.96 * se), 1), round(100 * (d + 1.96 * se), 1)]}


def activation_gap(w: pd.DataFrame, program: str, week) -> dict:
    """Activation before vs from the counting break on mature weeks, per application id and per person."""
    g = w[(w["program"] == program) & w["is_mature"]]
    before, after = g[g["cohort_week"] < week], g[g["cohort_week"] >= week]
    per_id = _two_rates(before["activated_application_ids"].sum(), before["application_ids"].sum(),
                        after["activated_application_ids"].sum(), after["application_ids"].sum())
    per_person = _two_rates(before["activated"].sum(), before["applicants"].sum(),
                            after["activated"].sum(), after["applicants"].sum())
    drop = per_id["before"] - per_id["after"]
    explained = 1 - (per_person["before"] - per_person["after"]) / drop if drop > 0 else None
    return {"program": program, "from_week": week.isoformat(), "mature_weeks_before": len(before),
            "mature_weeks_after": len(after), "per_application_id": per_id, "per_person": per_person,
            "share_of_drop_from_counting": None if explained is None else round(explained, 2)}


def kyc_reason_shift(con, program: str, week: str) -> dict:
    """For a real move in the KYC pass rate: which fail reason grew, per person submitted, before vs after."""
    df = con.sql(f"""
        with people as (
            select applicant_key, cohort_week >= date '{week}' as after
            from fct_applications where program = '{program}' and submitted_at is not null
        ),
        fails as (
            select distinct applicant_key, detail as reason
            from stg_onboarding__events
            where program = '{program}' and event_type in ('kyc_result', 'kyc_review_result')
                and detail not in ('pass', 'review')
        )
        select f.reason, p.after, count(*) as n, any_value(t.people) as people
        from fails as f
        inner join people as p on f.applicant_key = p.applicant_key
        inner join (select after, count(*) as people from people group by after) as t on p.after = t.after
        group by f.reason, p.after
    """).df()
    df["rate"] = df["n"] / df["people"]
    wide = df.pivot(index="reason", columns="after", values="rate").fillna(0)
    wide["change"] = wide[True] - wide[False]
    top = wide["change"].idxmax()
    return {"program": program, "from_week": week, "reason": top, "before": round(float(wide.loc[top, False]), 4),
            "after": round(float(wide.loc[top, True]), 4)}


def run(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        w = weekly(con)
        ids = ids_per_person(w)
        found = steps(w, ids)
        broken = [p for p, v in ids.items() if v["first_week_over"]]
        gaps = [activation_gap(w, p, pd.Timestamp(ids[p]["first_week_over"]).date()) for p in broken]
        real_kyc = [kyc_reason_shift(con, st["program"], st["week"]) for st in found
                    if st["shift"] and st["reading"] == "real" and st["rate"] == "kyc_pass_rate"]
        checks = {"redelivery": redelivery(con), "person_key": person_key(con)}
    checks["ids_per_person"] = {"limit": IDS_PER_PERSON_LIMIT, "programs": ids,
                                "passed": not broken, "programs_over": broken}
    return {"checks": checks, "steps": found, "counting_breaks": gaps, "kyc_reason_shifts": real_kyc}
