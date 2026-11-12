# Data health

Two checks on what the simulated source systems deliver each day: a contract for the product-event feed, and
a health scorecard for every source table.

## Event contracts

The simulator's product-event telemetry (`events`: logins, measurement orders, proposals, jobs, paid invoices)
is the biggest and least checked feed in the warehouse. dlt's schema contract only freezes column types, so a
batch with a made-up event type, a proposal value in cents or an event from tomorrow would still load. This
folder writes the contract down as data and checks each day's batch against it before it counts.

```bash
python -m data_health                          # check the 2026-06-30 batch, exit 1 if any rule fails
python -m data_health --day 2026-11-09         # any day in the simulated history
python -m data_health --inject value_in_cents  # break the batch on purpose and watch it fail
```

| File | What it does |
|---|---|
| `contracts.py` | The contract: six columns and their types, six event types (only the two proposal types carry `value_usd`, whole dollars from $100 to $250,000), and 16 rules. `check_batch` returns one row per broken rule and event, so a bad batch shows every problem at once. |
| `batches.py` | Cuts the history into daily batches, and 18 named faults that each break a clean batch in one way. Also the five table faults used by the scorecard. |
| `scorecard.py` | The table health scorecard, below. |

The rules: every column present, no extra columns, the right types; no empty ids, types or timestamps;
`event_id` well formed, unique (also against ids already loaded, so a replayed batch fails) and carrying the
same account number as `account_id`; `account_id` well formed and a real account; a known event type; values
only on proposals and in range; no event before the account signed up or outside the batch day; and
`updated_at` equal to `occurred_at`, because events are never edited.

### How it's tested

`tests/data_health/test_event_contracts.py` has 31 tests. All 623,164 events up to 2026-06-30 meet the contract, and so do four
sample daily batches. Each of the 18 injected faults fails on exactly the rule meant to catch it and no other,
and every rule is tripped by at least one test. CI also runs `python -m data_health` on yesterday's batch.

This checks one feed and one day at a time. Volume and freshness are the scorecard's job.

## Table health scorecard

A load can succeed and still bring a bad day: late, half missing, loaded twice, or with a column suddenly
blank. The scorecard grades each of the 11 source tables' batch for one day as green, amber or red, with a
one-line reason, against that table's own last 28 days.

```bash
python -m data_health.scorecard                         # grade the 2026-06-30 batches, exit 1 if any table is red
python -m data_health.scorecard --day 2026-11-09
python -m data_health.scorecard --inject half_batch --table measurement_orders
```

A batch is what an incremental load picks up that day: rows whose `updated_at` falls on it, as they were then.
`arrivals()` rebuilds them from the simulator one day at a time, so a support ticket that opens, gets a reply
and is solved shows up in three batches. (The final tables only keep each row's latest version; a baseline
taken from them undercounts past days for every table whose rows change.)

| Check | Compared with | Amber | Red |
|---|---|---|---|
| Freshness: hours from the last row to the end of the day | the longest gap between rows in 28 days, at least 24 h | over it | over 3 times it |
| Volume: rows in the day's batch | the daily counts of the last 28 days | over 3 spreads away | over 6 |
| Null rate: share of the day's rows empty, per column | that column's share in the last 28 days | over 3 spreads more | over 6 |

A spread is the standard deviation of the usual days, but never less than random noise allows for a table of
that size (the square root of the mean for counts; the binomial spread for the day's row count, and at least
one percentage point, for empties). The primary key and `updated_at` are not null-checked. A table's grade is
its worst check, and its reason is that check's sentence, e.g. `199 rows, 9.8 spreads below the usual 412 a day`.

The site build writes the scorecard for the as-of day to `reporting.table_health`, shown on the
[Data health page](https://sky-five.github.io/ridgeline-analytics/data-health/). CI runs it on yesterday's
batches and fails on any red.

### How it's tested

On clean simulated data, 2,013 table-days (11 tables, 2026-05-11 to 2026-11-09) give no red and 39 ambers
(1.9%). Ambers are things worth a look: a sparse CRM table quiet for a week, a seasonal drop in leads.

Five injected faults, each applied to one table on 2026-06-30:

| Fault | Check | Red on |
|---|---|---|
| `stuck_loader`: nothing for 4 days | freshness | 9 of 11 tables (CRM calls go amber; CRM deals often go a week without a row) |
| `half_batch`: half the day's rows missing | volume | events, measurement orders, contractor leads |
| `empty_batch`: the load brought nothing | volume | the same three, plus invoices |
| `double_load`: the batch appended twice | volume | the same three, plus invoices and accounts |
| `account_id_dropped`: a fifth of rows lose `account_id` | null rate | 8 tables: every table with a non-key account_id that had rows that day (CRM deals had none) |

So a table with four rows a day cannot show a half batch: two rows instead of four is within normal noise.
That is a limit of daily counts on small tables, written down rather than hidden by tighter thresholds that
would flag ordinary days.

`tests/data_health/test_scorecard.py` has 38 tests: two weeks of clean days (154 table-days) have no red;
each fault turns its check red on the tables listed for it and leaves every other table's grade unchanged;
hand-made hourly tables pin each threshold; and the command exits 1 on a red table.

## How to read the page

The [Data health page](https://sky-five.github.io/ridgeline-analytics/data-health/) opens with five steps for
someone who uses the numbers but did not build them: did the pipelines run, does today's data look normal,
read the reason rather than the colour (the table that needs the most attention is quoted live from the
scorecard), check the dbt build, and look up any word. What each grade means for using the numbers is spelled
out: green use them, amber read the reason first, red do not quote numbers built on that table for that day.

The page ends with a glossary of its 16 terms (`glossary.py`, written to `reporting.data_health_glossary` by
the site build). Its thresholds are not typed in: the scorecard's come from `scorecard.py` and the pipeline
freshness hours from the dbt source configs, which the `source_loads` table now reads too, so the page, the
glossary and the checks cannot disagree. Business metrics are defined on the separate
[Metric glossary](https://sky-five.github.io/ridgeline-analytics/metrics/).

```bash
python -m data_health.glossary   # print it
```

`tests/data_health/test_glossary.py` has 9 tests: every column and tile title on the page has a glossary
entry, the quoted thresholds equal the code's and change when it does, sources with different freshness
hours are an error, and the walkthrough comes first and links to the glossary.
