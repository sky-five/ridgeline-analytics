---
title: Cost per issued lead
---

**Simulated data**, separate from the roofing-software company on the rest of this site: a lead-generation
operation for <Value data={summary} column=clients/> home-service clients with eleven campaigns on a search and a
social platform, from <Value data={summary} column=first_day/> to <Value data={summary} column=as_of/>. Three
exports arrive every day (ad platforms, call tracking, CRM), <Value data={summary} column=files fmt=num0/> files in
all, with messy identifiers: phones typed four ways, campaigns spelt three ways, restated spend, click ids that get
lost. A pipeline (Bronze in Python, Silver and Gold in dbt on DuckDB) stitches them into one row per lead. The page
shows what an issued lead and a demo cost by client, campaign and week, how each lead was matched to a campaign,
the load audit, and four silent failures planted to check the tests catch them.

Code, dbt models and tests: [lead_cost/](https://github.com/sky-five/ridgeline-analytics/tree/main/lead_cost).
The simulation is seeded, so these numbers do not move with the nightly build.

```sql summary
select * from ridgeline.lead_cost_summary
```

## The quarter

<BigValue data={summary} value=spend title="Ad spend" fmt=usd0/>
<BigValue data={summary} value=issued_leads title="Issued leads with a campaign" fmt=num0/>
<BigValue data={summary} value=cost_per_issued_lead title="Cost per issued lead" fmt=usd2/>
<BigValue data={summary} value=cost_per_demo title="Cost per demo" fmt=usd2/>
<BigValue data={summary} value=unattributed_share title="Leads with no campaign" fmt=pct1/>

An **issued** lead is one worked in the CRM and sent to the client's rep with an appointment; it becomes a
**demo** when the rep runs the in-home presentation. Costs divide the spend by the issued leads and demos Gold can
tie to a campaign. <Value data={summary} column=crm_records fmt=num0/> CRM records became
<Value data={summary} column=leads fmt=num0/> leads (a person who fills in the form and also phones is one lead).

## By client

```sql clients
select * from ridgeline.lead_cost_clients order by cost_per_issued_lead
```

```sql client_costs
select client_label, 'Per issued lead' as cost, cost_per_issued_lead as dollars from ridgeline.lead_cost_clients
union all
select client_label, 'Per demo', cost_per_demo from ridgeline.lead_cost_clients
order by 1, 2 desc
```

<BarChart data={client_costs} x=client_label y=dollars series=cost type=grouped yFmt=usd0
  title="Cost per issued lead and per demo" colorPalette={['#1F2937', '#9CA3AF']}/>

<DataTable data={clients} rows=all>
  <Column id=client_label title="Client"/>
  <Column id=spend title="Spend" fmt=usd0/>
  <Column id=paid_leads title="Leads with a campaign" fmt=num0/>
  <Column id=issued_rate title="Share issued" fmt=pct0/>
  <Column id=issued_leads title="Issued leads" fmt=num0/>
  <Column id=demos title="Demos" fmt=num0/>
  <Column id=cost_per_issued_lead title="Per issued lead" fmt=usd2/>
  <Column id=cost_per_demo title="Per demo" fmt=usd2/>
  <Column id=unattributed_leads title="Leads with no campaign" fmt=num0/>
</DataTable>

## By campaign

```sql campaigns
select * from ridgeline.lead_cost_campaigns order by client_label, platform, theme
```

```sql campaign_chart
select campaign_label, platform, cost_per_lead, cost_per_issued_lead
from ridgeline.lead_cost_campaigns order by cost_per_issued_lead desc
```

<BarChart data={campaign_chart} x=campaign_label y=cost_per_issued_lead series=platform swapXY=true sort=false
  yFmt=usd0 title="Cost per issued lead by campaign" colorPalette={['#1F2937', '#C2410C']}/>

```sql platforms
select platform, sum(spend) as spend, sum(leads) as leads, sum(issued_leads) as issued_leads, sum(demos) as demos,
       sum(spend) / sum(leads) as cost_per_lead, sum(spend) / sum(issued_leads) as cost_per_issued_lead,
       sum(issued_leads) / sum(leads) as issued_rate
from ridgeline.lead_cost_campaigns group by platform order by platform
```

A social lead is cheaper than a search lead, but fewer of them get issued, so the gap shrinks or reverses per issued
lead:

{#each platforms as p}

- <b>{p.platform}</b>: ${p.cost_per_lead.toFixed(2)} a lead, {(100 * p.issued_rate).toFixed(0)}% issued, ${p.cost_per_issued_lead.toFixed(2)} per issued lead.

{/each}

<DataTable data={campaigns} rows=all>
  <Column id=client_label title="Client"/>
  <Column id=platform title="Platform"/>
  <Column id=theme title="Campaign"/>
  <Column id=clicks title="Clicks" fmt=num0/>
  <Column id=spend title="Spend" fmt=usd0/>
  <Column id=leads title="Leads" fmt=num0/>
  <Column id=issued_rate title="Share issued" fmt=pct0/>
  <Column id=cost_per_lead title="Per lead" fmt=usd2/>
  <Column id=cost_per_issued_lead title="Per issued lead" fmt=usd2/>
  <Column id=cost_per_demo title="Per demo" fmt=usd2/>
</DataTable>

## Week by week

```sql client_choice
select distinct client_label from ridgeline.lead_cost_weekly order by client_label
```

<Dropdown data={client_choice} name=client value=client_label title="Client" defaultValue="North Roofing"/>

```sql weekly
select * from ridgeline.lead_cost_weekly where client_label = '${inputs.client.value}' order by week
```

```sql weekly_costs
select week, 'Per issued lead' as cost, cost_per_issued_lead as dollars from ridgeline.lead_cost_weekly
where client_label = '${inputs.client.value}' and week_note not in ('starts mid-week', 'two days only')
union all
select week, 'Per demo', cost_per_demo from ridgeline.lead_cost_weekly
where client_label = '${inputs.client.value}' and week_note = ''
order by week
```

<LineChart data={weekly_costs} x=week y=dollars series=cost yFmt=usd0 title="Cost per issued lead and per demo, full weeks"
  colorPalette={['#1F2937', '#9CA3AF']}/>

Each lead counts in the week it came in. A lead is issued one to three days later and its demo comes two to ten days
after that, so the last weeks are not finished: the chart leaves out the cost per demo from the week of 2026-06-15
and both lines for the two part weeks at the ends. A client has a few dozen leads a week, so one week's cost moves a lot;
the quarter's figures above are the ones to compare.

<DataTable data={weekly} rows=all>
  <Column id=week title="Week of"/>
  <Column id=spend title="Spend" fmt=usd0/>
  <Column id=paid_leads title="Leads with a campaign" fmt=num0/>
  <Column id=issued_leads title="Issued" fmt=num0/>
  <Column id=demos title="Demos" fmt=num0/>
  <Column id=cost_per_issued_lead title="Per issued lead" fmt=usd2/>
  <Column id=cost_per_demo title="Per demo" fmt=usd2/>
  <Column id=week_note title="Note"/>
</DataTable>

## How each lead found its campaign

```sql attribution
select client_label, attributed_by_label, attributed_by_sort, sum(leads) as leads, sum(issued_leads) as issued_leads
from ridgeline.lead_cost_attribution group by all order by attributed_by_sort, client_label
```

```sql attribution_total
select attributed_by_label, came_by_label, sum(leads) as leads, sum(issued_leads) as issued_leads
from ridgeline.lead_cost_attribution group by all
order by min(attributed_by_sort), came_by_label desc
```

Gold tries three joins in order: a click id on any of the lead's CRM records, the click id call tracking saw when
the lead phoned, the tracking number the lead called. The first one that matches decides the campaign.

<BarChart data={attribution} x=client_label y=leads series=attributed_by_label sort=false yFmt=num0
  title="Leads by how the campaign was found" colorPalette={['#1F2937', '#4B5563', '#9CA3AF', '#C2410C']}/>

<DataTable data={attribution_total} rows=all>
  <Column id=attributed_by_label title="Matched by"/>
  <Column id=came_by_label title="Came in by"/>
  <Column id=leads title="Leads" fmt=num0/>
  <Column id=issued_leads title="Issued" fmt=num0/>
</DataTable>

<Value data={summary} column=unattributed_leads fmt=num0/> leads match none of the three. Checked against the
simulator, <Value data={summary} column=organic_leads fmt=num0/> of them never clicked an ad (organic). The other
<Value data={summary} column=paid_unattributed fmt=num0/> did (<Value data={summary} column=paid_unattributed_issued fmt=num0/> of them were issued),
but came by web form, lost their click id on the way to the CRM, and never phoned: no join can recover them, so their
cost lands on the leads that can be attributed. Against the same truth, <Value data={summary} column=wrong_campaign fmt=num0/>
leads are matched to the wrong campaign and <Value data={summary} column=outcome_mismatches fmt=num0/> have the wrong
issued or demo outcome.

## The load audit

Bronze lands every file as delivered and writes one audit row per file: the rows its manifest declared, the rows
that actually landed, and a checksum. A short file or a file delivered twice shows up here before it reaches a cost.

```sql exports
select * from ridgeline.lead_cost_exports order by source_sort
```

<DataTable data={exports} rows=all>
  <Column id=source_label title="Export"/>
  <Column id=files title="Files" fmt=num0/>
  <Column id=declared_rows title="Rows declared" fmt=num0/>
  <Column id=loaded_rows title="Rows landed" fmt=num0/>
  <Column id=short_files title="Short files" fmt=num0/>
  <Column id=repeated_files title="Repeated files" fmt=num0/>
</DataTable>

```sql audit_flags
select batch_id, source_label, file, delivered_at, declared_rows, loaded_rows, status
from ridgeline.lead_cost_load_audit where status <> 'landed in full' order by batch_id
```

```sql audit
select batch_id, source_label, file, delivered_at, declared_rows, loaded_rows, checksum, status
from ridgeline.lead_cost_load_audit order by batch_id desc
```

Files the audit flags (<Value data={summary} column=short_files fmt=num0/> short, <Value data={summary} column=repeated_files fmt=num0/> repeated):

<DataTable data={audit_flags} rows=all>
  <Column id=batch_id title="Batch"/>
  <Column id=file title="File"/>
  <Column id=delivered_at title="Delivered"/>
  <Column id=declared_rows title="Declared" fmt=num0/>
  <Column id=loaded_rows title="Landed" fmt=num0/>
  <Column id=status title="Audit"/>
</DataTable>

Silver keeps one copy of the repeated file's rows and the last restated value of each day's search spend
(<Value data={summary} column=spend_rows_dropped fmt=num0/> spend rows dropped). Every file:

<DataTable data={audit} rows=10 search=true>
  <Column id=batch_id title="Batch"/>
  <Column id=source_label title="Export"/>
  <Column id=file title="File"/>
  <Column id=delivered_at title="Delivered"/>
  <Column id=declared_rows title="Declared" fmt=num0/>
  <Column id=loaded_rows title="Landed" fmt=num0/>
  <Column id=status title="Audit"/>
</DataTable>

## Silent failures, planted

Each of these still loads and builds without an error. Each was planted on its own into a copy of the exports, built
into its own warehouse, and tested; <Value data={summary} column=faults_caught fmt=num0/> of <Value data={summary} column=faults fmt=num0/>
were caught by the dbt test written for them. The last columns show what the headline would have said if nobody had
looked.

```sql faults
select * from ridgeline.lead_cost_faults order by fault_sort
```

<DataTable data={faults} rows=all>
  <Column id=what title="Fault"/>
  <Column id=written_to_catch_it title="Test written for it"/>
  <Column id=tests_failed title="Tests failed" fmt=num0/>
  <Column id=cost_per_issued_lead_without_tests title="Cost per issued lead" fmt=usd2/>
  <Column id=moves_by title="Moves by" fmt=usd2/>
</DataTable>

```sql small_faults
select count(*) as n from ridgeline.lead_cost_faults where abs(moves_by) < 2
```

<Value data={small_faults} column=n fmt=num0/> of the four move the headline by less than two dollars, which is why
they need a test: nobody would see them on a chart. Click ids stored in lower case are the expensive one: leads drop
out of their campaigns and become unattributed, and the cost per issued lead rises by about a quarter.
