# Migration kit: full reload to incremental, proven with a parallel run

Moving a table from an old load pattern to a new one is only done when you can show the new table holds the
same data as the old one. This kit does that on a real, public, constantly changing feed: the USGS list of
earthquakes of magnitude 2.5+ in the past 30 days (public domain). Events arrive all day, get revised
(magnitude, location, status `automatic` -> `reviewed`), are occasionally deleted, and drop off the end of the
30-day window.

```bash
python -m migration_kit           # replay snapshots/ through both loaders, write results/
python -m migration_kit --fetch   # add a fresh snapshot of the feed first
python -m migration_kit --check   # fail if results/ is out of date (CI)
python -m migration_kit --live    # committed snapshots + one fetched now, not saved; fail on any mismatch (nightly)
```

Only DuckDB is needed.

## The two loaders

| Table | Load pattern |
|---|---|
| `legacy.earthquakes` | Truncate and reload the whole feed every time. Keeps no history: an event that ages out of the window is gone. |
| `target.earthquakes` | Incremental `MERGE` keyed on `id`. A change-capture step hashes the 22 feed columns of each incoming row and compares with the stored hash, so only new and changed rows are written. Each change goes to `target.earthquake_changes` with the columns that moved. Rows that leave the feed stay, with `in_feed = false` and `left_feed_as` = `aged_out` (older than the window) or `deleted` (dropped inside the window). `target.load_log` has one row per load. |

A third strategy, `event_time_watermark`, is the common shortcut: load only events newer than the newest one
already loaded. It never sees revisions or removals. It runs as a negative control, and the reconciliation must
fail on it.

## Reconciliation

`reconcile.py` compares the legacy table with the target rows still in the feed, after every load:

| Check | Passes when |
|---|---|
| row_count | Same number of rows |
| keys | No `id` on one side only |
| rows | Every shared `id` has identical values in all 22 columns; the hash is recomputed on both sides, not read from the loader, and mismatches are counted per column |
| aggregates | Rows by status, rows by event type, sum of magnitude, first and last event time |

`results/reconciliation.md` has the table for every load of both strategies.

## Retirement checklist

`results/retirement_checklist.md` is generated, not ticked by hand: column lineage (every legacy column mapped
to a target column, plus the bookkeeping columns the target adds), at least 3 loads in a row with zero
differences, the negative control failing, every row that left the feed kept in the target, and no file outside
the kit still naming `legacy.earthquakes`. The last two items (downstream owners moved, legacy table dropped
after a grace period) need a person and stay open.

## Results on the committed snapshots

Four snapshots fetched on 2026-11-13 between 00:23 and 00:43 UTC (1,985 events in the first, 1,983 in the
last). Over the three later loads the merge wrote 4 revisions and marked 2 events aged out, and left every other
row untouched. The revisions were real: two touched only the feed's `updated` time, and in the last snapshot two
events were relocated (time, latitude, longitude, depth and their error columns moved), one of them also going
from `automatic` to `reviewed`. The target and the legacy table matched on all
four checks after all 4 loads, and the target still holds the 2 aged-out events the legacy table dropped.

The event-time watermark failed reconciliation on 3 of 4 loads: by the last one 3 rows were stale and 2 aged-out
events were still counted as in the feed. The snapshots are minutes apart, so the changes are few; `--live` runs
the same check in the nightly workflow on that day's feed.

## Tests

`tests/migration_kit/` builds snapshots from the committed real one with planted changes (5 new events, then 4 more, 3
magnitude revisions, 2 status changes, 1 deletion inside the window, the events past the new window aged out)
and checks the merge finds exactly those, names the changed columns, keeps and labels the rows that left,
treats a reloaded snapshot as no change, logs an event that comes back as `returned`, and that the
reconciliation catches the watermark loader and a target row edited behind the loader's back. One test
checks the committed results match the committed snapshots.
