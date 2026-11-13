---
title: Report reconciliation
---

A learning project on **simulated** project, resource and time data, separate from the roofing-software company on
the rest of this site. Before three reports go to their owners for user acceptance testing (UAT), each one is
checked against its source: are the row counts right, do the totals match, is the data fresh, and is every column
documented. Code and tests:
[report_reconciliation/](https://github.com/sky-five/ridgeline-analytics/tree/main/report_reconciliation). Like the
vehicle auction, these numbers come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.recon_summary
```

<BigValue data={summary} value=reports_passing title="Reports passing" fmt=num0/>
<BigValue data={summary} value=checks_passing title="Checks passing" fmt=num0/>
<BigValue data={summary} value=faults_caught title="Planted faults caught" fmt=num0/>
<BigValue data={summary} value=owner_items_open title="Owner items open" fmt=num0/>

The source has <Value data={summary} column=timesheet_entries fmt=num0/> timesheet entries for 25 working weeks, of which <Value data={summary} column=approved_entries fmt=num0/> are approved: <Value data={summary} column=approved_hours fmt=num2/> hours and <Value data={summary} column=approved_cost fmt=usd2/> of cost once each entry is priced at the rate in effect on its work date. Checks ran at <Value data={summary} column=as_of/>, an hour after the marts were built.

## Pass or fail, by report and check

Each mart is built in SQL. The checks compare it with numbers recomputed in pandas straight from the source tables,
so a mistake in the SQL can't hide by being repeated in the check.

| Check | Passes when |
|---|---|
| Row count | One mart row per grain key the source produces, and no other keys |
| Totals | Every measure's total matches the source, and no single key is off by more than a cent |
| Refresh age | Every input was extracted within 24 hours, and the mart was built after the newest extract |
| Lineage | Every mart column has a lineage entry, and every source column named exists |

```sql by_report
select title, mart,
       max(case when check_name = 'row_count' then status end) as row_count,
       max(case when check_name = 'totals' then status end) as totals,
       max(case when check_name = 'refresh_age' then status end) as refresh_age,
       max(case when check_name = 'lineage' then status end) as lineage
from ridgeline.recon_checks
group by report_sort, title, mart
order by report_sort
```

<DataTable data={by_report}>
  <Column id=title title="Report"/>
  <Column id=mart title="Mart"/>
  <Column id=row_count title="Row count"/>
  <Column id=totals title="Totals"/>
  <Column id=refresh_age title="Refresh age"/>
  <Column id=lineage title="Lineage"/>
</DataTable>

What each check found:

```sql details
select title, check_name, status, detail
from ridgeline.recon_checks
order by report_sort, check_sort
```

<DataTable data={details} rows=all>
  <Column id=title title="Report"/>
  <Column id=check_name title="Check"/>
  <Column id=status title="Result"/>
  <Column id=detail title="Detail" wrap=true/>
</DataTable>

## Planted faults

A check that has never failed proves little. The build can plant one known mistake at a time, and the kit runs every
check again. Each row is one fault; each report column lists the checks that failed. CI fails if any fault gets
through every check.

```sql matrix
select fault, what,
       max(case when report = 'project_hours' then failed_checks end) as project_hours,
       max(case when report = 'utilisation' then failed_checks end) as utilisation,
       max(case when report = 'budget_burn' then failed_checks end) as budget_burn
from ridgeline.recon_faults
group by fault_sort, fault, what
order by fault_sort
```

<DataTable data={matrix} rows=all>
  <Column id=fault title="Fault"/>
  <Column id=what title="What goes wrong" wrap=true/>
  <Column id=project_hours title="Project hours"/>
  <Column id=utilisation title="Utilisation"/>
  <Column id=budget_burn title="Budget burn"/>
</DataTable>

The rate join fan-out is the quiet one: every mart still has the right number of rows, and only the totals check
sees that people with a raise are counted once per rate. The undocumented column was added to the utilisation mart
only, so the other two reports rightly pass.

## Open UAT items

The automated items are ticked from the checks above. The rest need the report owner and stay open until a name is
filled in.

```sql open_items
select title, item, who, definitions
from ridgeline.recon_uat
where not done
order by report_sort, item_sort
```

<DataTable data={open_items} rows=all>
  <Column id=title title="Report"/>
  <Column id=item title="Item" wrap=true/>
  <Column id=who title="Waiting on"/>
  <Column id=definitions title="Definitions to agree" wrap=true/>
</DataTable>

The owner traces these rows, the three largest in each report, back to the source system by hand:

```sql samples
select title, row_key, measure, value
from ridgeline.recon_samples
order by report_sort, row_sort
```

<DataTable data={samples} rows=all>
  <Column id=title title="Report"/>
  <Column id=row_key title="Row (grain key)"/>
  <Column id=measure title="Measure"/>
  <Column id=value title="Value" fmt=num2/>
</DataTable>
