# Onboarding funnel monitor

A funnel monitor for account onboarding (identity checks, funding, first transaction) on a simulated event log,
with a check that tells a real drop from a counting change. Everything runs on DuckDB; the funnel is a small dbt
project. Simulated data only.

```
python -m onboarding_funnel          # simulate, load, dbt build, write results/
python -m onboarding_funnel --check  # rebuild and fail if results/ is out of date (CI runs this)
```

## The data

`simulate.py` (seeded) writes an event log for four account programs on one platform: `consumer_card`,
`gig_payouts`, `business_expense` and `cross_border`. 24,000 people start an application between 2026-01-05 and
2026-06-28. The export is cut off at the end of 2026-06-30 and has 114,999 delivered events. Each person goes
through `application_started`, `document_uploaded`, `application_submitted`, `kyc_result` (pass, review, or a fail
reason), `kyc_review_result`, `account_funded` and `first_transaction`, and can drop out at every step. Someone who
leaves before submitting may come back once (`application_resumed`). Someone whose document was unreadable or
whose selfie did not match may try again.

Three things are planted for the monitor to find:

| planted | what it does |
|---|---|
| resume bug, `cross_border` from 2026-04-06 | a resume or retry opens a **new application id**, often with the email typed in another case or with a leading space |
| stricter selfie check, `consumer_card` from 2026-05-11 | selfie mismatches go from 3% to 9% of KYC results: a real drop |
| redelivery | 1,706 events (about 1.5%) arrive twice with the same event id |

The true person behind each application id goes to `labels.applications`. The dbt models never read it; it is
only used to score the dedupe.

## The models

| model | grain | what it is for |
|---|---|---|
| `stg_onboarding__events` | event | removes redeliveries (keeps the first) and adds `applicant_key` = md5 of the trimmed, lower-case email and the date of birth |
| `fct_applications` | person x program | the application: every application id a person opened in a program counts once; first time each step was reached; drop-off step and reason |
| `fct_application_ids` | application id | what a dashboard that counts ids sees; kept to show the gap |
| `funnel_by_program` | program | people reaching each step on mature cohorts, with each step's rate |
| `drop_off_reasons` | program x step x reason | why people in mature cohorts did not activate |
| `time_to_first_transaction` | program | median, p90, share within 1 and 7 days, from first start to first transaction |
| `funnel_weekly` | program x cohort week | activation per application id and per person, ids per person, KYC pass rate |

Definitions: a person is **activated** if their first transaction is within 30 days of their first start. A
cohort week is **mature** once every person in it has had the full 30 days by the as-of date (weeks to
2026-05-25). The funnel, drop-off and time tables use mature cohorts only. The KYC pass rate is people passing
KYC (directly or after review) over people who submitted.

dbt tests: unique keys, accepted values for event types and drop-off steps, and four singular tests (one
application per person and program; no step reaches more people than the step before; the mature weeks add up to
the program funnel; every person who did not activate has exactly one drop-off reason).

## What the funnel shows

Mature cohorts, people who started from 2026-01-05 to 2026-05-25:

| program | started | KYC pass | activated | median days to first transaction | biggest drop-off |
|---|---:|---:|---:|---:|---|
| gig_payouts | 5,000 | 94.6% | 73.5% | 2.0 | left before the document upload (26.9%) |
| consumer_card | 8,031 | 91.0% | 45.1% | 2.9 | passed KYC, never funded (36.2%) |
| business_expense | 3,072 | 80.4% | 34.3% | 8.4 | left before the document upload (34.1%) |
| cross_border | 4,025 | 86.5% | 33.2% | 4.7 | passed KYC, never funded (32.9%) |

The business program loses the most at KYC, mostly on `address_unverified`. In the consumer card and cross-border
programs the largest single loss comes after KYC: people pass and never put money in.

## The metric-accuracy check

`check.py` runs five checks on the built warehouse and writes them into `results/summary.json`:

1. **Redeliveries.** 1,706 of 114,999 delivered rows repeat an event id, and every copy is identical apart from
   the receive time. The staged table has one row per event (113,293).
2. **Person key against the truth.** The 24,326 application ids belong to 24,000 people. Keyed on the normalised
   email and date of birth, the warehouse finds exactly 24,000 applications, splitting no person and merging none.
   Keyed on the raw email (the negative control), it would split 165 people.
3. **Application ids per person, by program and week.** Above 1.02, people are being counted more than once.
   `cross_border` goes over in the week of 2026-04-06 and stays over for all 12 weeks after (up to 1.176). The
   other programs stay at exactly 1.000.
4. **Step reading.** A step detector looks for the week each weekly rate moved most (largest weighted t over
   splits with at least 4 weeks on each side) and calls it a shift at |t| >= 3. It is not told the planted dates.
   It finds two shifts. `cross_border` activation per application id drops in the week of 2026-04-06 (t = -3.1),
   the same week ids per person jump, so it is read as a **counting artefact**. `consumer_card` KYC pass rate
   drops from 91.5% to 87.9% in the week of 2026-05-11 (t = -5.4) while ids per person stay at 1.000, so it is
   read as **real**. `selfie_mismatch` is the fail reason that grew (2.9% to 8.9% of people submitted). The
   margin is thin: the largest step on a series with nothing planted is t = 2.9 (`gig_payouts` KYC pass rate). So
   the ids-per-person check, not the step detector, is the alarm for double counting.
5. **Before and after the counting break**, on mature `cross_border` weeks. Per application id, activation goes
   from 33.6% to 28.8% (-4.8 pp, 95% CI -7.6 to -2.0). Per person it goes from 33.6% to 32.6% (-1.0 pp, 95% CI
   -4.0 to +2.0). About 80% of the drop a dashboard counting ids would show is people counted twice.

The [findings note](results/findings.md) is generated from these results. `results/funnel_weekly.csv` has the
weekly table (100 rows).

## Tests

`tests/onboarding_funnel/` builds the warehouse once (about 10 s) and checks:

- the simulator is seeded, only the cross-border app opens second ids and only from the bug date, and the selfie
  check gets stricter;
- the dbt funnel, application counts and time to first transaction against an independent pandas count keyed on
  the true person, not the email;
- the check's pieces on hand-made weeks (a planted step found and noise ignored; the ids-per-person flag; a drop
  made only of extra ids attributed 100% to counting);
- that the check finds both planted moves on the simulated log and reads them correctly, and that the committed
  results are current.

Not in this half: the dashboard page.
