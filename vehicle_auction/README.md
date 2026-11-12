# Wholesale vehicle auction (learning project, simulated data)

A learning project on simulated data. A weekly wholesale auction sells dealers' used vehicles in three
channels: a physical lane, a lane with online simulcast bidding, and a timed online-only sale. It asks two
questions: what share of the cars offered actually sell in each channel (and what exactly counts), and would a
lower reserve-price guidance sell more cars and bring sellers more money. Nothing here comes from a real
auction, dealer or buyer.

```bash
python -m vehicle_auction          # simulate, load DuckDB, dbt build, write results/
python -m vehicle_auction --check  # fail if the committed results are out of date
```

## How it works

| File | What it does |
|---|---|
| `simulate.py` | 26 weekly sales, 2026-01-05 to 2026-06-29, seeded. Each car gets a book value from its segment, age, mileage and condition grade, and a seller's reserve near the reserve guidance. Bidders arrive by channel (simulcast draws the most) and the high bid lands one $100 increment over the second-highest valuation. A high bid within 10% under the reserve can become an if-sale; a no-sale may be relisted next week with a 3% lower reserve, up to 3 runs; 4% of listings are withdrawn before they run. |
| `load.py` | Loads `vehicles`, `listings`, `bids` and the test's `test_assignments` log into `raw_auction` in DuckDB, then builds the dbt project in `dbt/`. |
| `dbt/` | `fct_listings` (one row per run, with the offered / sold-on-block / if-sale / converted flags), `fct_vehicles` (one row per car), `sell_through_weekly`, `vehicle_sell_through_weekly` (cars by the week first offered), `sell_through_by_channel`, `reserve_test_arms`. Singular tests pin the metric rules. |
| `readout.py` | Reads out the reserve-price test and checks it against the planted truth. |
| `report.py` | Writes `results/sell_through_weekly.csv` and turns the committed results into the dashboard tables. |

## Metric definitions

| Metric | Definition |
|---|---|
| Offered | A listing that ran in a sale. Withdrawn listings are not offered and are left out of every denominator. |
| Sell-through on the block | Listings sold on the block (high bid at or over the reserve) / listings offered. |
| Conversion rate | (Sold on the block + if-sales the seller accepted afterwards) / listings offered. |
| Vehicle sell-through | Cars that sold in any run / cars offered at least once. A car that no-sells twice and then sells counts once, as sold. |

The three rates always come in that order, and dbt tests fail if they don't: each step adds sales the one before
leaves out. The tests also recount every channel's rates in pandas straight from the raw frames and compare.
Counting withdrawn listings as offered would pull on-block sell-through from 58.1% down to 55.8%.

## Sell-through by channel

All 26 sales: 12,569 cars, 15,064 listings (14,477 offered), 62,796 bids.

| Channel | Listings offered | On the block | Conversion | Vehicle sell-through | Bidders per run |
|---|---|---|---|---|---|
| Physical lane | 5,790 | 57.2% | 70.3% | 84.0% | 4.2 |
| Lane + simulcast | 4,821 | 69.9% | 80.1% | 90.2% | 5.6 |
| Timed online | 3,866 | 44.7% | 56.9% | 74.3% | 3.0 |

More bidders per run means more cars clear their reserve, so simulcast sells best and the timed sale worst. Which
rate a report quotes matters as much as the channel: in the lane, the same cars give 57%, 70% or 84%.

## Reserve-price test

From the week of 2026-04-06, each newly consigned car is split 50/50 by a hash of its id. Control keeps the usual
reserve guidance (100% of book value); treatment gets 95% of book. The outcome is the car's first run, so relists
(which lower the reserve again) don't blur the comparison.

| First run, per car offered | Control (100% of book) | Treatment (95% of book) | Difference (95% CI) | True difference |
|---|---|---|---|---|
| Cars | 3,190 | 3,110 | sample-ratio check p = 0.31 | |
| Conversion rate | 68.1% | 80.3% | +12.2 pp (+10.0 to +14.4) | +13.1 pp |
| Seller proceeds (0 if no sale) | $7,202 | $8,497 | +$1,295 ($985 to $1,605) | +$1,365 |
| Price / book when sold | 1.028 | 1.020 | not compared | |

- **Sample-ratio check first.** 3,190 vs 3,110 is consistent with a fair 50/50 split, so the readout goes ahead.
- **A/A check.** The same hash split on cars consigned before the test shows +1.1 pp (p = 0.38): no gap before
  the change.
- **The truth is known.** Bids never depend on the reserve in this simulation, so the simulator knows how every
  test car's first run would have ended under the other arm. That counterfactual is kept out of the warehouse;
  the tests check that both confidence intervals cover the true effect on the same cars.
- **Don't compare sold prices.** Cars sold under the lower reserve sell for less of their book value on average.
  That is a selection effect, not a price cut: treatment sells cars that control would have no-sold. Proceeds per
  car offered, with 0 for a no-sale, is the fair money comparison.

Limits: the first-run proceeds gain overstates the real one, because many control no-sales sell a week later on a
relist. And real bidders can anchor on a visible reserve; here they don't, which is what makes the truth knowable.

## Dashboard page

The site's [Vehicle auction page](https://sky-five.github.io/ridgeline-analytics/vehicle-auction/) reads three tables
that `scripts/export_reporting.py` writes from the committed `results/summary.json` and
`results/sell_through_weekly.csv`: `reporting.auction_channels`, `auction_weekly` (78 rows, 3 channels by 26 weeks)
and `auction_reserve_test`. It shows sell-through by channel with the three definitions side by side, the same by sale
week with a channel picker, and the reserve test with both confidence intervals next to the true effect. The numbers
come from one fixed run, so they don't move with the nightly build; the nightly smoke test requests the page.

By week, the vehicle rate puts each car in the week it was first offered. Cars first offered near the end have had
fewer chances to relist, so the rate falls in the last weeks (physical lane: 74.8% for the 2026-06-29 week against
84.0% overall). That is the data ending, not a slump.

## Tests

`tests/vehicle_auction/` (26 tests, about 10 seconds). They build a fresh warehouse and check that the simulation and
the split are deterministic, that only cars consigned in the test window are assigned, that the counterfactual
stays out of `raw_auction`, the metric definitions above against an independent count, the sample-ratio and A/A
checks, that the confidence intervals cover the true effect, that the committed results match the code, and that
the dashboard tables add up to the channel totals and the page reads only columns they have.
