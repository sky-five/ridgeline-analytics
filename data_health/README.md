# Event contracts

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
| `batches.py` | Cuts the history into daily batches, and 18 named faults that each break a clean batch in one way. |

The rules: every column present, no extra columns, the right types; no empty ids, types or timestamps;
`event_id` well formed, unique (also against ids already loaded, so a replayed batch fails) and carrying the
same account number as `account_id`; `account_id` well formed and a real account; a known event type; values
only on proposals and in range; no event before the account signed up or outside the batch day; and
`updated_at` equal to `occurred_at`, because events are never edited.

## How it's tested

`tests/data_health/` has 31 tests. All 623,164 events up to 2026-06-30 meet the contract, and so do four
sample daily batches. Each of the 18 injected faults fails on exactly the rule meant to catch it and no other,
and every rule is tripped by at least one test. CI also runs `python -m data_health` on yesterday's batch.

This checks one feed and one day at a time. It does not yet grade volume or freshness; that is the table
health scorecard, next on the list.
