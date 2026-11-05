# A/B test analysis (learning project, simulated data)

A learning project on simulated data. A seeded experiment splits new trial accounts 50/50 between the current
onboarding (control) and a guided setup checklist (treatment). Success is activation: the first proposal sent within
14 days of signup. The checklist's true effect is planted (30% to 34%), so the analysis can be checked against a known
answer. Nothing here comes from a real product or real users.

```bash
python -m experiments           # print the readout, write results/onboarding-checklist.json
python -m experiments --check   # fail if the committed results file no longer matches the code
```

| File | What it does |
|---|---|
| `stats.py` | Sample size and power for two proportions, pooled z-test with a Wald 95% interval, sample-ratio-mismatch (chi-square) check. Standard library only, so each formula can be checked by hand. |
| `simulate.py` | The seeded experiment: 170 trial accounts a day for 28 days through three funnel steps (create a job, measure a roof, send a proposal), plus an optional tracking bug. |
| `peeking.py` | 2,000 A/A tests (no real difference), tested once at the end vs every day with a stop at the first p < 0.05. |
| `analysis.py` | Runs all of it and writes the results file the site's A/B test page reads. |

## The readout (seed 20261105)

| Step | Number |
|---|---|
| Planned size | 2,131 accounts per arm for a 4-point lift on 30% (alpha 0.05, power 0.8); 28 days planned, 84% power |
| Result | control 31.1% (n = 2,335), checklist 33.5% (n = 2,425): +2.3 points, 95% CI -0.3 to +5.0, p = 0.083 |
| Same design, 1,000 runs | significant in 85.6%, interval covers the planted lift in 94.0% |
| Split check | 2,335 / 2,425, p = 0.19: fine |
| Tracking bug | a fifth of non-activating treatment accounts go unlogged: split 2,335 / 2,065, p = 0.00005, the check alarms; the broken data would claim +8.2 points |
| Peeking | false positives 5.1% testing once, 25.6% testing daily and stopping at the first significant day |

This seed is one of the roughly one-in-six runs where an 84%-powered test misses a real effect: the interval holds the
true 4 points but also zero. It is kept as is rather than re-rolled, since reading a result like this correctly is the
point of the exercise.

## Tests

`tests/experiments/` (16 tests): sample size and the z-test against hand-computed values, the planted rates on a
large sample, interval coverage near 95% and the share of significant runs matching the analytic power over 2,000
repeated runs, the SRM alarm on the tracking bug, A/A false positives near 5% for one look and over 3x that with daily
looks, and the committed results file matching the code.
