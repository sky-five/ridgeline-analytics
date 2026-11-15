---
title: Onboarding funnel
---

An account-onboarding funnel monitor on **simulated** data, separate from the roofing-software company on the rest
of this site: <Value data={summary} column=people fmt=num0/> people starting an application in one of four account
programs between <Value data={summary} column=first_week/> and <Value data={summary} column=as_of/>, from
<Value data={summary} column=delivered_events fmt=num0/> delivered events. An application is a person in a program
(keyed on the trimmed, lower-case email and date of birth), not an application id, and a check watches for the
day those two stop agreeing.

Code, tests and the [findings note](https://github.com/sky-five/ridgeline-analytics/blob/main/onboarding_funnel/results/findings.md):
[onboarding_funnel/](https://github.com/sky-five/ridgeline-analytics/tree/main/onboarding_funnel). These numbers
come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.onb_summary
```

<BigValue data={summary} value=mature_started title="People in mature cohorts" fmt=num0/>
<BigValue data={summary} value=mature_activation_rate title="Activated within 30 days" fmt=pct1/>
<BigValue data={summary} value=application_ids title="Application ids" fmt=num0/>
<BigValue data={summary} value=redelivered title="Redelivered events (counted once)" fmt=num0/>
<BigValue data={summary} value=break_max_ids_per_person title="Worst ids per person" fmt=num3/>

Activated means a first transaction within 30 days of the first start. The funnel, drop-off and time tables use
mature cohorts only: people who started from <Value data={summary} column=first_week/> to the week of
<Value data={summary} column=last_mature_week/>, who all had the full 30 days by the cut-off.

## Funnel by program

```sql programs
select distinct program as value, program_label as label from ridgeline.onb_funnel order by 2
```

<Dropdown data={programs} name=program value=value label=label title="Program" defaultValue="cross_border"/>

```sql picked_funnel
select step_sort, step, people, share_of_started, share_of_previous_step
from ridgeline.onb_funnel
where program = '${inputs.program.value}'
order by step_sort
```

<BarChart data={picked_funnel} x=step y=people yFmt=num0 swapXY=true sort=false
  title="People reaching each step" colorPalette={['#111827']}/>

<DataTable data={picked_funnel} rows=all>
  <Column id=step title="Step"/>
  <Column id=people title="People" fmt=num0/>
  <Column id=share_of_previous_step title="Of the step before" fmt=pct1/>
  <Column id=share_of_started title="Of everyone who started" fmt=pct1/>
</DataTable>

```sql all_programs
select program_label, step_sort, step, share_of_started
from ridgeline.onb_funnel
order by program_label, step_sort
```

<LineChart data={all_programs} x=step y=share_of_started series=program_label yFmt=pct0 yMin=0 sort=false
  title="Share of starters still in, by step"/>

Gig payouts keep the most people at every step. The business program loses the most at KYC; consumer card and
cross-border lose the most after it, to people who pass and never fund the account.

## Why people drop off

```sql picked_drops
select step_label, reason_label, applicants, share_of_drop_offs
from ridgeline.onb_drop_offs
where program = '${inputs.program.value}'
order by applicants desc
```

<BarChart data={picked_drops} x=reason_label y=applicants series=step_label yFmt=num0 swapXY=true
  title="People who did not activate, by the step and reason they stopped (program picked above)"/>

<DataTable data={picked_drops} rows=all>
  <Column id=step_label title="Step"/>
  <Column id=reason_label title="Reason"/>
  <Column id=applicants title="People" fmt=num0/>
  <Column id=share_of_drop_offs title="Of drop-offs" fmt=pct1/>
</DataTable>

## Time to first transaction

```sql ttft
select * from ridgeline.onb_time_to_first_txn order by median_days
```

<BarChart data={ttft} x=program_label y=median_days yFmt=num1 title="Median days from first start to first transaction"
  colorPalette={['#9CA3AF']}/>

<DataTable data={ttft} rows=all>
  <Column id=program_label title="Program"/>
  <Column id=activated title="Activated" fmt=num0/>
  <Column id=median_days title="Median days" fmt=num1/>
  <Column id=p90_days title="90th percentile days" fmt=num1/>
  <Column id=share_within_1_day title="Within 1 day" fmt=pct0/>
  <Column id=share_within_7_days title="Within 7 days" fmt=pct0/>
</DataTable>

## Counted per application id or per person

```sql break_weekly
select cohort_week, counted, activation
from ridgeline.onb_activation_weekly
where program = 'cross_border'
order by cohort_week, counted
```

<LineChart data={break_weekly} x=cohort_week y=activation series=counted yFmt=pct0 yMin=0
  title="Cross-border weekly activation, mature cohort weeks"
  seriesColors={{'Per application id': '#C2410C', 'Per person': '#111827'}}>
  <ReferenceLine data={summary} x=break_week label="Second ids start" color="#6B7280"/>
</LineChart>

From the week of <Value data={summary} column=break_week/>, a resume or retry in the
<Value data={summary} column=break_program_label/> app opens a new application id. A dashboard counting ids sees
activation fall from <Value data={summary} column=per_id_before fmt=pct1/> to
<Value data={summary} column=per_id_after fmt=pct1/> (<Value data={summary} column=per_id_change_pp fmt=num1/>
points, 95% CI <Value data={summary} column=per_id_ci_low fmt=num1/> to <Value data={summary} column=per_id_ci_high fmt=num1/>).
Counted per person it goes from <Value data={summary} column=per_person_before fmt=pct1/> to
<Value data={summary} column=per_person_after fmt=pct1/> (<Value data={summary} column=per_person_change_pp fmt=num1/>
points, 95% CI <Value data={summary} column=per_person_ci_low fmt=num1/> to +<Value data={summary} column=per_person_ci_high fmt=num1/>):
about <Value data={summary} column=share_from_counting fmt=pct0/> of the drop is people counted twice.

```sql ids_weekly
select cohort_week, program_label, application_ids_per_applicant
from ridgeline.onb_weekly
order by cohort_week, program_label
```

<LineChart data={ids_weekly} x=cohort_week y=application_ids_per_applicant series=program_label yFmt=num2
  title="Application ids per person, every cohort week">
  <ReferenceLine data={summary} y=ids_limit label="Check limit" color="#6B7280"/>
</LineChart>

The other three programs stay at exactly 1.000. <Value data={summary} column=break_program_label/> goes over
<Value data={summary} column=ids_limit fmt=num2/> in the break week and stays over for all
<Value data={summary} column=break_weeks_over fmt=num0/> weeks after, up to
<Value data={summary} column=break_max_ids_per_person fmt=num3/>.

## A real drop: consumer-card KYC

```sql kyc_weekly
select cohort_week, kyc_pass_rate
from ridgeline.onb_weekly
where program = 'consumer_card'
order by cohort_week
```

<LineChart data={kyc_weekly} x=cohort_week y=kyc_pass_rate yFmt=pct0 title="Consumer card KYC pass rate, every cohort week"
  colorPalette={['#111827']}>
  <ReferenceLine data={summary} x=real_week label="Pass rate steps down" color="#6B7280"/>
</LineChart>

The <Value data={summary} column=real_program_label/> KYC pass rate drops from
<Value data={summary} column=real_before fmt=pct1/> to <Value data={summary} column=real_after fmt=pct1/> from the
week of <Value data={summary} column=real_week/> (t = <Value data={summary} column=real_t fmt=num1/>) while ids per
person stay at 1.000, so it is read as real. <Value data={summary} column=real_reason/> is the fail reason that grew,
from <Value data={summary} column=real_reason_before fmt=pct1/> to <Value data={summary} column=real_reason_after fmt=pct1/>
of people who submitted.

## The accuracy checks

```sql checks
select * from ridgeline.onb_checks order by sort
```

<DataTable data={checks} rows=all>
  <Column id=check title="Check"/>
  <Column id=passed title="Passed"/>
  <Column id=result title="Result" wrap=true/>
</DataTable>

The third check failing is the point: it is the alarm that fired on the cross-border counting break.

```sql steps
select program_label, rate_label, week, before, after, t, reading
from ridgeline.onb_steps
order by abs(t) desc
```

The step detector looks for the week each weekly rate moved most and calls it a shift at |t| >= 3. It is not told
the planted dates. Its margin is thin: the largest step on a series with nothing planted is
t = <Value data={summary} column=noise_t fmt=num1/> (<Value data={summary} column=noise_label/>), so the ids-per-person
check, not the step detector, is the alarm for double counting.

<DataTable data={steps} rows=all>
  <Column id=program_label title="Program"/>
  <Column id=rate_label title="Rate"/>
  <Column id=week title="Largest step at"/>
  <Column id=before title="Before" fmt=pct1/>
  <Column id=after title="After" fmt=pct1/>
  <Column id=t title="t" fmt=num1/>
  <Column id=reading title="Reading"/>
</DataTable>
