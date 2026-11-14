---
title: Quote funnel
---

A teardown on **simulated** data, separate from the roofing-software company on the rest of this site. An insurance
quote-comparison site asks a panel of carriers to price each shopper, the shopper may click through to one, and the
carrier reports back when a policy is bound. The page asks three things: how to define quote-to-bind so it measures
shoppers, why the old dashboard showed a conversion drop that never happened, and what adding a carrier to the panel
would be worth. Code and tests: [quote_funnel/](https://github.com/sky-five/ridgeline-analytics/tree/main/quote_funnel).
These numbers come from one fixed, tested run and do not move with the nightly build.

```sql summary
select * from ridgeline.quote_funnel_summary
```

<BigValue data={summary} value=sessions title="Sessions (26 weeks)" fmt=num0/>
<BigValue data={summary} value=quote_requests title="Logged quote requests" fmt=num0/>
<BigValue data={summary} value=carrier_quotes title="Carrier prices" fmt=num0/>
<BigValue data={summary} value=binds title="Policies bound" fmt=num0/>
<BigValue data={summary} value=quote_to_bind title="Quote-to-bind (per session)" fmt=pct1/>

The one-page decision memo: [results/memo.md](https://github.com/sky-five/ridgeline-analytics/blob/main/quote_funnel/results/memo.md).

## Per session, not per request

Every rate counts sessions over sessions: quote rate = sessions with a price / sessions, click rate = sessions that
clicked through / quoted sessions, bind rate = bound sessions / clicked sessions, and quote-to-bind = bound sessions
/ quoted sessions. The old dashboard divided binds by quote requests instead. That works only while the site logs one
request per session.

From the week of <Value data={summary} column=break_week/>, the site starts logging every form resubmit as its own
request. Shoppers do not change. Requests per session jump from <Value data={summary} column=requests_per_session_before fmt=num2/>
to <Value data={summary} column=requests_per_session_after fmt=num2/>; a detector that is not told the date finds that week
from the request log alone.

```sql weekly_rates
select week,
       quote_to_bind as "Per session",
       quote_to_bind_per_request as "Per request (old dashboard)"
from ridgeline.quote_funnel_weekly
order by week
```

<LineChart data={weekly_rates} x=week y={['Per session', 'Per request (old dashboard)']} yFmt=pct0 yMin=0
  title="Weekly quote-to-bind, two ways" colorPalette={['#111827', '#C2410C']}>
  <ReferenceLine data={summary} x=break_week label="Resubmits logged from here" color="#6B7280"/>
</LineChart>

<BigValue data={summary} value=per_request_diff title="Old rate, change" fmt=pct1/>
<BigValue data={summary} value=per_session_diff title="Session rate, change" fmt=pct1/>
<BigValue data={summary} value=share_of_drop_from_request_count title="Drop explained by request count" fmt=pct0/>

Comparing the 13 weeks either side of the break, binds per request fall from <Value data={summary} column=per_request_before fmt=pct1/>
to <Value data={summary} column=per_request_after fmt=pct1/>, a <Value data={summary} column=relative_drop_per_request fmt=pct0/> relative
drop that a significance test would call real. Bound sessions per quoted session go from <Value data={summary} column=per_session_before fmt=pct1/>
to <Value data={summary} column=per_session_after fmt=pct1/> (95% CI <Value data={summary} column=per_session_ci_low fmt=pct1/> to
<Value data={summary} column=per_session_ci_high fmt=pct1/>, p = <Value data={summary} column=per_session_p fmt=num2/>): no change.

```sql weekly_counts
select week, sessions as "Sessions", requests as "Logged requests"
from ridgeline.quote_funnel_weekly
order by week
```

<LineChart data={weekly_counts} x=week y={['Sessions', 'Logged requests']} yMin=0 title="Sessions stay flat; logged requests jump"
  colorPalette={['#111827', '#9CA3AF']}>
  <ReferenceLine data={summary} x=break_week color="#6B7280"/>
</LineChart>

## The funnel by segment

```sql segments
select * from ridgeline.quote_funnel_segments order by sort
```

<DataTable data={segments}>
  <Column id=segment_label title="Segment"/>
  <Column id=sessions title="Sessions" fmt=num0/>
  <Column id=quotes_per_session title="Prices per session" fmt=num1/>
  <Column id=quote_rate title="Quote rate" fmt=pct1/>
  <Column id=click_rate title="Click rate" fmt=pct1/>
  <Column id=bind_rate title="Bind rate" fmt=pct1/>
  <Column id=quote_to_bind title="Quote-to-bind" fmt=pct1/>
  <Column id=commission title="Commission" fmt=usd0/>
</DataTable>

<BarChart data={segments} x=segment_label y=quote_to_bind yFmt=pct0 sort=false title="Quote-to-bind by segment"/>

Non-standard risks get fewer prices to compare, so fewer of those shoppers click through and fewer bind. Non-standard
auto has the thinnest panel, which is where a new carrier could add the most.

## Sizing a new carrier

```sql carrier
select * from ridgeline.quote_funnel_carrier order by sort
```

```sql binds
select * from ${carrier} where sort = 0
```

```sql money
select * from ${carrier} where sort = 1
```

A candidate carrier, keenly priced in non-standard auto, wants to join the panel. Before launch the team has the
half-year's history and a rating sample: the candidate priced <Value data={binds} column=sample_sessions fmt=num0/> past
auto sessions and quoted <Value data={binds} column=sample_quoted_by_candidate fmt=num0/> of them. Click, carrier-choice
and bind models fitted on the history score each sampled session with and without the candidate's price, scaled to
all <Value data={binds} column=auto_sessions fmt=num0/> auto sessions.

<BigValue data={binds} value=estimate title="Added binds, estimate" fmt=num0/>
<BigValue data={binds} value=truth title="Added binds, replayed truth" fmt=num0/>
<BigValue data={money} value=estimate title="Added commission, estimate" fmt=usd0/>
<BigValue data={money} value=truth title="Added commission, replayed truth" fmt=usd0/>

<DataTable data={carrier}>
  <Column id=measure title="Per half-year"/>
  <Column id=estimate title="Estimate" fmt=num0/>
  <Column id=ci_low title="95% CI low" fmt=num0/>
  <Column id=ci_high title="95% CI high" fmt=num0/>
  <Column id=truth title="Replayed truth" fmt=num0/>
</DataTable>

**The truth is known.** Every random draw a shopper makes is fixed up front, so the simulator can replay the same
shoppers with the candidate on the panel. The sizing never reads that replay; the tests check that both intervals
cover it. The interval is sampling noise only, not model error.

```sql lost
select carrier, source, binds_lost
from ridgeline.quote_funnel_lost_binds
order by carrier, source
```

<BarChart data={lost} x=carrier y=binds_lost series=source type=grouped title="Binds the current panel would lose to the candidate"
  colorPalette={['#C2410C', '#111827']}/>

Not every policy the candidate writes is new: some shoppers would have bound with another carrier anyway. With an
assumed <Value data={binds} column=onboarding_cost_assumed fmt=usd0/> one-off onboarding cost (a placeholder), the added
commission pays it back in about <Value data={binds} column=payback_months fmt=num1/> months. The memo recommends launching
on a share of auto traffic first and checking the measured lift against this estimate.
