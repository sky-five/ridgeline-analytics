---
title: Claims self-service
---

A self-service claims dashboard on **simulated** data, separate from the roofing-software company on the rest of
this site: a book of <Value data={summary} column=policies fmt=num0/> one-year insurance policies and the
<Value data={summary} column=claims fmt=num0/> claims reported against them up to <Value data={summary} column=as_of/>.
Loss ratio, claim cycle time and approval rate are defined once in a MetricFlow semantic layer; every number here is
summed from that layer's additive metrics and divided the same way, so a drill-down cannot drift from the definition.

Code, tests and the [handover doc](https://github.com/sky-five/ridgeline-analytics/blob/main/claims_self_service/HANDOVER.md)
(how to query a metric, how to add one, what each one is not fit for):
[claims_self_service/](https://github.com/sky-five/ridgeline-analytics/tree/main/claims_self_service). These numbers
come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.claims_ss_summary
```

<BigValue data={summary} value=loss_ratio title="Loss ratio" fmt=pct1/>
<BigValue data={summary} value=claim_cycle_time_days title="Cycle time (days)" fmt=num1/>
<BigValue data={summary} value=approval_rate title="Approval rate" fmt=pct1/>
<BigValue data={summary} value=earned_premium title="Earned premium" fmt=usd0/>
<BigValue data={summary} value=claims_open title="Claims still open" fmt=num0/>

## Drill down

Pick a line of business, region and channel. The three metrics and the monthly chart follow the selection.

```sql lines
select distinct line_of_business as value, line_of_business_label as label from ridgeline.claims_ss_cube order by 1
```

```sql regions
select distinct region as value, region_label as label from ridgeline.claims_ss_cube order by 1
```

```sql channels
select distinct channel as value, channel_label as label from ridgeline.claims_ss_cube order by 1
```

<Dropdown data={lines} name=line value=value label=label title="Line of business" defaultValue="all">
  <DropdownOption value="all" valueLabel="All lines"/>
</Dropdown>
<Dropdown data={regions} name=region value=value label=label title="Region" defaultValue="all">
  <DropdownOption value="all" valueLabel="All regions"/>
</Dropdown>
<Dropdown data={channels} name=channel value=value label=label title="Channel" defaultValue="all">
  <DropdownOption value="all" valueLabel="All channels"/>
</Dropdown>

```sql picked
select *
from ridgeline.claims_ss_cube
where ('${inputs.line.value}' = 'all' or line_of_business = '${inputs.line.value}')
  and ('${inputs.region.value}' = 'all' or region = '${inputs.region.value}')
  and ('${inputs.channel.value}' = 'all' or channel = '${inputs.channel.value}')
```

```sql picked_total
select sum(incurred_losses) / sum(earned_premium) as loss_ratio,
       sum(cycle_days) / nullif(sum(closed_claims), 0) as claim_cycle_time_days,
       sum(approved_claims) / nullif(sum(decided_claims), 0) as approval_rate,
       sum(claims_reported) as claims_reported,
       sum(decided_claims) - sum(approved_claims) as denied_claims
from ${picked}
```

<BigValue data={picked_total} value=loss_ratio title="Loss ratio" fmt=pct1/>
<BigValue data={picked_total} value=claim_cycle_time_days title="Cycle time (days)" fmt=num1/>
<BigValue data={picked_total} value=approval_rate title="Approval rate" fmt=pct1/>
<BigValue data={picked_total} value=claims_reported title="Claims reported" fmt=num0/>
<BigValue data={picked_total} value=denied_claims title="Denied" fmt=num0/>

```sql picked_monthly
select month,
       sum(incurred_losses) / sum(earned_premium) as loss_ratio,
       sum(claims_reported) as claims_reported,
       sum(approved_claims) / nullif(sum(decided_claims), 0) as approval_rate
from ${picked}
group by month
order by month
```

<LineChart data={picked_monthly} x=month y=loss_ratio yFmt=pct0 title="Loss ratio by month of loss"
  colorPalette={['#111827']}/>

<BarChart data={picked_monthly} x=month y=claims_reported yFmt=num0 title="Claims reported by month of loss"
  colorPalette={['#9CA3AF']}/>

Loss ratio counts a loss in the month it happened and premium in the month it was earned. Claims not yet reported
are not in it, so the last few months read low.

## Every slice, from the semantic layer

```sql slices
select * from ridgeline.claims_ss_slices order by slice_sort, value
```

<DataTable data={slices} rows=all groupBy=slice>
  <Column id=value_label title="Slice"/>
  <Column id=loss_ratio title="Loss ratio" fmt=pct1/>
  <Column id=claim_cycle_time_days title="Cycle time (days)" fmt=num1/>
  <Column id=approval_rate title="Approval rate" fmt=pct1/>
</DataTable>

These rows are MetricFlow's own answers for each slice; a test checks that summing the drill-down table gives the
same numbers.

## The hail month

```sql hail
select month, loss_ratio, claims_reported, is_hail_month from ridgeline.claims_ss_hail order by month
```

<BarChart data={hail} x=month y=claims_reported yFmt=num0 title="South region homeowners claims by month of loss"
  colorPalette={['#C2410C']}/>

In <Value data={summary} column=hail_month_label/>, homeowners losses in the <Value data={summary} column=hail_region/>
region came to <Value data={summary} column=hail_loss_ratio fmt=num1/> times that month's earned premium, from
<Value data={summary} column=hail_claims fmt=num0/> claims, against <Value data={summary} column=other_months_min_claims fmt=num0/>
to <Value data={summary} column=other_months_max_claims fmt=num0/> in every other month. That one storm is why the
<Value data={summary} column=hail_region/> region has the highest loss ratio over the whole period
(<Value data={summary} column=south_loss_ratio fmt=pct1/>). Pick Homeowners and South above to see it in the monthly chart.

## Direct-channel denials

```sql channel_quarterly
select quarter, channel_label, denial_rate, denied_claims, decided_claims
from ridgeline.claims_ss_channel_quarterly
order by quarter, channel_label
```

<LineChart data={channel_quarterly} x=quarter y=denial_rate series=channel_label yFmt=pct0 yMin=0
  title="Denial rate by channel, by quarter closed" colorPalette={['#9CA3AF', '#6B7280', '#C2410C']}/>

Direct-channel claims are approved <Value data={summary} column=direct_approval_rate fmt=pct1/> of the time, against
<Value data={summary} column=agent_approval_rate fmt=pct1/> for agent and <Value data={summary} column=broker_approval_rate fmt=pct1/>
for broker, and the gap holds in every quarter rather than coming from one bad month. The metric says where to look;
it does not say why (the simulator plants the gap, a real team would read the denial reasons next).

<DataTable data={channel_quarterly} rows=all>
  <Column id=quarter title="Quarter closed"/>
  <Column id=channel_label title="Channel"/>
  <Column id=decided_claims title="Decided" fmt=num0/>
  <Column id=denied_claims title="Denied" fmt=num0/>
  <Column id=denial_rate title="Denial rate" fmt=pct1/>
</DataTable>

## The metrics

```sql metric_list
select * from ridgeline.claims_ss_metrics order by sort
```

All <Value data={summary} column=n_metrics fmt=num0/> metrics in
[_metrics.yml](https://github.com/sky-five/ridgeline-analytics/blob/main/claims_self_service/dbt/models/semantic/_metrics.yml).
The three ratios are built from the simple metrics below them.

<DataTable data={metric_list} rows=all>
  <Column id=label title="Metric"/>
  <Column id=computed_as title="Computed as"/>
  <Column id=description title="Definition" wrap=true/>
  <Column id=not_fit_for title="Not fit for" wrap=true/>
</DataTable>
