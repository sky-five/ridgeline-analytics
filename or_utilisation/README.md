# ROI you can defend: operating-room block utilisation (simulated data)

A surgical suite gives each surgical service fixed blocks of operating-room time. When a surgeon is away,
the block sits idle unless the service releases it early enough for another service to use. From
2026-04-06 the suite runs an auto-release rule: a block with nothing booked 72 hours ahead is released
unless the surgeon keeps it. This folder works out what that rule returned, and shows how the usual
utilisation numbers can make the return look five times bigger than it is. Everything runs in dbt on
DuckDB on seeded synthetic data; nothing here comes from a real hospital, service or patient.

```bash
python -m or_utilisation           # simulate, load, dbt build, review the claims, size the return, write results/
python -m or_utilisation --check   # fail if the committed results are out of date (CI)
```

## The data

`simulate.py` makes 26 weeks of weekdays (2026-01-05 to 2026-07-03) for 12 rooms: 1,560 blocks of 8 hours,
each owned by one of six services on a fixed weekly template. 5,145 cases were booked and 4,741 completed.
On 12-18% of block days (by service) the surgeon is away; 80% of absences are known 72 hours or more
ahead. Services release a known absence on their own 35% of the time, and a block released 72 hours or more
ahead finds a taker 65% of the time (25% at shorter notice). Same-day cancellations are not refilled and
fall from about 10% in January and February to 6% from April, so utilisation rises in the spring on its own.

There were 129 releases, 48 of them by the rule. Every random draw belongs to one block, so the same
half-year can be replayed with the rule switched off. That replay is the truth: the rule added 6,332 patient
minutes (105.5 hours, 73 cases) inside the block window. It is never loaded into the warehouse.

## Metric spec

[metric_spec.yml](metric_spec.yml) defines each metric (numerator, denominator, what it is fit for), and the
dbt macro `utilisation_columns` computes them for any grouping of `fct_blocks`. A test recomputes every
week's value from the spec. Minutes count only inside the 07:30-15:30 window; an overrun is not extra capacity.

| Metric | Numerator / denominator | Weeks 1-13 | Weeks 14-26 |
|---|---|---|---|
| Block utilisation | owner's patient minutes / block minutes | 52.3% | 56.4% |
| Adjusted block utilisation | owner's patient minutes / (block minutes - time released 72 h+ ahead) | 54.8% | 63.0% |
| Block utilisation with turnover | (owner's patient + turnover minutes) / block minutes | 64.7% | 69.9% |
| Room utilisation | every patient minute / block minutes | 53.7% | 59.5% |
| Released-time rate | minutes released 72 h+ ahead / block minutes | 4.5% | 10.5% |
| Released-time reuse rate | other services' patient minutes in released blocks / released minutes | 26.1% | 27.4% |
| Same-day cancellation rate | cancelled / booked cases | 9.7% | 6.1% |

Adjusted block utilisation is the right number for a fair block review (a service is not penalised for time
it gave back early). It is the wrong number for judging a release rule, because releasing more shrinks its
denominator.

## The validation suite

`validate.py` reviews a before/after claim with five checks: the denominator moved, turnover counted as
used time, the numerator leaves out what the rule can add (other services' cases in released time), the
metric also moved on blocks the owning service booked (the rule cannot act there), and unequal windows
(here both periods have 65 weekdays with the same mix, so it never fires).

| Claim (weeks 1-13 to 14-26) | Change | Flags |
|---|---|---|
| Adjusted block utilisation | +8.2 pp | denominator moved (-6.3% a day; +4.3 pp with the old denominator), misses the gain, moved +3.0 pp on booked blocks |
| Block utilisation with turnover | +5.2 pp | counts turnover (13.5 pp of the rate), misses the gain, moved +3.9 pp on booked blocks |
| Block utilisation | +4.1 pp | misses the gain, moved +3.0 pp on booked blocks |
| Room utilisation | +5.9 pp | moved +3.0 pp on booked blocks |

Room utilisation is the honest metric, but a plain before/after still credits the rule with fewer winter
cancellations. Tests plant each framing on hand-made rows (for example, 200 of 1,000 minutes released with
no new case: adjusted utilisation 20% to 25%) and check that a claim where nothing moved passes clean.

## The return

`roi.py` turns each framing into added patient minutes over the 13 weeks, and into money with two
placeholder assumptions a finance team would replace: $1,500 contribution margin per patient hour and
$25,000 to run the rule.

| Framing | Added patient minutes | Net return |
|---|---|---|
| Claimed: adjusted block utilisation change x all block minutes | 30,857 | $746,417 |
| Before/after room utilisation | 21,956 | $523,900 |
| Defended: patient minutes in released blocks above the before-period rate | 6,699 (95% CI 2,798 to 10,455) | $142,475 ($44,950 to $236,375) |
| Replayed truth | 6,332 | $133,300 |

The defended estimate counts only time the rule could have changed: other services' patient minutes in
released blocks, minus what the before-period reuse per block minute would have given on the same block
minutes. Its interval comes from resampling days in each period, and it covers the truth. The claim is 4.9
times the truth. The interval is wide because the rule only released 48 blocks; the minutes are what the
analysis stands behind, the dollars move with the two assumptions.

## Files

```
simulate.py      the seeded suite and the replay without the rule
load.py          raw_or.* in DuckDB, then dbt build
dbt/             staging views, fct_cases, fct_blocks, weekly / by-period / by-service marts, singular tests
metric_spec.yml  the metric definitions; spec.py evaluates them from minute sums
validate.py      the five framing checks
roi.py           claimed vs before/after vs defended, against the truth
results/         summary.json and utilisation_weekly.csv (CI checks they are current)
```
