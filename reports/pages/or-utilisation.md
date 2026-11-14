---
title: Operating-room ROI
---

A return-on-investment check on **simulated** data, separate from the roofing-software company on the rest of this
site. A surgical suite gives each surgical service fixed blocks of operating-room time. From the week of <Value data={summary} column=policy_start/>
it runs an auto-release rule: a block with nothing booked 72 hours ahead is released so another service can use it.
The page asks what that rule really returned, and shows how the usual utilisation numbers make it look about five
times bigger.

Code and tests: [or_utilisation/](https://github.com/sky-five/ridgeline-analytics/tree/main/or_utilisation). These
numbers come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.or_roi_summary
```

<BigValue data={summary} value=rooms title="Rooms" fmt=num0/>
<BigValue data={summary} value=blocks title="Blocks (26 weeks)" fmt=num0/>
<BigValue data={summary} value=cases_completed title="Completed cases" fmt=num0/>
<BigValue data={summary} value=releases title="Releases" fmt=num0/>
<BigValue data={summary} value=auto_releases title="By the rule" fmt=num0/>

## Four answers to one question

How many patient minutes did the rule add in its first 13 weeks?

```sql framings
select * from ridgeline.or_roi_framings order by sort
```

<BigValue data={summary} value=claimed_minutes title="Claimed (minutes)" fmt=num0/>
<BigValue data={summary} value=before_after_minutes title="Before/after (minutes)" fmt=num0/>
<BigValue data={summary} value=defended_minutes title="Defended (minutes)" fmt=num0/>
<BigValue data={summary} value=true_minutes title="Replayed truth (minutes)" fmt=num0/>

<BarChart data={framings} x=framing y=added_minutes sort=false yFmt=num0 title="Added patient minutes, 13 weeks"
  colorPalette={['#111827']}/>

<DataTable data={framings}>
  <Column id=framing title="Framing"/>
  <Column id=method title="How it is computed" wrap=true/>
  <Column id=added_minutes title="Added minutes" fmt=num0/>
  <Column id=ci_low title="95% CI low" fmt=num0/>
  <Column id=ci_high title="95% CI high" fmt=num0/>
  <Column id=over_truth title="x truth" fmt=num1/>
  <Column id=net_usd title="Net return" fmt=usd0/>
</DataTable>

**The truth is known.** Every random draw belongs to one block, so the simulator can replay the same half-year with
the rule switched off. The rule added <Value data={summary} column=true_minutes fmt=num0/> patient minutes
(<Value data={summary} column=true_cases fmt=num0/> cases). The analysis never reads that replay; a test checks that
the defended interval (<Value data={summary} column=defended_ci_low fmt=num0/> to <Value data={summary} column=defended_ci_high fmt=num0/>,
from resampling days) covers it. The claim is <Value data={summary} column=claimed_over_truth fmt=num1/> times the truth.

Money uses two placeholders a finance team would replace: <Value data={summary} column=margin_per_patient_hour_usd fmt=usd0/>
contribution margin per patient hour and <Value data={summary} column=rule_cost_usd fmt=usd0/> to run the rule. The
minutes are what the analysis stands behind.

## The claims, reviewed

Each claim is "metric M went from X in weeks 1-13 to Y in weeks 14-26". The validation suite runs five checks on it.

```sql claims
select * from ridgeline.or_roi_claims order by sort
```

<DataTable data={claims}>
  <Column id=metric_label title="Claim"/>
  <Column id=before title="Weeks 1-13" fmt=pct1/>
  <Column id=after title="Weeks 14-26" fmt=pct1/>
  <Column id=change_pp title="Change (points)" fmt=num1/>
  <Column id=n_flags title="Flags" fmt=num0/>
  <Column id=flags title="What the checks found" wrap=true/>
</DataTable>

The checks that fired, with what each one measured (all 20 check results are in `reporting.or_roi_checks`):

```sql checks
select * from ridgeline.or_roi_checks where flagged order by claim_sort, check_sort
```

<DataTable data={checks} rows=all>
  <Column id=metric_label title="Claim"/>
  <Column id=check_label title="Check" wrap=true/>
  <Column id=size_pp title="Points" fmt=num1/>
  <Column id=detail title="What it found" wrap=true/>
</DataTable>

Room utilisation is the honest metric, but a plain before/after still credits the rule with fewer winter
cancellations: it also rose on blocks the owning service booked, where the rule cannot act.

## Week by week

```sql weekly_rates
select block_week,
       room_utilisation as "Room utilisation",
       adjusted_block_utilisation as "Adjusted block utilisation",
       block_utilisation as "Block utilisation"
from ridgeline.or_roi_weekly
order by block_week
```

<LineChart data={weekly_rates} x=block_week y={['Room utilisation', 'Adjusted block utilisation', 'Block utilisation']}
  yFmt=pct0 title="Weekly utilisation, three definitions" colorPalette={['#111827', '#C2410C', '#9CA3AF']}>
  <ReferenceLine data={summary} x=policy_start label="Auto-release rule starts" color="#6B7280"/>
</LineChart>

```sql weekly_drivers
select block_week,
       released_time_rate as "Released 72 h+ ahead",
       same_day_cancellation_rate as "Same-day cancellations"
from ridgeline.or_roi_weekly
order by block_week
```

<LineChart data={weekly_drivers} x=block_week y={['Released 72 h+ ahead', 'Same-day cancellations']} yFmt=pct0 yMin=0
  title="More time released, fewer cancellations" colorPalette={['#C2410C', '#111827']}>
  <ReferenceLine data={summary} x=policy_start color="#6B7280"/>
</LineChart>

Released time rises when the rule starts. Same-day cancellations fall in the spring on their own, which lifts every
utilisation line whether or not the rule did anything.

## How each number is computed

```sql metric_spec
select * from ridgeline.or_roi_metric_spec order by sort
```

Each metric comes from [metric_spec.yml](https://github.com/sky-five/ridgeline-analytics/blob/main/or_utilisation/metric_spec.yml):
the dbt macro computes it from these minute sums for any grouping, and a test recomputes every week from the spec.
Minutes count only inside the 07:30-15:30 block window.

{#each metric_spec as m}

<Details title="{m.label}: {m.before_text} in weeks 1-13, {m.after_text} in weeks 14-26">

<p class="meta">
<b>Numerator:</b> <code>{m.numerator}</code><br/>
<b>Denominator:</b> <code>{m.denominator}</code><br/>
<b>Definition:</b> {m.definition}<br/>
<b>Fit for:</b> {m.fit_for}
</p>

</Details>

{/each}
