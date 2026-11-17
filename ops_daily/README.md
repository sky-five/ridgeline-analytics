# Operations speed-to-decision

A daily view of a simulated claims operation: calls, handle time, backlog and service level by site and line, a
flag rule that names the three things to look at today, a so-what paragraph per metric, and a metric definitions
sheet. dbt on DuckDB. All data is simulated.

```bash
python -m ops_daily           # simulate, load, dbt build, write results/
python -m ops_daily --check   # fail if results/ would change (run in CI)
```

## The operation

`simulate.py` writes two feeds for three sites (east, central, west) and two lines (home, auto):

- `raw_ops.calls`: one row per day, site and line from the phone system, 2026-01-01 to 2026-06-30 (1,086 rows,
  299,673 calls offered): offered, answered, abandoned, answered within 60 seconds, handle seconds, staffed hours;
- `raw_ops.claims`: one row per claim with the day it was opened and closed (33,958 claims from 2025-11-03, so the
  backlog is settled by January; 25,548 opened in 2026).

Volumes follow the weekday. Staffing is planned for 78% occupancy; when the load runs above that, fewer calls are
answered within 60 seconds and more callers hang up. Planted for the flag rule to find:

- **staff cut**: west auto has 82% of its planned hours from 2026-06-22;
- **handle-time creep**: east home handle time rises 18% over two weeks from 2026-06-08 (a new step), and stays;
- **storm**: central home gets a windstorm on 2026-06-18; new claims jump fivefold on the day and fade over a week
  (512 in the storm week against 183 two weeks before), and the backlog builds because closing capacity does not
  change (70 open claims on 06-17, 384 on 06-30).

## The model

| model | grain | what it adds |
|---|---|---|
| `fct_claims_day` | day x site x line | claims opened, closed, and still open at the end of the day |
| `fct_ops_day` | day x site x line | the phone and claims figures side by side, and the seven metrics |
| `ops_metric_day` | day x site x line x metric | the seven metrics in long form |
| `ops_flags` | day x site x line x metric | baseline, spread, score and whether the value is flagged |
| `ops_watchlist` | day x rank | the three things to look at: up to three flagged teams a day |

The [metric definitions sheet](dbt/seeds/metric_definitions.csv) is a dbt seed: for each of the seven metrics
(calls offered, service level, abandon rate, average handle time, new claims, claims closed, open claims) its
definition, formula, source, which direction is good, the flag thresholds, and what to check first when it is
flagged. `ops_flags` reads the thresholds from it, so the sheet and the rule can't drift apart.

dbt tests check that every offered call is answered or abandoned, that today's backlog is yesterday's plus opened
minus closed, one row per team and day, seven metrics per team-day, and at most three watchlist items a day, one
per team, each a flagged metric.

## The flag rule

Each day's value is compared with the same weekday in the previous six weeks (so Mondays are compared with
Mondays). Baseline: the median of those six days. Spread: 1.4826 x their median absolute deviation, floored at a
minimum per metric and, for counts, at the square root of the baseline. A value is flagged when it is at least 3
spreads from the baseline, moves at least the metric's minimum change (for example 10 points of service level, 4
points of abandon rate, 0.5 minutes of handle time, 40% of the usual backlog), and moves the bad way (either way
for calls offered and new claims). The watchlist keeps each team's furthest-out metric, names its other flagged
metrics, and lists the three teams furthest out.

Back-checked on every day from 2026-02-12 (the first with six weeks behind it) to 2026-06-30, 5,838 scored values:

| planted event | from | first flagged on its cause | days on the watchlist |
|---|---|---|---|
| west auto staff cut | 2026-06-22 | same day (service level) | 9 of 9 |
| central home storm | 2026-06-18 | same day (new claims) | 13 of 13 |
| east home handle-time creep | 2026-06-08 | 4 days later (handle time) | 18 of 23 |

Teams with nothing planted were flagged 47 times (0.8% of their scored values), most often on open claims (14) and
service level (10). That is still enough to put a false item on the watchlist on 36 of 139 days, so treat the
third item as a question, not an alarm.

The creep is the rule's weak spot. A slow change is only flagged once it is big enough, and a six-week baseline
takes a lasting change in as normal. By 2026-06-30 three of the six Tuesdays behind it were raised, which widened
the spread so much that east home's 11.2 minutes against a 9.4-minute baseline was not flagged; only its abandon
rate kept the team on the list. After four raised weeks the median itself moves to the new level. A metric with a
known target (handle time against plan) needs that target as a second check.

## The results

- [results/today.md](results/today.md): the three things to look at on 2026-06-30 (central home's backlog, west
  auto's abandon rate, east home's abandon rate) and a so-what paragraph per metric;
- [results/summary.json](results/summary.json): the operation's totals, the back-check, the watchlist;
- [results/flags.csv](results/flags.csv): every flagged day, site, line and metric (130 rows);
- [results/ops_day.csv](results/ops_day.csv): the daily figures and metrics per site and line, for the dashboard;
- [results/metric_day.csv](results/metric_day.csv): every day, team and metric with its baseline, spread, score and
  flag (7,602 rows), for the dashboard's charts.

## The dashboard

The site's [Operations speed-to-decision page](https://sky-five.github.io/ridgeline-analytics/ops-daily/) shows the
half-year's totals, today's three things with what to check first, the seven metrics for one team at a time (pick a
team: each day against its same-weekday median, flagged days as dots, and the team's flag list), the back-check
with the false flags by metric and where the rule is weak, the so-what paragraphs, and the definitions sheet.

`report.py` builds the page's 8 `reporting.ops_*` tables from the committed results only, so the page does not move
with the nightly build.

## Tests

`tests/ops_daily/` (24 tests). `test_ops_daily.py` checks that the simulation is seeded and its feeds hold
together, that the planted events are in the feeds, the claims and phone marts against the raw feeds, the whole flag
rule written again in pandas (same baseline and same flag on all 5,838 scored values), that each planted event is
flagged on its cause within four days and quiet teams on under 1% of their values, that the as-of watchlist names
the three planted teams, that the definitions sheet covers exactly the seven metrics, and that the committed results
are current. `test_report.py` checks the dashboard: the flag list is exactly the flagged rows of the metric table,
the false flags agree with the back-check, today's three things match results/today.md, every query on the page
runs for every team, every column a chart or table names exists, and the page's fixed words (the handle-time
creep no longer flagged on the last day) hold in the data.
