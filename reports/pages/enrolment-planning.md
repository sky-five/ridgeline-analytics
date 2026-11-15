---
title: Enrolment planning
---

**Public data**, separate from the roofing-software company on the rest of this site: Statistics Canada's fall
enrolment counts for Canadian colleges and universities, and IRCC's monthly count of new study permits. The page
shows where international students are enrolled, how well three simple rules forecast next year's intake of new
permits, and a what-if that turns an intake figure into a fall enrolment figure.

Code, dbt models and tests: [enrolment_planning/](https://github.com/sky-five/ridgeline-analytics/tree/main/enrolment_planning).
Both sources are under the <Value data={summary} column=licence/> and pinned by SHA-256, so these numbers do not move
with the nightly build.

```sql summary
select * from ridgeline.enrol_summary
```

<BigValue data={summary} value=international title="International enrolments, fall 2024" fmt=num0/>
<BigValue data={summary} value=international_share title="Share of all enrolments" fmt=pct1/>
<BigValue data={summary} value=peak_international title="Peak (fall 2023)" fmt=num0/>
<BigValue data={summary} value=last_bridge_intake title="New permits, Oct 2023 to Sep 2024" fmt=num0/>
<BigValue data={summary} value=next_fall_intake title="New permits, Oct 2024 to Sep 2025" fmt=num0/>

Enrolments are program counts on one fall date, not students over a year. StatCan rounds each count at random to a
multiple of 3, so the leaves below add up to a few more or less than the published totals in the headline.
New permits are post-secondary study permits that took effect in the month (IRCC rounds to a multiple of 5).

## International share by region and program group

```sql groups
select distinct program_group, group_label,
       case program_group when 'ALL' then 0 when 'STEM' then 1 when 'BHASE' then 2 else 3 end as sort
from ridgeline.enrol_share order by sort
```

<Dropdown data={groups} name=group value=program_group label=group_label title="Program group" defaultValue="ALL"/>

```sql share_last_fall
select region_name, international, total, international_share
from ridgeline.enrol_share
where fall_year = (select max(fall_year) from ridgeline.enrol_share)
  and program_group = '${inputs.group.value}' and region_code <> 'CA'
order by international desc
```

<BarChart data={share_last_fall} x=region_name y=international_share swapXY=true sort=false yFmt=pct0
  title="International share of enrolments, fall 2024" colorPalette={['#111827']}/>

```sql share_trend
select fall, region_name, international_share
from ridgeline.enrol_share
where program_group = '${inputs.group.value}' and region_code in ('CA', 'ON', 'BC', 'QC', 'AB')
order by fall_year
```

<LineChart data={share_trend} x=fall y=international_share series=region_name yFmt=pct0 sort=false
  title="International share by fall, Canada and the four largest provinces"/>

<DataTable data={share_last_fall} rows=all>
  <Column id=region_name title="Region"/>
  <Column id=international title="International" fmt=num0/>
  <Column id=total title="All enrolments" fmt=num0/>
  <Column id=international_share title="International share" fmt=pct1/>
</DataTable>

```sql by_group
select region_name, group_label, international
from ridgeline.enrol_share
where fall_year = (select max(fall_year) from ridgeline.enrol_share)
  and program_group <> 'ALL' and region_code <> 'CA'
order by international desc
```

<BarChart data={by_group} x=region_name y=international series=group_label swapXY=true yFmt=num0
  title="International enrolments by program group, fall 2024"/>

STEM is science, engineering, mathematics and computing; BHASE is business, humanities, health, arts, social
science and education (StatCan's grouping of CIP Canada 2021). StatCan leaves some cells unpublished; they count as
nothing on both sides of the share.

## Three intake rules, back-tested

From every month-end from <Value data={summary} column=backtest_first_origin/> to <Value data={summary} column=backtest_last_origin/>,
each rule forecasts the next 12 months of new post-secondary permits using only months up to that point (<Value data={summary} column=monthly_forecasts fmt=num0/>
monthly forecasts in all). Each origin's 12-month total
is scored against what IRCC later published. WAPE is the absolute error over the actual; bias above zero means the
rule forecast too many.

```sql series
select distinct series, series_name, case series when 'CA' then 0 else 1 end as sort
from ridgeline.enrol_backtest order by sort, series_name
```

<Dropdown data={series} name=series value=series label=series_name title="Series" defaultValue="CA"/>

```sql backtest
select period, rule_label, forecasts, wape, bias, case when is_best then 'best' else '' end as best
from ridgeline.enrol_backtest
where series = '${inputs.series.value}'
order by period, rule
```

<BarChart data={backtest} x=period y=wape series=rule_label type=grouped sort=false yFmt=pct0
  title="WAPE of the 12-month total, by period" colorPalette={['#111827', '#C2410C', '#9CA3AF']}/>

<BarChart data={backtest} x=period y=bias series=rule_label type=grouped sort=false yFmt=pct0
  title="Bias of the 12-month total (above zero: too many)" colorPalette={['#111827', '#C2410C', '#9CA3AF']}/>

<DataTable data={backtest} rows=all>
  <Column id=period title="12 months ending in"/>
  <Column id=rule_label title="Rule"/>
  <Column id=forecasts title="Origins" fmt=num0/>
  <Column id=wape title="WAPE" fmt=pct1/>
  <Column id=bias title="Bias" fmt=pct1/>
  <Column id=best title="Best"/>
</DataTable>

No rule wins every period. After the federal cap on study permit applications (announced 2024-01-22) every rule
forecast too many for Canada: rules built on past months cannot see a policy change, so a plan has to put it in as
an input. That is what the what-if below is for.

```sql horizon
select horizon, rule_label, wape
from ridgeline.enrol_backtest_horizon
where series = '${inputs.series.value}' and period = '2024-2026 after the cap'
order by horizon, rule_label
```

<LineChart data={horizon} x=horizon y=wape series=rule_label yFmt=pct0 xAxisTitle="Months ahead"
  title="Single-month WAPE by months ahead, after the cap" colorPalette={['#111827', '#C2410C', '#9CA3AF']}/>

Single months are harder than the total: the August peak moves between July, August and September.

```sql permits
select month, permits from ridgeline.enrol_permits_monthly
where series = '${inputs.series.value}' order by month
```

<LineChart data={permits} x=month y=permits yFmt=num0 title="New post-secondary study permits per month"
  colorPalette={['#111827']}/>

## What-if: intake to fall enrolment

Fall international enrolment is roughly a year's new permits (October to September) times enrolments per new
permit. That ratio is a stock over a flow: the fall count holds students in every year of their program, the
permits only the new arrivals. So it **rises when intake falls**: 1.31 in fall 2019, 1.68 in fall 2020 when
intake dropped, 1.09 at the peak of fall 2023.

```sql bridge
select fall, international_enrolments, new_permits_oct_to_sep, enrolments_per_new_permit
from ridgeline.enrol_bridge order by fall_year
```

<DataTable data={bridge} rows=all>
  <Column id=fall title="Fall"/>
  <Column id=new_permits_oct_to_sep title="New permits (Oct-Sep)" fmt=num0/>
  <Column id=international_enrolments title="International" fmt=num0/>
  <Column id=enrolments_per_new_permit title="Per permit" fmt=num2/>
</DataTable>

The last complete window, October 2024 to September 2025, had <Value data={summary} column=next_fall_intake fmt=num0/>
new permits, down from <Value data={summary} column=last_bridge_intake fmt=num0/> a year earlier. StatCan has not published fall 2025
yet. Move the slider to try another intake, and pick a ratio.

<Slider name=intake title="New permits (Oct-Sep)" min=100000 max=600000 step=5000
  defaultValue=265000 fmt=num0 showInput=true size=large/>

```sql ratios
select ratio_key, choice, sort from ridgeline.enrol_ratios order by sort
```

<Dropdown data={ratios} name=ratio value=ratio_key label=choice title="Enrolments per new permit" defaultValue="last"/>

```sql estimate
select r.choice, round(${inputs.intake} * r.ratio) as fall_international,
       round(${inputs.intake} * r.ratio) / s.international - 1 as change_vs_last_fall
from ridgeline.enrol_ratios as r cross join ridgeline.enrol_summary as s
where r.ratio_key = '${inputs.ratio.value}'
```

<BigValue data={estimate} value=fall_international title="Fall international enrolments" fmt=num0/>
<BigValue data={estimate} value=change_vs_last_fall title="Change vs fall 2024" fmt=pct1/>

```sql whatif_range
select r.choice, round(${inputs.intake} * r.ratio) as fall_international,
       round(${inputs.intake} * r.ratio) / s.international - 1 as change_vs_last_fall
from ridgeline.enrol_ratios as r cross join ridgeline.enrol_summary as s
order by r.sort
```

<DataTable data={whatif_range} rows=all>
  <Column id=choice title="Ratio"/>
  <Column id=fall_international title="Fall international enrolments" fmt=num0/>
  <Column id=change_vs_last_fall title="Change vs fall 2024" fmt=pct1/>
</DataTable>

With a sharp drop in intake, as after the cap, the 2020 pattern points to the upper end of the range: students who
arrived in earlier years are still enrolled. The what-if is arithmetic on the published ratios, not a forecast.
