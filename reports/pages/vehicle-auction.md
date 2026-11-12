---
title: Vehicle auction
---

A learning project on **simulated** data, separate from the roofing-software company on the rest of this site. A
weekly wholesale auction sells dealers' used cars in three channels: a physical lane, the lane with online simulcast
bidding, and a timed online-only sale. The page asks two questions: what share of the cars offered sell (and what
exactly counts as a sale), and would a lower reserve-price guidance sell more cars and bring sellers more money. Code,
dbt models and tests: [vehicle_auction/](https://github.com/sky-five/ridgeline-analytics/tree/main/vehicle_auction).
Like the renewals list, these numbers come from one fixed, tested run and do not move with the nightly build.

```sql channels
select * from ridgeline.auction_channels order by sort
```

<BigValue data={channels} value=vehicles_total title="Cars consigned" fmt=num0/>
<BigValue data={channels} value=listings_total title="Listings (runs through a sale)" fmt=num0/>
<BigValue data={channels} value=bids_total title="Bids" fmt=num0/>

## Three ways to count sell-through

| Metric | Definition |
|---|---|
| On the block | Listings sold on the block (high bid at or over the reserve) / listings offered |
| Conversion | (Sold on the block + if-sales the seller accepted afterwards) / listings offered |
| Vehicle sell-through | Cars that sold in any run / cars offered at least once |

Withdrawn listings never ran, so they are left out of every denominator. Each rate adds sales the one before leaves
out, so they always come in this order; dbt tests fail if they don't.

<DataTable data={channels}>
  <Column id=channel_label title="Channel"/>
  <Column id=listings_offered title="Listings offered" fmt=num0/>
  <Column id=sell_through_on_block title="On the block" fmt=pct1/>
  <Column id=conversion_rate title="Conversion" fmt=pct1/>
  <Column id=vehicles_offered title="Cars offered" fmt=num0/>
  <Column id=vehicle_sell_through title="Vehicle sell-through" fmt=pct1/>
  <Column id=avg_bidders title="Bidders per run" fmt=num1/>
</DataTable>

More bidders per run means more cars clear their reserve, so simulcast sells best and the timed sale worst. Which rate
a report quotes matters as much as the channel: in the physical lane, the same cars give
<Value data={channels} column=sell_through_on_block fmt=pct0/>,
<Value data={channels} column=conversion_rate fmt=pct0/> or
<Value data={channels} column=vehicle_sell_through fmt=pct0/>.

## Week by week

```sql weekly_on_block
select sale_week, channel_label, sell_through_on_block
from ridgeline.auction_weekly
order by sale_week, channel_label
```

<LineChart data={weekly_on_block} x=sale_week y=sell_through_on_block series=channel_label yFmt=pct0 yMin=0 yMax=1
  title="Sell-through on the block, by sale week" colorPalette={['#C2410C', '#2563EB', '#6B7280']}/>

Pick a channel to see its three rates side by side:

<Dropdown data={channels} name=channel value=channel label=channel_label defaultValue="in_lane"/>

```sql weekly_channel
select sale_week,
       sell_through_on_block as "On the block",
       conversion_rate as "Conversion",
       vehicle_sell_through as "Vehicle sell-through"
from ridgeline.auction_weekly
where channel = '${inputs.channel.value}'
order by sale_week
```

<LineChart data={weekly_channel} x=sale_week y={['On the block', 'Conversion', 'Vehicle sell-through']} yFmt=pct0
  yMin=0 yMax=1 title="Three definitions, one channel" colorPalette={['#9CA3AF', '#C2410C', '#111827']}/>

The vehicle rate puts each car in the week it was first offered. Cars first offered in the last few weeks have had
fewer chances to relist before the data ends, so that line drops at the right edge. That is a cut-off, not a slump.

## Reserve-price test

```sql rt
select * from ridgeline.auction_reserve_test order by sort
```

```sql conv
select * from ${rt} where unit = 'rate'
```

```sql money
select * from ${rt} where unit = 'usd'
```

From the week of 2026-04-06, each newly consigned car is split 50/50 by a hash of its id. Control keeps the usual
reserve guidance (100% of book value); treatment gets 95% of book. The outcome is the car's first run, so relists
(which lower the reserve again) don't blur the comparison.

**Sample-ratio check first.** <Value data={conv} column=vehicles_control fmt=num0/> control cars vs
<Value data={conv} column=vehicles_treatment fmt=num0/> treatment cars (p = <Value data={conv} column=srm_p_value fmt=num2/>)
is consistent with a fair split, so the readout goes ahead. The same hash split on cars consigned before the test
shows <Value data={conv} column=aa_conversion_diff fmt=pct1/> (p = <Value data={conv} column=aa_conversion_p_value fmt=num2/>):
no gap before the change.

<BigValue data={conv} value=control title="Conversion, control" fmt=pct1/>
<BigValue data={conv} value=treatment title="Conversion, 95% reserve" fmt=pct1/>
<BigValue data={conv} value=diff title="Measured difference" fmt=pct1/>
<BigValue data={conv} value=true_diff title="True difference" fmt=pct1/>

The lower reserve converted <Value data={conv} column=diff fmt=pct1/> points more first runs (95% CI
<Value data={conv} column=ci_low fmt=pct1/> to <Value data={conv} column=ci_high fmt=pct1/>).

<BigValue data={money} value=control title="Proceeds per car, control" fmt=usd0/>
<BigValue data={money} value=treatment title="Proceeds per car, 95% reserve" fmt=usd0/>
<BigValue data={money} value=diff title="Measured difference" fmt=usd0/>
<BigValue data={money} value=true_diff title="True difference" fmt=usd0/>

Seller proceeds per car offered, counting a no-sale as $0, rose by <Value data={money} column=diff fmt=usd0/>
(95% CI <Value data={money} column=ci_low fmt=usd0/> to <Value data={money} column=ci_high fmt=usd0/>).

<DataTable data={rt}>
  <Column id=metric title="First run, per car offered"/>
  <Column id=diff title="Measured difference" fmt=num4/>
  <Column id=ci_low title="CI low" fmt=num4/>
  <Column id=ci_high title="CI high" fmt=num4/>
  <Column id=true_diff title="True difference" fmt=num4/>
  <Column id=ci_covers title="CI covers the truth"/>
</DataTable>

**The truth is known.** Bids never depend on the reserve in this simulation, so the simulator knows how every test
car's first run would have ended under the other arm. That counterfactual is kept out of the warehouse; the tests
check that both intervals cover the true effect on the same cars.

**Don't compare sold prices.** Cars sold under the lower reserve fetch
<Value data={conv} column=price_to_book_treatment fmt=num3/> of book on average, against
<Value data={conv} column=price_to_book_control fmt=num3/> in control. That is a selection effect, not a price cut:
treatment sells cars that control would have no-sold. Proceeds per car offered is the fair money comparison.

Limits: the first-run proceeds gain overstates the real one, because many control no-sales sell a week later on a
relist. And real bidders can anchor on a visible reserve; here they don't, which is what makes the truth knowable.
