---
title: ED wait times
---

Emergency-department throughput for ten **simulated** hospital sites, separate from the roofing-software company
on the rest of this site: <Value data={summary} column=visits fmt=num0/> visits from <Value data={summary} column=first_day/> to <Value data={summary} column=last_day/>, with each site's inpatient bed occupancy beside
them. Time in the ED runs from triage to leaving and is reported as the 90th percentile over a week's patients.
The target is <Value data={summary} column=target_hours/> hours for admitted patients and for high-urgency patients
sent home, and 4 hours for low-urgency patients sent home. A site with fewer than 20 patients in a week is not
reported for that week, rather than counted as passing.

The sites ED01 to ED10 are not real hospitals. The public part is Ontario's open daily ICU beds file, at the end
of this page. Code and tests: [ed_wait_times/](https://github.com/sky-five/ridgeline-analytics/tree/main/ed_wait_times).
These numbers come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.ed_summary
```

<BigValue data={summary} value=visits title="ED visits" fmt=num0/>
<BigValue data={summary} value=admitted title="Admitted" fmt=num0/>
<BigValue data={summary} value=p90_admitted_hours_all title="Admitted, 90th percentile hours (all weeks)" fmt=num2/>
<BigValue data={summary} value=breached_last_week title="Sites over 8 hours last week" fmt=num0/>
<BigValue data={summary} value=icu_odd_days title="Odd days in the public ICU file" fmt=num0/>

## Last week: which sites breached the 8-hour target

```sql last_week
select * from ridgeline.ed_last_week order by sort
```

For the week of <Value data={summary} column=week_start/> to <Value data={summary} column=week_end/>, admitted
patients at <Value data={summary} column=breached_sites/> were over <Value data={summary} column=target_hours/> hours
at the 90th percentile. <Value data={summary} column=not_reported_sites/> had too few admitted patients to report.

<BarChart data={last_week} x=site_id y=p90_reported_hours yFmt=num1 sort=false
  title="Admitted patients, 90th percentile hours in the ED, last week" colorPalette={['#111827']}>
  <ReferenceLine data={summary} y=target_hours label="8-hour target" color="#C2410C"/>
</BarChart>

<DataTable data={last_week} rows=all>
  <Column id=site_id title="Site"/>
  <Column id=site_type title="Type"/>
  <Column id=region title="Region"/>
  <Column id=patients title="Admitted" fmt=num0/>
  <Column id=p90_reported_hours title="90th percentile, hours" fmt=num2/>
  <Column id=share_within_target title="Within 8 hours" fmt=pct1/>
  <Column id=mean_bed_occupancy title="Bed occupancy" fmt=pct1/>
  <Column id=status title="Result"/>
</DataTable>

The same answer for any week and patient group comes from a read-only MCP tool,
`python -m ed_wait_times.server` ([how to connect it](https://github.com/sky-five/ridgeline-analytics/tree/main/ed_wait_times#ask-it-from-an-ai-assistant-mcp)).

## Throughput by site

```sql sites
select distinct site_id as value, site_id || ' (' || site_type || ', ' || region || ')' as label
from ridgeline.ed_throughput_weekly order by 1
```

<Dropdown data={sites} name=site value=value label=label title="Site" defaultValue="ED07"/>

```sql picked_weekly
select week_start, visits, admitted, share_admitted, admitted_p90_hours, mean_bed_occupancy, staffed_beds
from ridgeline.ed_throughput_weekly
where site_id = '${inputs.site.value}'
order by week_start
```

```sql picked_closure
select closure_from from ridgeline.ed_summary where closure_site = '${inputs.site.value}'
```

<BarChart data={picked_weekly} x=week_start y=visits yFmt=num0 title="ED visits per week (site picked above)"
  colorPalette={['#9CA3AF']}/>

<LineChart data={picked_weekly} x=week_start y=admitted_p90_hours yFmt=num1 yMin=0
  title="Admitted patients, weekly 90th percentile hours (gaps are weeks too small to report)"
  colorPalette={['#111827']}>
  <ReferenceLine data={summary} y=target_hours label="8-hour target" color="#C2410C" labelPosition=aboveStart/>
  <ReferenceLine data={picked_closure} x=closure_from label="24 beds close" color="#6B7280"/>
</LineChart>

<LineChart data={picked_weekly} x=week_start y=mean_bed_occupancy yFmt=pct0 yMin=0.7
  title="Inpatient bed occupancy at midnight, weekly mean of occupied over staffed beds" colorPalette={['#111827']}>
  <ReferenceLine data={picked_closure} x=closure_from label="24 beds close" color="#6B7280"/>
</LineChart>

```sql picked_weekly_latest
select * from ${picked_weekly} order by week_start desc
```

<DataTable data={picked_weekly_latest} rows=10>
  <Column id=week_start title="Week of"/>
  <Column id=visits title="Visits" fmt=num0/>
  <Column id=admitted title="Admitted" fmt=num0/>
  <Column id=share_admitted title="Share admitted" fmt=pct1/>
  <Column id=admitted_p90_hours title="Admitted p90, hours" fmt=num2/>
  <Column id=mean_bed_occupancy title="Bed occupancy" fmt=pct1/>
  <Column id=staffed_beds title="Staffed beds" fmt=num0/>
</DataTable>

Admitted patients wait in the ED for a ward bed, so their hours grow as the wards fill. From <Value data={summary} column=closure_from/>, <Value data={summary} column=closure_site/> closes <Value data={summary} column=closed_beds/> beds: its
weekly 90th percentile goes from a median <Value data={summary} column=closure_before_p90 fmt=num2/> hours
(<Value data={summary} column=closure_before_breached/> breach in <Value data={summary} column=closure_before_weeks/> weeks,
beds <Value data={summary} column=closure_before_occupancy fmt=pct1/> full) to <Value data={summary} column=closure_after_p90 fmt=num2/> hours
(both weeks after, beds <Value data={summary} column=closure_after_occupancy fmt=pct1/> full).
Pick ED03 for a site whose wards are always nearly full, and <Value data={summary} column=small_site/> for one too
small to report in <Value data={summary} column=small_site_unreported_weeks/> of <Value data={summary} column=weeks/> weeks.

## Every site, every week

```sql groups
select distinct patient_group as value, group_label as label from ridgeline.ed_site_week order by 1
```

<Dropdown data={groups} name=group value=value label=label title="Patient group" defaultValue="admitted"/>

```sql picked_group
select week_start, strftime(week_start, '%m-%d') as week, site_id, p90_reported_hours, target_hours
from ridgeline.ed_site_week
where patient_group = '${inputs.group.value}'
order by week_start, site_id
```

```sql picked_target
select distinct target_hours from ridgeline.ed_site_week where patient_group = '${inputs.group.value}'
```

<Heatmap data={picked_group} x=week y=site_id value=p90_reported_hours valueFmt=num1 xSort=week_start
  valueLabels=false nullsZero=false xLabelRotation=-90 xAxisPosition=bottom cellHeight=24
  colorPalette={['#F9FAFB', '#9CA3AF', '#C2410C']}
  title="Weekly 90th percentile hours in the ED, by site and week of 2026 (blank: too few to report)"/>

The target for this group is <Value data={picked_target} column=target_hours/> hours. ED03 is over it for admitted
patients almost every week; ED07 only in the last two.

```sql per_site
select * from ridgeline.ed_sites order by site_id
```

<DataTable data={per_site} rows=all>
  <Column id=site_id title="Site"/>
  <Column id=visits title="Visits" fmt=num0/>
  <Column id=admitted title="Admitted" fmt=num0/>
  <Column id=median_weekly_p90_hours title="Admitted, median weekly p90" fmt=num2/>
  <Column id=breached_weeks title="Weeks over 8 h" fmt=num0/>
  <Column id=unreported_weeks title="Not reported" fmt=num0/>
  <Column id=mean_bed_occupancy title="Bed occupancy" fmt=pct1/>
</DataTable>

## The public file: Ontario ICU beds by day

```sql icu_long
select census_date, 'Adult' as unit, adult_occupancy as occupancy from ridgeline.ed_icu_daily
union all
select census_date, 'Paediatric', ped_occupancy from ridgeline.ed_icu_daily
order by census_date, unit
```

```sql odd_days
select * from ridgeline.ed_icu_odd_days order by date
```

<LineChart data={icu_long} x=census_date y=occupancy series=unit yFmt=pct0 yMin=0
  title="ICU patients over ICU beds, Ontario, every day in the file (orange lines: the odd days)"
  seriesColors={{'Adult': '#111827', 'Paediatric': '#9CA3AF'}}>
  <ReferenceLine data={odd_days} x=date color="#C2410C" hideValue=true/>
</LineChart>

<Value data={summary} column=icu_days fmt=num0/> days from <Value data={summary} column=icu_first_day/> to <Value data={summary} column=icu_last_day/>, published on <a href="https://data.ontario.ca/dataset/availability-of-adult-icu-beds-and-occupancy-for-covid-related-critical-illness-crci">data.ontario.ca</a> under the
<Value data={summary} column=icu_licence/>; the file stopped updating on its last day. Adult ICU occupancy has a
median of <Value data={summary} column=icu_median_adult_occupancy fmt=pct1/>. The data tests keep the rows as
published and list <Value data={summary} column=icu_odd_days/> days that look wrong or unusual:

<DataTable data={odd_days} rows=all>
  <Column id=date title="Day"/>
  <Column id=adult_patients title="Adult patients" fmt=num0/>
  <Column id=adult_beds title="Adult beds" fmt=num0/>
  <Column id=ped_patients title="Paediatric patients" fmt=num0/>
  <Column id=ped_beds title="Paediatric beds" fmt=num0/>
  <Column id=why title="Why it is listed" wrap=true/>
</DataTable>

The two single days in 2023 look like reporting errors; the November 2022 days may be real.
