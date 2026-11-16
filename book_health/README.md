# Provincial book health

Growth, loss ratio and retention by province for a simulated home and auto insurance book, with a back-tested
monthly retention forecast and a one-page brief. dbt on DuckDB. All data is simulated.

```bash
python -m book_health           # simulate, load, dbt build, write results/
python -m book_health --check   # fail if results/ would change (run in CI)
```

## The book

`simulate.py` writes 32,758 policies in eight provinces through three channels (broker, direct, digital), as
118,035 twelve-month terms and 9,944 claims from 2022-01 to 2026-06. Each renewal offers a rate change; the bigger
the increase over the usual 4%, the less likely the customer stays. Claims are reported a few weeks after the loss,
so the claims feed stops at what was reported by 2026-06-30.

Planted for the model to find:

- a hailstorm in Alberta on 2024-07-22 (61 home claims, $1.4M);
- Alberta home renewals from 2025-01 offered about 10% instead of 4%;
- Ontario auto renewals from 2025-04 offered about 14%;
- digital customers renew less often than broker customers;
- Alberta's new business grows fastest, Quebec's not at all.

## The model

| model | grain | what it adds |
|---|---|---|
| `stg_book__terms` | term | province, product, channel; outcome at the term's end: renewed, lapsed or not due yet |
| `fct_segment_month` | month x province x product x channel | policies in force at month end, new policies, written premium, earned premium (spread over the days of each term), claims and incurred by loss month, renewals due and renewed, mean offered rate change |
| `province_month` | month x province | loss ratio, retention, year-on-year growth in policies in force and in 12-month written premium |
| `retention_by_segment` | province x product x channel | retention over the last 12 months |

dbt tests check one row per segment-month, that a term never earns more than it wrote (and exactly that when it
lies inside the covered months), that a renewal starts the day the last term ends, and that province months add up
to the segment months and to the terms that came due. Money and rate changes are decimals so the results are the
same on every build.

## The retention forecast

`forecast.py` back-tests three rules for the next three months' retention per province, at every month from
2022-12 to 2026-05, using only months up to that point: last month, the 3-month average and the 12-month average
(both weighted by renewals due). Error is in percentage points, weighted by renewals due.

| rule | mean absolute error | bias | Ontario, first 6 months after its rate increase: bias |
|---|---:|---:|---:|
| last month | 2.25 | +0.12 | +1.53 |
| 3-month average | 1.82 | +0.17 | +2.35 |
| 12-month average | **1.80** | +0.39 | +4.12 |

The 12-month average wins overall and is used for the next three months
([retention_forecast.csv](results/retention_forecast.csv)), but after a rate increase it expects about 4 points
more customers to stay than do, for half a year. Scores per province and horizon:
[retention_backtest.csv](results/retention_backtest.csv).

## What it finds

From [the brief](results/brief.md), last 12 months to 2026-06-30:

- 22,110 policies in force, $48.4M written, loss ratio 64.2%, 87.5% of renewals kept.
- Ontario auto retention fell from 87.2% to 76.7% in the year after its rate increase (4.0% to 14.0% offered);
  Ontario has 2.5% fewer policies in force than a year earlier.
- Alberta home's loss ratio was 551% in the month of the hail and 107.5% for 2024 (51.2% in 2023).
- Digital customers renew 78.3%, broker customers 89.3%.
- 165 claims ($2.3M) from April to June were not reported by 2026-06-30. With them the last three months' loss ratio
  is 63.1%, not the 43.8% the reported claims show.

## The dashboard

The site's [Provincial book health page](https://sky-five.github.io/ridgeline-analytics/book-health/) shows growth,
loss ratio and retention by province, Alberta home's claims with the hail month and its rate increase marked, both
rate increases month by month, retention by channel, each rule's one-month-ahead miss by province and its forecast
against what happened (pick a province), the next three months' forecast, the monthly loss ratio with the
unfinished months marked, and the brief.

`report.py` builds the page's 10 `reporting.book_*` tables from the committed results only, so the page does not
move with the nightly build. Two results files exist for it: [segment_watch.csv](results/segment_watch.csv)
(Alberta home and Ontario auto by month) and [backtest_path.csv](results/backtest_path.csv) (each rule's
one-month-ahead forecast and what happened, 1,134 rows).

`tests/book_health/test_report.py` checks that the tables add up: provinces to the book, the two segments to the
rate actions' before/after retention, the one-month-ahead path to its scores, the forecast to the summary, the
page's brief to brief.md. It also runs every query on the page against the exported tables, checks every column a
chart or table names, and ties the page's marked dates and fixed words to the simulation's constants.
