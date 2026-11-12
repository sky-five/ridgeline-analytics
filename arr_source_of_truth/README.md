# ARR source of truth

Sales says ARR grew by what the CRM shows as closed-won. Finance says it grew by what billing started. This folder makes the two agree: billing's contract side is the one source of truth for ARR, every CRM deal is matched to the billing change it should have started, and a monthly walk explains the gap between them step by step, to the cent.

> **All data is synthetic.** Billing is saas-world-sim's billing pack (the same one `revrec/` uses). The CRM deals are made from that billing history by `crm_side.py` with a fixed seed. Nothing comes from a real CRM, billing system or customer.

```bash
python -m arr_source_of_truth                      # load as of 2026-09-30, dbt build, score, write results/summary.json
python -m arr_source_of_truth --as-of 2026-10-31   # any other date (results file left alone)
pytest tests/arr_source_of_truth -q                # 16 tests, about 11 seconds
```

The warehouse goes to `warehouse/arr.duckdb`. The main warehouse and the nightly build are not touched.

## The two systems

- **Billing** (`raw_billing.subscription_changes`): one row each time a subscription's MRR changes (new, upgrade, seats up or down, churn, cancel with refund).
- **CRM** (`raw_crm.won_deals`): a closed-won deal for every new subscription and every plan upgrade, closed 0-14 days before billing starts it. Seat changes happen in the product and never reach the CRM.

Five kinds of mistakes are planted in the CRM, each with a label that is never loaded into the warehouse:

| Planted mistake | How often |
|---|---|
| Missing deal: a new subscription or upgrade no one logged | 3% of billing changes |
| Annual plan booked at what the customer pays (10 months) instead of its ARR (12) | 25% of annual sign-ups |
| Amount typo, off by 10-30% | 3% of deals |
| Duplicate: the same deal logged twice, a few days apart | 2% of deals |
| Won, never billed: an expansion marked won that billing never started | 2% of new customers |

## Models (dbt on DuckDB)

| Model | What it is |
|---|---|
| `arr_customer_months` | Contract MRR per customer at each month end, from billing. ARR = 12 x this. |
| `arr_movements` | One row per customer and month whose ARR changed: new, reactivation, expansion, contraction or churn, classified per customer (moving to another subscription is not churn plus new). |
| `arr_bridge` | Opening + new + reactivation + expansion + contraction + churn = closing ARR, per month. |
| `arr_deal_matches` | Each deal matched to a billing change: same customer, a new subscription (for new or win-back deals) or a plan upgrade (for expansions), 0-30 days after the close date, nearest first. A change is claimed by one deal at most. The status says how they agree: `agrees`, `annual_at_billed`, `amount_differs`, `duplicate` (an unmatched copy of a matched deal within 14 days), `awaiting_billing` (unmatched, closed in the last 30 days) or `won_not_billed`. |
| `arr_booking_walk` | Per month, CRM booked ARR to billing ARR, one column per step (below). |

The walk, per month:

```
CRM booked ARR (by close date)
  - duplicates - won, not billed - awaiting billing
  + amount fixes (billed - booked, on matched deals)
  + timing (deals billed in a different month than they closed)
  + missing deals (billing changes with no deal)
  = billing ARR from new subscriptions and upgrades
  + seat changes + churn and cancellations
  = closing - opening ARR in arr_bridge
```

## Tested definitions

- dbt singular tests: the bridge rolls forward every month; the walk reaches billing and then the bridge, to the cent, every month.
- dbt unit tests: one customer through new, expansion, contraction, churn and reactivation; a deal taking the nearest upgrade, its duplicate, an annual plan booked at 10 months, and a deal with nothing in billing.
- pytest: the dbt bridge equals revrec's plain-Python reference (a replay of contract changes) in all 21 months; every matched deal lands on the change it came from; every planted mistake is caught with no false flags; the CRM export is deterministic and an earlier date is a prefix of a later one; `results/summary.json` matches the code.

## Results as of 2026-09-30

| Check | Number |
|---|---|
| Deals and billing changes | 491 closed-won deals; 470 new subscriptions and upgrades in billing |
| Matching | 461 deals matched, all to the change they came from (0 wrong matches) |
| Planted mistakes caught | 18 of 18 duplicates, 5 of 5 won-not-billed, 16 of 16 typos, 9 of 9 missing deals, 36 of 37 annual-at-billed (the 37th closed in late September and billing has not started it yet, so it is awaiting billing). 0 false flags |
| Awaiting billing | 7 deals closed in September, not yet started |
| ARR | $736,260 closing, 285 paying customers (the same as `revrec/`) |

September 2026, in dollars:

```
CRM booked                 $75,410
duplicates                 -$7,620
awaiting billing          -$17,640
amount fixes                 -$170
timing                      $5,880
missing deals                   $0
= billing new + upgrades   $55,860
seat changes                $5,220
churn and cancellations   -$49,260
= net change in ARR        $11,820   ($724,440 -> $736,260)
```

From December 2024 to September 2026 the CRM booked $1,141,870 of ARR; billing started $1,104,060. Annual plans booked at the paid amount understate the CRM by $17,330, duplicates overstate it by $47,520.

## The page

[ARR: from CRM to billing](https://sky-five.github.io/ridgeline-analytics/arr-walk/) on the Evidence site shows the walk for any closed month (pick it from the list), the walk and the bridge for every month, the count and ARR of deals in each match status with what the status means, and a searchable list of every deal that does not simply agree.

`report.py` builds this warehouse as of the run date and copies the page's tables, converted from cents to dollars and nothing else, into `reporting.arr_*` in the main warehouse, where the site reads them. `scripts/run_all.py` calls it after the dashboard export, so the nightly build moves the page forward one day at a time:

```bash
python -m arr_source_of_truth.report --as-of 2026-11-11   # build warehouse/arr.duckdb, write reporting.arr_* to warehouse/ridgeline.duckdb
```

On the 2026-11-11 build (last closed month October 2026): $786,540 closing ARR, 297 paying customers, 535 closed-won deals, 87 that need a look. Six pytest tests (`tests/arr_source_of_truth/test_report.py`) check that the page's walk adds up to billing and to the bridge every month, that its numbers at 2026-09-30 equal `results/summary.json`, and that the page reads only tables the build writes.

Next for this folder (not built yet): an agent that answers ARR questions only through these models.
