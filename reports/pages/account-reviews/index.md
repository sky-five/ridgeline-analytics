---
title: Account reviews
---

One page template, many accounts. Each link below opens a review page for one of the
<Value data={accts} column=n fmt=num0/> largest paying accounts by MRR, all drawn from
[the same template](https://github.com/sky-five/ridgeline-analytics/blob/main/reports/pages/account-reviews/%5Baccount_id%5D.md).
The monthly numbers on every review are the governed metrics (MRR, support tickets, measurement orders and redos,
homeowner leads) grouped by account, the same definitions behind the company-wide pages and the AI analyst. Data is
simulated.

The [opportunities page](/account-reviews/opportunities) lists every paying account whose measurement orders are
falling or whose lead close rate has dipped.

```sql accts
select count(*) as n, sum(mrr) as mrr, min(as_of) as as_of from ridgeline.account_review
```

```sql reviews
select rank, account_id, company_name, region, crew_size, plan, mrr, health_score, risk_band,
       '/account-reviews/' || account_id as link
from ridgeline.account_review
order by rank
```

<BigValue data={accts} value=n title="Accounts reviewed" fmt=num0/>
<BigValue data={accts} value=mrr title="Their MRR" fmt=usd0k/>

<DataTable data={reviews} link=link rows=all>
  <Column id=rank title="#"/>
  <Column id=company_name title="Account"/>
  <Column id=region/>
  <Column id=crew_size title="Crew"/>
  <Column id=plan/>
  <Column id=mrr title="MRR" fmt=usd0/>
  <Column id=health_score title="Health score"/>
  <Column id=risk_band title="Band"/>
</DataTable>

{#each reviews as r}
<a href="/account-reviews/{r.account_id}" class="hidden">{r.company_name}</a>
{/each}
