# ARR source of truth

Sales says ARR grew by what the CRM shows as closed-won. Finance says it grew by what billing started. This folder makes the two agree: billing's contract side is the one source of truth for ARR, every CRM deal is matched to the billing change it should have started, and a monthly walk explains the gap between them step by step, to the cent.

> **All data is synthetic.** Billing is saas-world-sim's billing pack (the same one `revrec/` uses). The CRM deals are made from that billing history by `crm_side.py` with a fixed seed. Nothing comes from a real CRM, billing system or customer.

```bash
python -m arr_source_of_truth                      # load as of 2026-09-30, dbt build, score, write results/summary.json
python -m arr_source_of_truth --as-of 2026-10-31   # any other date (results file left alone)
pytest tests/arr_source_of_truth -q                # 36 tests, about 20 seconds
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

## Asking the ARR models

`agent.py` is an agent that answers ARR questions only through these models, says which model each answer came from, and refuses everything else.

It gets five read-only tools on the ARR warehouse, and no SQL tool, so it can't pick its own definition of ARR:

| Tool | Model it reads |
|---|---|
| `arr_bridge(month)` | `arr_bridge`: opening, new, reactivation, expansion, contraction, churn, closing ARR and paying customers |
| `arr_walk(month)`, `arr_walk_range(first_month, last_month)` | `arr_booking_walk`: every walk step for a month, or summed over a range |
| `deal_status_counts(close_month)`, `find_deals(deal_id, customer_id, status)` | `arr_deal_matches`: deals per match status, or single deals with booked and billed ARR |

The model ends with a json block (answer, unit, models, refused). Before anything reaches the person asking, `check` holds the answer back unless it cites at least one model, cites only models a tool read in that conversation, and every number in it appears in a tool result. A sum, rounding or forecast of the model's own is held back, not shown. Caps: 6 model calls and 60k tokens per question. The model client is the analyst's (`analyst/llm.py`): Gemini's free tier, Claude, or a no-model keyword baseline (`agent_baseline.py`, a phrase table that picks one tool call and copies one field).

```bash
python -m arr_source_of_truth                                                        # build warehouse/arr.duckdb
python -m arr_source_of_truth.agent "What was closing ARR at the end of September 2026?"   # 736260 usd  (source: arr_bridge)
python -m arr_source_of_truth.agent "What will ARR be at the end of 2027?"                 # refused, exits 1
python -m arr_source_of_truth.agent --provider gemini "How many deals are duplicates?"     # needs GEMINI_API_KEY
```

### Eval

`agent_eval/questions.yml` has 20 questions on the 2026-09-30 build: 14 the models answer (bridge, walk, a walk over 22 months, deal counts, one deal's status), with the truth read straight from the models by SQL, and 6 they don't (a forecast, CAC, sales reps, deleting deals, retention by plan, an off-topic question). An answer is right when the check delivered it, the number or status equals the truth, and it cites a model the question allows. The number that matters most is "wrong, delivered": a wrong number that reached the person.

| Run | Answerable: right | Wrong, delivered | Held back by the check | Refused | Out of scope: refused |
|---|---|---|---|---|---|
| Keyword baseline (no model) | 11 of 14 | 0 | 0 | 3 | 6 of 6 |
| gemini-3.5-flash-lite (Gemini API, free tier), recorded 2026-11-12 | 14 of 14 | 0 | 0 | 0 | 6 of 6 |

The baseline refuses three questions whose words are not in its phrase table ("customers were paying", "ARR grow", "duplicate deals add"); it never guesses. The Gemini run used 37 model requests for the 20 questions (38,397 input / 1,679 output tokens): every answerable question took one tool call, except August's growth, where it read the bridge and then the walk and cited the walk. It refused four out-of-scope questions without a tool call and two (sales reps, retention by plan) after reading a model and finding nothing that answers them. The check held back nothing in either run; the tests show what it stops (an answer citing a model no tool read, a number of the model's own, a rounded figure).

Runs are saved to `agent_eval/results/` with every reply and tool result, so they replay without a key; `--db` also reruns each recorded tool call on a fresh build and fails if any result has changed. The Gemini run is recorded by the `record ARR agent` workflow (`.github/workflows/record-arr-agent.yml`), which uses the repository's `GEMINI_API_KEY` secret.

```bash
python -m arr_source_of_truth.agent_eval                     # keyword baseline, builds its own warehouse
python -m arr_source_of_truth.agent_eval --replay arr_source_of_truth/agent_eval/results/keyword-baseline.json --db warehouse/arr.duckdb
pytest tests/arr_source_of_truth/test_agent.py -q            # 20 tests
```

Results differ by model and by run; the table shows one recorded run each.
