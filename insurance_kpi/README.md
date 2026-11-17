# Insurance KPI starter

A starting kit for an insurance book's numbers: two simulated exports (policies and claims), a column profile and
data-quality checks scored against faults planted on purpose, a cleaning step that must give back the true book, and
a KPI tree from combined ratio down to frequency, severity and premium, with the year-on-year change split exactly
across the tree. Python and SQL on in-memory DuckDB. All data is simulated.

```bash
python -m insurance_kpi           # simulate, profile, check, clean, build the tree, write results/
python -m insurance_kpi --check   # fail if results/ would change (run in CI)
```

Results: [kpi_tree.md](results/kpi_tree.md) (the tree, what moved, what the cleaning changed),
[checks.csv](results/checks.csv), [column_profile.csv](results/column_profile.csv),
[kpi_tree.csv](results/kpi_tree.csv), [kpi_change.csv](results/kpi_change.csv),
[kpi_segments.csv](results/kpi_segments.csv) (line x province), [summary.json](results/summary.json).

## The book

`simulate.py` (seed 540) writes a personal-lines book: auto and home, four provinces (ON, AB, BC, QC), broker (12%
commission) and direct (3% platform fee), one-year policies starting 2023-01-01 to 2025-12-31, claims valued on
2026-06-30. The true book has 63,000 policies and 4,182 claims reported by the valuation date. Case reserves are set
to each open claim's remaining cost, so incurred (paid + case reserve) is the full cost; there is no IBNR step (the
mean report lag is 12 days).

Planted business changes, accident year 2025 against 2024: auto claim costs +15% on losses from 2025, an auto rate
increase of +6% on policies starting in 2025, and hail doubling home claim frequency in AB in 2025.

## Profile and checks

The exports carry 135 planted faults on top of the true book (63,008 policy rows, 4,257 claim rows):

| fault | rows | check | clean step |
|---|---:|---|---|
| duplicate claim row | 40 | claim_id appears more than once | keep one copy |
| orphan claim | 15 | policy_id in no policy export | drop |
| loss outside the policy term | 20 | loss date before start or on/after end | drop |
| negative paid amount | 12 | paid below zero | flip the sign |
| reported before loss | 10 | reported date earlier than loss date | swap the dates back |
| missing province | 30 | province empty | set to 'unknown' |
| zero-premium test policy | 8 | written premium zero or below | drop |

Each check is a SQL query in [profile.py](profile.py) that returns the key of every row it flags. All 135 are
caught, with no false flags. Seven more checks pass on this export (duplicate policy, term not positive, unknown
line/province/channel code, commission outside 0-30%, unknown claim status, negative reserve, closed claim with a
reserve); the tests plant one new fault for each and check that it is caught. The column profile lists every raw
column's type, nulls, distinct values, min and max, which is where the 30 empty provinces, the 40 repeated claim ids
and the negative paid minimum first show.

The order matters in one place: the term and orphan checks run after the row-level fixes (schema `stg`), so a claim
with swapped dates is judged on its real loss date and not flagged twice.

The tests check that the cleaned tables equal the true book row for row (apart from the 30 provinces now 'unknown').
A naive query over the raw exports overstates the all-lines loss ratio by 0.2 points for 2024 and 0.6 for 2025:
small, and easy to miss in a trend.

## The KPI tree

```
combined ratio = loss ratio + expense ratio
  loss ratio   = frequency x severity / average earned premium
    frequency  = claims / earned policy-years
    severity   = incurred / claims
    avg premium = earned premium / earned policy-years
  expense ratio = commission ratio + admin ratio ($95 per earned policy-year)
```

Premium, commission and exposure are earned day by day over each policy's term; a claim belongs to the accident
year of its loss date. The change from 2024 to 2025 is split across frequency, severity and average premium with
log-mean weights (each driver gets L(LR25, LR24) x ln(driver25 / driver24)), so the three parts add up to the
loss-ratio change exactly; the expense side is additive. The tests check every identity and the split on hand
numbers, and recount exposure, premium, claims and incurred in pandas.

What it shows (all lines: combined ratio 47.0% to 56.1%, loss ratio 32.5% to 41.9%):

- **auto**: loss ratio +5.8 points, mostly severity (+6.9), with higher average premium taking back 2.0. Measured
  severity rose 24.7%, +/- 7.5% from sampling alone; the planted +15% is just outside that range, because claim
  costs are heavy-tailed and this is one draw. Average
  earned premium rose 6.5%: the 3% yearly trend plus about half of the +6% rate, since policies starting in 2025 are
  only about half earned in 2025;
- **home**: loss ratio +14.9 points, mostly frequency (+12.7). The line x province leaves put the jump in AB, 2.13
  times its 2024 rate (planted: 2.0); the other provinces moved between -3% and +19%.

## Limits

One seed, two accident years, case-reserve incurred with no IBNR and no development. The admin cost is a flat
amount per policy-year. The tree explains what moved, not why: the drill to province is the first step of the why.
