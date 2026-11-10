# Acquisition spend: channel CAC and a budget what-if

Where should the next marketing dollar go? This module answers it from the warehouse's governed marts: the
signup funnel (`fct_account_funnel`), the lead score and its deciles (`fct_pqa_scores`) and daily spend by
channel (`fct_marketing_channel_daily`).

> **All data is synthetic**, from the simulated roofing-software business in
> [saas-world-sim](https://github.com/sky-five/saas-world-sim) v0.4.0.

```bash
python scripts/run_all.py --fresh --as-of 2026-06-30   # build the warehouse on the fixed snapshot
python -m acquisition_spend                            # write results/
python -m acquisition_spend --check                    # fail if results/ is out of date (runs in CI)
python -m acquisition_spend --move trade_show google_ads 2000   # one what-if on the monthly budget
```

## How it works

| File | What it does |
|---|---|
| `cac.py` | Channel CAC = ad spend in a window / signups from that window that paid within 60 days. Only signups whose 60-day outcome is known are used (the window refuses immature signups). Free channels (referral, organic) show a CAC of 0 and stay in the blended number. |
| `whatif.py` | A paid channel's yield per dollar = signups per dollar × its mix across the ten lead-score deciles × each decile's paid rate (all channels pooled). A budget move changes expected paid accounts by the difference in yield. Also: spend per signup that lands in the top three deciles, and a back-test. |
| `report.py` | Fixed windows on the 2026-06-30 snapshot: CAC over May 2025 to April 2026 (the last 12 whole months with known outcomes); the back-test fits on May to December 2025 and predicts January to April 2026 from spend alone. |

The what-if is linear on purpose: it assumes cost per signup and the decile mix hold at the new spend. Real
channels saturate, so it is meant for moves of about 10% of a channel's budget, not for zeroing one out. The lead
score was trained on signups before 2026, so the 2026 months in the back-test are ones it never saw.

## Results (warehouse as of 2026-06-30)

| Channel | Signups | Paid in 60 days | Spend | CAC | Paid per $1k | Spend per top-3-decile signup |
|---|---|---|---|---|---|---|
| Google Ads | 960 | 130 | $101,858 | $784 | 1.28 | $398 |
| Facebook | 605 | 72 | $60,178 | $836 | 1.06 | $421 |
| Supplier partner | 375 | 64 | $107,999 | $1,687 | 0.64 | $947 |
| Trade show | 234 | 41 | $168,000 | $4,098 | 0.24 | $2,507 |
| Organic / referral | 1,071 | 211 | $0 | n/a | | |
| **All channels** | 3,245 | 518 | $438,035 | **$846** | | |

Paid channels alone: $1,427 per paying account. Trade-show and supplier-partner signups convert best of the paid
channels (17-18% vs 12-14%), but they cost roughly 3 to 7 times as much per signup, so per dollar they buy the fewest paying
accounts. Lead-score deciles 8-10 pay at 27%, 41% and 58%; deciles 1-7 at 2-10%.

**What-if** on the average monthly budget of $36,503: moving 10% of trade-show spend ($1,400) to Google Ads adds
1.5 expected paid accounts a month (25.4 → 26.9) and cuts paid-channel CAC from $1,438 to $1,360. The worst
move, 10% of Google Ads into trade shows, loses 0.9. All 12 pairwise moves are in `results/budget_moves.csv`.

**Back-test:** fitted on May-December 2025, the model predicted 98.7 paid accounts from January-April 2026 paid
spend; the actual was 101 (2.2% low). Per channel it is rougher: it under-predicted Google Ads and Facebook by
about 7 each and over-predicted trade shows by 7 (15.3 vs 8), so treat channel-level numbers as a direction, not
a forecast.

Files: `results/channel_cac.csv`, `channel_yield.csv`, `budget_moves.csv`, `backtest.csv`, `summary.json`.
