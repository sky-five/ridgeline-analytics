---
title: Margin risk
---

**Simulated data**, separate from the roofing-software company on the rest of this site: a margin book of <Value data={summary} column=accounts/>
fictional brokerage accounts (<Value data={summary} column=margin_accounts/> allowed to borrow) holding 30 fictional securities in 6 sectors, every weekday
from <Value data={summary} column=first_day/> to <Value data={summary} column=as_of/>. A sector sell-off, a stock split
and two broken feed files are planted on purpose. The page shows the book's risk day by day, the margin calls after
the sell-off, where the collateral is concentrated, daily P&L, and the days the mart does not agree with the ledger.

Code, dbt models and tests: [margin_risk/](https://github.com/sky-five/ridgeline-analytics/tree/main/margin_risk).
The simulation is seeded, so these numbers do not move with the nightly build.

```sql summary
select * from ridgeline.margin_summary
```

## The book on <Value data={summary} column=as_of/>

<BigValue data={summary} value=loan title="Margin loans" fmt=usd0/>
<BigValue data={summary} value=market_value title="Securities held" fmt=usd0/>
<BigValue data={summary} value=collateral_coverage title="Collateral coverage" fmt=num2/>
<BigValue data={summary} value=margin_utilisation title="Margin utilisation" fmt=pct1/>
<BigValue data={summary} value=borrowers title="Borrowers"/>
<BigValue data={summary} value=concentrated_borrowers title="Concentrated borrowers"/>

Collateral coverage is borrowers' market value less each holding's maintenance requirement (25% or 30% by sector,
40% for a holding over half the account), over the loan: below 1 the book could not cover its loans at the
requirement. Utilisation is the loan over what borrowers could borrow at the 50% initial rate.

## Coverage and utilisation by day

```sql daily
select as_of_date, collateral_coverage, margin_utilisation, loan, market_value
from ridgeline.margin_daily order by as_of_date
```

<LineChart data={daily} x=as_of_date y=collateral_coverage yFmt=num2 title="Collateral coverage"
  colorPalette={['#111827']}>
  <ReferenceArea xMin='2026-03-16' xMax='2026-03-20' label="Sell-off" color=warning/>
</LineChart>

<LineChart data={daily} x=as_of_date y=margin_utilisation yFmt=pct0 title="Margin utilisation"
  colorPalette={['#C2410C']}>
  <ReferenceArea xMin='2026-03-16' xMax='2026-03-20' label="Sell-off" color=warning/>
</LineChart>

<LineChart data={daily} x=as_of_date y={['loan', 'market_value']} yFmt=usd0k
  title="Margin loans and securities held, whole book" colorPalette={['#C2410C', '#9CA3AF']}/>

## Margin calls around the sell-off

From <Value data={summary} column=shock_from/> to <Value data={summary} column=shock_to/> the
sector <Value data={summary} column=shock_sector/> fell <Value data={summary} column=fall_mildest fmt=pct1/>
to <Value data={summary} column=fall_worst fmt=pct1/> by security; market P&L for the week
was <Value data={summary} column=market_pnl_week fmt=usd0/>. A call starts the first weekday an account's equity is
below its requirement and lasts until it is back above.

<BigValue data={summary} value=real_calls title="Margin calls"/>
<BigValue data={summary} value=accounts_called title="Accounts called"/>
<BigValue data={summary} value=calls_before_shock title="Calls before the sell-off"/>
<BigValue data={summary} value=deficit_at_call title="Short on the day of the call" fmt=usd0/>

```sql calls_daily
select as_of_date, real_calls as "Calls started", calls_on_a_break as "Started on a day that does not reconcile",
       accounts_in_call
from ridgeline.margin_calls_daily order by as_of_date
```

<BarChart data={calls_daily} x=as_of_date y={['Calls started', 'Started on a day that does not reconcile']}
  title="Margin calls started per weekday" colorPalette={['#111827', '#D1D5DB']}>
  <ReferenceArea xMin='2026-03-16' xMax='2026-03-20' label="Sell-off" color=warning/>
</BarChart>

Every real call is in an account over half in one security, and in every one that security is a semiconductor:
the calls follow where the book is concentrated, not just which sector fell.
The <Value data={summary} column=calls_on_a_break/> grey calls start on <Value data={reconciliation} column=as_of_date row=0/>,
the day a positions file was wrong (see the reconciliation below); they are not real and are left out of the counts.

```sql outcomes
select resolution_label, calls, deficit_at_call, median_weekdays from ridgeline.margin_call_outcomes
order by calls desc
```

<DataTable data={outcomes} rows=all>
  <Column id=resolution_label title="How the call ended"/>
  <Column id=calls title="Calls"/>
  <Column id=deficit_at_call title="Short on the day of the call" fmt=usd0/>
  <Column id=median_weekdays title="Median weekdays in call" fmt=num0/>
</DataTable>

```sql calls
select call_date, account_id, top_symbol, deficit_at_call, max_deficit, weekdays_in_call, resolution_label,
       case when real then '' else 'does not reconcile' end as note
from ridgeline.margin_calls order by call_date, account_id
```

<DataTable data={calls} rows=15 search=true>
  <Column id=call_date title="Called"/>
  <Column id=account_id title="Account"/>
  <Column id=top_symbol title="Largest holding"/>
  <Column id=deficit_at_call title="Short at call" fmt=usd0/>
  <Column id=max_deficit title="Most short" fmt=usd0/>
  <Column id=weekdays_in_call title="Weekdays"/>
  <Column id=resolution_label title="Ended by"/>
  <Column id=note title="Note"/>
</DataTable>

## Concentration by security and sector

```sql sectors
select as_of_date, sector, share_of_borrower_value from ridgeline.margin_sectors order by as_of_date, sector
```

<AreaChart data={sectors} x=as_of_date y=share_of_borrower_value series=sector yFmt=pct0 type=stacked100
  title="Sectors as a share of borrowers' securities"/>

```sql snapshots
select distinct snapshot, snapshot_label, snapshot_sort from ridgeline.margin_concentration order by snapshot_sort
```

<Dropdown data={snapshots} name=snapshot value=snapshot label=snapshot_label title="Day" defaultValue="last day"/>

```sql by_symbol
select symbol, sector, share_of_borrower_value, borrower_market_value, borrowers_holding, borrowers_concentrated
from ridgeline.margin_concentration
where snapshot = '${inputs.snapshot.value}'
order by share_of_borrower_value desc
```

<BarChart data={by_symbol} x=symbol y=share_of_borrower_value series=sector swapXY=true sort=false yFmt=pct1
  title="Share of borrowers' securities by security"/>

<DataTable data={by_symbol} rows=10>
  <Column id=symbol title="Security"/>
  <Column id=sector title="Sector"/>
  <Column id=share_of_borrower_value title="Share" fmt=pct1/>
  <Column id=borrower_market_value title="Held by borrowers" fmt=usd0/>
  <Column id=borrowers_holding title="Borrowers holding"/>
  <Column id=borrowers_concentrated title="Over half an account"/>
</DataTable>

Semiconductors were <Value data={summary} column=shock_sector_share fmt=pct1/> of borrowers' securities on the last
day; the largest single holding was <Value data={summary} column=largest_symbol/>
(<Value data={summary} column=largest_share fmt=pct1/>). Pick a day to see the sector shrink through the sell-off.

## Daily P&L

```sql pnl
select as_of_date, market_pnl, interest_income, deposits, unexplained
from ridgeline.margin_daily where market_pnl is not null order by as_of_date
```

<BarChart data={pnl} x=as_of_date y=market_pnl yFmt=usd0k title="Market P&L per weekday (split-adjusted)"
  colorPalette={['#111827']}/>

<BigValue data={summary} value=market_pnl title="Market P&L, whole period" fmt=usd0/>
<BigValue data={summary} value=interest_income title="Margin interest charged" fmt=usd0/>
<BigValue data={summary} value=worst_day_pnl title="Worst day" fmt=usd0/>

P&L is the change in equity explained by prices (split-adjusted), deposits and interest. What is left over is
"unexplained", and it should be zero:

<BarChart data={pnl} x=as_of_date y=unexplained yFmt=usd0k title="Unexplained change in equity"
  colorPalette={['#C2410C']}/>

Each fault shows twice, on its day and again, reversed, the next. The P&L check only says something moved; the
ledger says which day is wrong.

## Does the mart agree with the ledger

The reconciliation compares <Value data={summary} column=account_days fmt=num0/> account-days of mart market value
and cash with the books of record and flags <Value data={summary} column=account_days_flagged/> of
them, on <Value data={summary} column=flagged_days/> days. Against what was planted: <Value data={summary} column=missed/>
missed, <Value data={summary} column=false_alarms/> false alarms.

```sql reconciliation
select as_of_date, market_value_drift, cash_drift, accounts_broken, planted, cause
from ridgeline.margin_reconciliation order by as_of_date
```

<DataTable data={reconciliation} rows=all>
  <Column id=as_of_date title="Day"/>
  <Column id=market_value_drift title="Market value drift" fmt=usd0/>
  <Column id=cash_drift title="Cash drift" fmt=usd0/>
  <Column id=accounts_broken title="Accounts flagged"/>
  <Column id=planted title="Accounts planted"/>
  <Column id=cause title="Cause" wrap=true/>
</DataTable>

The positions file for <Value data={summary} column=repeated_file_date/> was
loaded <Value data={summary} column=repeated_file_loads/> times (<Value data={summary} column=repeated_file_raw_rows fmt=num0/>
rows for <Value data={summary} column=repeated_file_rows_kept fmt=num0/> holdings). Staging keeps the latest load,
so the day reconciles; counted twice it would be <Value data={summary} column=drift_if_counted_twice fmt=usd0/>
over the ledger. A flagged day's totals should not be reported until its break is explained.
