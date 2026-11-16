---
title: Provincial book health
---

**Simulated data**, separate from the roofing-software company on the rest of this site: a book of home and auto
insurance in <Value data={summary} column=provinces/> provinces, sold through brokers, directly and online,
from <Value data={summary} column=first_month/> to <Value data={summary} column=as_of/>
(<Value data={summary} column=policies fmt=num0/> policies, <Value data={summary} column=terms fmt=num0/> twelve-month
terms, <Value data={summary} column=claims fmt=num0/> claims). A hail storm in Alberta and two rate increases are
planted on purpose. The page shows growth, loss ratio and retention by province, what the storm and the increases
did, how well simple rules forecast retention, and the one-page brief.

Code, dbt models, tests and the [brief](https://github.com/sky-five/ridgeline-analytics/blob/main/book_health/results/brief.md):
[book_health/](https://github.com/sky-five/ridgeline-analytics/tree/main/book_health). The simulation is seeded, so
these numbers do not move with the nightly build.

```sql summary
select * from ridgeline.book_summary
```

## The book, last 12 months

<BigValue data={summary} value=in_force title="Policies in force" fmt=num0/>
<BigValue data={summary} value=written_premium_12m title="Written premium" fmt=usd1m/>
<BigValue data={summary} value=loss_ratio_12m title="Loss ratio" fmt=pct1/>
<BigValue data={summary} value=retention_12m title="Renewals kept" fmt=pct1/>

Loss ratio is incurred claims (by loss month) over earned premium (each term's premium spread over its days).
Retention is renewals kept over renewals due in the month.

## Growth by province

```sql provinces
select province_name, policies_in_force, in_force_growth_yoy, written_premium_growth_12m, written_premium_12m,
       loss_ratio_12m, retention_12m
from ridgeline.book_provinces order by written_premium_12m desc
```

<BarChart data={provinces} x=province_name y=in_force_growth_yoy yFmt=pct1 swapXY=true sort=false
  title="Policies in force, change on a year ago" colorPalette={['#111827']}/>

```sql in_force
select month_start, province_name, policies_in_force from ridgeline.book_province_month order by month_start
```

<LineChart data={in_force} x=month_start y=policies_in_force series=province_name yFmt=num0
  title="Policies in force at month end"/>

<Value data={summary} column=fastest_province/> grew fastest (<Value data={summary} column=fastest_growth fmt=pct1/>
more policies than a year ago); <Value data={summary} column=slowest_province/> is the only province with fewer
(<Value data={summary} column=slowest_growth fmt=pct1/>), after its auto rate increase. Written premium still grew
everywhere, because every renewal takes a rate change.

<DataTable data={provinces} rows=all>
  <Column id=province_name title="Province"/>
  <Column id=policies_in_force title="In force" fmt=num0/>
  <Column id=in_force_growth_yoy title="In force vs a year ago" fmt=pct1/>
  <Column id=written_premium_12m title="Written, 12 months" fmt=usd0/>
  <Column id=written_premium_growth_12m title="Written vs the 12 before" fmt=pct1/>
  <Column id=loss_ratio_12m title="Loss ratio" fmt=pct1/>
  <Column id=retention_12m title="Retention" fmt=pct1/>
</DataTable>

## Loss ratio by province

<BarChart data={provinces} x=province_name y=loss_ratio_12m yFmt=pct0 swapXY=true sort=false
  title="Loss ratio, last 12 months" colorPalette={['#C2410C']}/>

```sql provinces_by_year
select province_name, year(month_start)::varchar as year, sum(incurred) / sum(earned_premium) as loss_ratio
from ridgeline.book_province_month where year(month_start) <= 2025 group by all order by year, province_name
```

<BarChart data={provinces_by_year} x=province_name y=loss_ratio series=year type=grouped yFmt=pct0 sort=false
  title="Loss ratio by full calendar year"/>

The range runs from <Value data={summary} column=best_lr fmt=pct1/> (<Value data={summary} column=best_lr_province/>)
to <Value data={summary} column=worst_lr fmt=pct1/> (<Value data={summary} column=worst_lr_province/>). The small
provinces swing year to year on a few large claims; read them over two or three years, not one.

## The hail month

On <Value data={summary} column=hail_date/> hail hit <Value data={summary} column=hail_province/>: <Value data={summary} column=hail_claims/>
home claims, <Value data={summary} column=hail_incurred fmt=usd0/>.

<BigValue data={summary} value=hail_lr_month title="Alberta home loss ratio, July 2024" fmt=pct1/>
<BigValue data={summary} value=hail_lr_year title="Alberta home, 2024" fmt=pct1/>
<BigValue data={summary} value=hail_lr_year_before title="Alberta home, 2023" fmt=pct1/>

```sql alberta_home
select month_start, earned_premium, incurred from ridgeline.book_segments
where segment = 'Alberta home' order by month_start
```

<BarChart data={alberta_home} x=month_start y={['incurred', 'earned_premium']} type=grouped yFmt=usd0k
  title="Alberta home: incurred claims and earned premium by month" colorPalette={['#C2410C', '#9CA3AF']}>
  <ReferenceLine x='2024-07-01' label="Hail" color="#6B7280"/>
  <ReferenceLine x='2025-01-01' label="+10% from here" color="#6B7280"/>
</BarChart>

## The two rate increases

Every renewal takes a rate change; most land near 4%. Alberta home renewals took about 10% from <Value data={summary} column=ab_from/>,
after the hail, and Ontario auto about 14% from <Value data={summary} column=on_from/>. Customers who get more than the usual increase leave more.

```sql rate_actions
select segment, period, period_sort, renewals_due, mean_rate_change, retention
from ridgeline.book_rate_actions order by segment, period_sort
```

<DataTable data={rate_actions} rows=all>
  <Column id=segment title="Segment"/>
  <Column id=period title="Renewals"/>
  <Column id=renewals_due title="Due" fmt=num0/>
  <Column id=mean_rate_change title="Mean rate change" fmt=pct1/>
  <Column id=retention title="Kept" fmt=pct1/>
</DataTable>

```sql segments
select month_start, segment, retention, mean_rate_change from ridgeline.book_segments order by month_start
```

<LineChart data={segments} x=month_start y=mean_rate_change series=segment yFmt=pct0
  title="Mean rate change on renewals" colorPalette={['#C2410C', '#111827']}>
  <ReferenceLine x='2025-01-01' label="Alberta home" color="#6B7280"/>
  <ReferenceLine x='2025-04-01' label="Ontario auto" color="#6B7280"/>
</LineChart>

<LineChart data={segments} x=month_start y=retention series=segment yFmt=pct0 yMin=0.6
  title="Renewals kept" colorPalette={['#C2410C', '#111827']}>
  <ReferenceLine x='2025-01-01' color="#6B7280" hideValue=true/>
  <ReferenceLine x='2025-04-01' color="#6B7280" hideValue=true/>
</LineChart>

In Ontario auto retention fell from <Value data={summary} column=on_retention_before fmt=pct1/> to <Value data={summary} column=on_retention_after fmt=pct1/>
in the year after: about <Value data={summary} column=on_points_lost_per_point fmt=num1/> points of retention for each extra point of
increase.

## Retention by channel

```sql channels
select channel, renewals_due, retention_12m from ridgeline.book_channels order by retention_12m desc
```

<BarChart data={channels} x=channel y=retention_12m yFmt=pct1 sort=false yMin=0.6
  title="Renewals kept by channel, last 12 months" colorPalette={['#111827']}/>

## Forecasting retention

Three simple rules forecast each province's retention for the next 1 to 3 months from the months up to the forecast:
last month's retention, the 3-month average and the 12-month average (weighted by renewals due). Back-tested on every
month the book allows (<Value data={summary} column=forecasts_per_rule fmt=num0/> forecasts per rule across the
provinces), the <Value data={summary} column=rule/> misses by the least.

<BigValue data={summary} value=mae_trailing_12 title="12-month average, mean miss (points)" fmt=num2/>
<BigValue data={summary} value=mae_trailing_3 title="3-month average" fmt=num2/>
<BigValue data={summary} value=mae_last_month title="Last month" fmt=num2/>

```sql backtest_scores
select province_name, rule_label, horizon, forecasts, mae_points, bias_points
from ridgeline.book_backtest where horizon = 1
order by province_name = 'Whole book' desc, province_name, rule_label
```

<BarChart data={backtest_scores} x=province_name y=mae_points series=rule_label type=grouped yFmt=num1
  title="Mean miss one month ahead, by province (points)" sort=false/>

The four small provinces have under a hundred renewals due a month, so every rule misses them by more; the whole book is
forecast within about a point.

```sql province_choice
select distinct province_name from ridgeline.book_backtest_path order by province_name = 'Whole book' desc,
  province_name
```

<Dropdown data={province_choice} name=province value=province_name title="Province" defaultValue="Ontario"/>

```sql picked_path
select month_start, 'What happened' as line, actual as retention
from ridgeline.book_backtest_path
where province_name = '${inputs.province.value}' and rule = 'trailing_12'
union all
select month_start, rule_label, forecast
from ridgeline.book_backtest_path
where province_name = '${inputs.province.value}' and rule in ('trailing_12', 'trailing_3')
order by month_start
```

<LineChart data={picked_path} x=month_start y=retention series=line yFmt=pct0 yMin=0.6
  title="One month ahead: forecast against what happened" colorPalette={['#111827', '#C2410C', '#9CA3AF']}>
  <ReferenceLine x='2025-04-01' label="Ontario auto +14%" color="#6B7280"/>
</LineChart>

A 12-month average is a good forecast until prices move. In Ontario's first six months after the increase it was <Value data={summary} column=on_bias_trailing_12 fmt=num2/>
points too hopeful; the 3-month average caught up faster (<Value data={summary} column=on_bias_trailing_3 fmt=num2/>).

### The next three months

```sql forecast
select province_name, month, retention, renewals_due, expected_renewed
from ridgeline.book_forecast order by province_name, month
```

<BigValue data={summary} value=next_3_due title="Renewals due" fmt=num0/>
<BigValue data={summary} value=next_3_expected title="Expected to stay" fmt=num0/>
<BigValue data={summary} value=next_3_retention title="Expected retention" fmt=pct1/>

<DataTable data={forecast} rows=all>
  <Column id=province_name title="Province"/>
  <Column id=month title="Month"/>
  <Column id=retention title="Forecast retention" fmt=pct1/>
  <Column id=renewals_due title="Renewals due" fmt=num0/>
  <Column id=expected_renewed title="Expected to stay" fmt=num0/>
</DataTable>

## The latest months are not finished

```sql loss_by_month
select month_start, sum(incurred) / sum(earned_premium) as loss_ratio
from ridgeline.book_province_month group by 1 order by 1
```

<LineChart data={loss_by_month} x=month_start y=loss_ratio yFmt=pct0 title="Loss ratio by month, whole book (as reported)"
  colorPalette={['#111827']}>
  <ReferenceArea xMin='2026-04-01' xMax='2026-06-01' label="Late claims" color=warning/>
</LineChart>

<BigValue data={summary} value=lr_3m_reported title="Last 3 months, as reported" fmt=pct1/>
<BigValue data={summary} value=lr_3m_with_late title="With claims reported later" fmt=pct1/>
<BigValue data={summary} value=late_claims title="Claims not yet reported" fmt=num0/>

<Value data={summary} column=late_claims/> claims (<Value data={summary} column=late_incurred fmt=usd0/>) from the
last three months were not reported by <Value data={summary} column=as_of/>. The dbt models never see them; they are
kept apart only to show how far the reported number is low.

## The brief

```sql brief_numbers
select lead, body from ridgeline.book_brief where section = 'What the numbers say' order by item_sort
```

```sql brief_cautions
select lead, body from ridgeline.book_brief where section = 'Two cautions' order by item_sort
```

```sql brief_so_what
select lead, body from ridgeline.book_brief where section = 'So what' order by item_sort
```

**What the numbers say**

{#each brief_numbers as b}

- <b>{b.lead}</b> {b.body}

{/each}

**Two cautions**

{#each brief_cautions as b}

- <b>{b.lead}</b> {b.body}

{/each}

**So what**

{#each brief_so_what as b}

- {b.body}

{/each}
