---
title: "ARR: from CRM to billing"
---

A learning project on **simulated** data. Sales counts ARR from closed-won deals in the CRM; finance counts it from
what billing started. This page walks from one to the other, month by month, to the cent. Billing's contract side is
the source of truth. Each CRM deal is matched to the billing change it should have started, and every gap gets a
named step. The models and their tests are in
[arr_source_of_truth/](https://github.com/sky-five/ridgeline-analytics/tree/main/arr_source_of_truth); this page is
rebuilt with them every night.

```sql meta
select * from ridgeline.arr_meta
```

<BigValue data={meta} value=closing_arr title="Closing ARR (billing)" fmt=usd0k/>
<BigValue data={meta} value=paying_customers title="Paying customers" fmt=num0/>
<BigValue data={meta} value=won_deals title="Closed-won deals" fmt=num0/>
<BigValue data={meta} value=deals_flagged title="Deals that need a look" fmt=num0/>

Data as of <Value data={meta} column=as_of/>; the last closed month is <Value data={meta} column=last_month fmt="mmmm yyyy"/>.
Since December 2024 the CRM booked <Value data={meta} column=crm_booked_total fmt=usd0/> of ARR from new subscriptions
and upgrades; billing started <Value data={meta} column=billing_sales_led_total fmt=usd0/>.

## The walk for one month

```sql months
select strftime(month, '%Y-%m') as month_label, month from ridgeline.arr_walk_monthly order by month desc
```

<Dropdown data={months} name=month value=month_label title="Month"/>

```sql walk
select step, usd, kind
from ridgeline.arr_walk_steps
where strftime(month, '%Y-%m') = '${inputs.month.value}'
order by step_order
```

<DataTable data={walk} rows=all>
  <Column id=step title="Step"/>
  <Column id=usd title="ARR (USD)" fmt=usd0/>
</DataTable>

Read it top to bottom. **Duplicates**, **won, not billed** and **awaiting billing** take out deals that did not (or
not yet) start anything in billing. **Amount fixes** replace the booked ARR with what billing started.
**Timing** moves a deal to the month billing started it. **Missing deals** add billing changes no one logged in the
CRM. That lands on billing's ARR from new subscriptions and upgrades. Seat changes and churn never go through the
CRM; adding them gives the net change in the bridge below.

## Every month

```sql walk_monthly
select month, crm_booked, duplicates + won_not_billed + awaiting_billing as not_billed,
       amount_fixes, timing, missing_deals, billing_sales_led, seat_changes, cancellations, net_change
from ridgeline.arr_walk_monthly
order by month desc
```

<DataTable data={walk_monthly} rows=12>
  <Column id=month fmt="mmm yyyy"/>
  <Column id=crm_booked title="CRM booked" fmt=usd0/>
  <Column id=not_billed title="Not billed" fmt=usd0/>
  <Column id=amount_fixes title="Amount fixes" fmt=usd0/>
  <Column id=timing title="Timing" fmt=usd0/>
  <Column id=missing_deals title="Missing deals" fmt=usd0/>
  <Column id=billing_sales_led title="Billing new + upgrades" fmt=usd0/>
  <Column id=seat_changes title="Seats" fmt=usd0/>
  <Column id=cancellations title="Churn" fmt=usd0/>
  <Column id=net_change title="Net change" fmt=usd0/>
</DataTable>

```sql booked_vs_billed
select month, crm_booked as "CRM booked", billing_sales_led as "Billing new + upgrades"
from ridgeline.arr_walk_monthly
order by month
```

<LineChart data={booked_vs_billed} x=month y={['CRM booked', 'Billing new + upgrades']} yFmt=usd0k title="CRM booked vs billing new + upgrades" colorPalette={['#6B7280', '#C2410C']}/>

## The ARR bridge

```sql bridge
select month, opening, new, reactivation, expansion, contraction, churn, closing, paying_customers
from ridgeline.arr_bridge
order by month desc
```

<BarChart data={bridge} x=month y={['new', 'reactivation', 'expansion', 'contraction', 'churn']} yFmt=usd0k title="ARR movements by month" colorPalette={['#C2410C', '#FDBA74', '#F59E0B', '#9CA3AF', '#4B5563']}/>

<DataTable data={bridge} rows=12>
  <Column id=month fmt="mmm yyyy"/>
  <Column id=opening fmt=usd0/>
  <Column id=new fmt=usd0/>
  <Column id=reactivation fmt=usd0/>
  <Column id=expansion fmt=usd0/>
  <Column id=contraction fmt=usd0/>
  <Column id=churn fmt=usd0/>
  <Column id=closing fmt=usd0/>
  <Column id=paying_customers title="Paying customers" fmt=num0/>
</DataTable>

Opening + new + reactivation + expansion + contraction + churn = closing, every month. A customer moving to
another subscription is an expansion or contraction, not churn plus new.

## Deal match statuses

```sql statuses
select * from ridgeline.arr_deal_status
```

<DataTable data={statuses} rows=all>
  <Column id=status title="Status"/>
  <Column id=deals fmt=num0/>
  <Column id=booked_usd title="Booked ARR" fmt=usd0/>
  <Column id=billed_usd title="Billed ARR" fmt=usd0/>
  <Column id=meaning title="What it means" wrap=true/>
</DataTable>

A deal matches a billing change for the same customer: a new subscription for a new or win-back deal, a plan
upgrade for an expansion, 0-30 days after the close date, nearest first. A billing change is claimed by one deal at
most.

## Deals that need a look

```sql flags
select deal_id, customer_id, deal_type, close_date, status, booked_usd, billed_usd,
       coalesce(strftime(effective_on, '%Y-%m-%d'), 'not started') as effective_on
from ridgeline.arr_deal_flags
order by close_date desc
```

<DataTable data={flags} search=true rows=20>
  <Column id=deal_id title="Deal"/>
  <Column id=customer_id title="Customer"/>
  <Column id=deal_type title="Type"/>
  <Column id=close_date title="Closed"/>
  <Column id=status title="Status"/>
  <Column id=booked_usd title="Booked ARR" fmt=usd0/>
  <Column id=billed_usd title="Billed ARR" fmt=usd0/>
  <Column id=effective_on title="Billing started"/>
</DataTable>

The CRM side is made from the billing history with five kinds of planted mistakes (duplicates, won deals never
billed, annual plans booked at 10 months, amount typos, missing deals). The planted labels never reach the
warehouse; the tests check that the statuses above find them.
