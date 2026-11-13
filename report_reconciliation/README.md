# Report reconciliation kit

Before a report goes to its owners for user acceptance testing (UAT), someone has to show that its numbers come
from the source and nothing was lost, doubled or left stale on the way. This kit does that for three reports
built from synthetic project, resource and time data, all in DuckDB.

```bash
python -m report_reconciliation           # build, check, plant each fault, write results/
python -m report_reconciliation --check   # fail if results/ is stale, a check fails or a fault is missed (CI)
```

## The data and the reports

`simulate.py` makes seeded source tables for 25 working weeks (2026-01-05 to 2026-06-26): 18 projects (2
internal and not billable, 3 closed during the half), 30 people with a role and weekly capacity (some join
mid-half), 41 effective-dated cost rates (11 people get a raise), and 4,800 timesheet entries, of which 4,598
are approved, 84 rejected and 118 still submitted. `source.extract_log` says when each table was extracted.

`build.py` goes source -> `staging.timesheet_costed` (approved entries priced at the rate in effect on the
work date) -> three marts:

| Report | Mart | Grain | Rows |
|---|---|---|---|
| Project hours and cost by month | `mart.project_hours_monthly` | project, month | 92 |
| Resource utilisation by week | `mart.resource_utilisation_weekly` | person, week | 708 |
| Project budget burn | `mart.project_budget_burn` | project | 18 |

## The checks

`checks.py` compares each mart (built in SQL) with numbers recomputed in pandas straight from the source tables
(`reports.py`, which prices entries with `merge_asof` instead of the SQL range join):

| Check | Passes when |
|---|---|
| row_count | One mart row per grain key the source produces, and no other keys |
| totals | Every measure's total matches the source, and no single key is off by more than a cent |
| refresh_age | Every input was extracted within 24 hours of the check, and the mart was built after the newest extract |
| lineage | Every mart column has a lineage entry (or is bookkeeping), and every source column named exists in the catalog |

On the committed run all three reports pass all four checks: 22,538.25 approved hours and $2,234,622.68 of
cost in both the project and the budget reports, and the same hours in the utilisation report.

## Planted faults

`build.py` can plant one known mistake at a time; `results/reconciliation.md` shows which checks fail:

| Fault | What goes wrong | Caught by |
|---|---|---|
| rate_join_fan_out | Rates joined on person only, so people with a raise are counted twice | totals (row counts still match) |
| rejected_included | The approved-only filter is dropped | totals |
| closed_projects_dropped | An inner join to active projects drops closed ones | row_count and totals |
| stale_extract | The timesheet extract is 30 hours old | refresh_age |
| undocumented_column | A new mart column with no lineage entry | lineage, on the report that has it |

`--check` fails if any fault gets through. While the kit was being built, the totals check also found a bug in
the simulator itself: a raise dated before a late joiner's start date, which the two pricing methods read
differently.

## UAT sign-off checklist

`results/uat_checklist.md` is generated per report. The four automated items are ticked from the checks. Three
items need the report owner and stay open until a name is filled in `uat.SIGN_OFF`: tracing the listed sample
rows (the three largest) back to the source, agreeing with the written definitions, and signing off.

## Tests

`tests/report_reconciliation/` checks that a correct build passes everything, that each planted fault fails
exactly the expected checks, and that the checks catch hand edits: a 2-cent change in one mart row, one deleted
row, a mart built before a newer extract arrived (inside the SLA), and a lineage entry naming a column that does
not exist. One test checks an entry on a raise date is priced at the new rate; another that the committed
results are current.
