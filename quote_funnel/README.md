# Quote-to-bind funnel teardown (simulated data)

An insurance quote-comparison site asks a panel of carriers to price each shopper's risk, the shopper may click
through to one of them, and the carrier reports back when a policy is bound. This folder defines the funnel
metrics, shows how a change in what gets counted can fake a conversion drop, and sizes the effect of adding a
carrier to the panel before it goes live. Everything runs in DuckDB on seeded synthetic data; nothing here
comes from a real site, carrier or shopper.

```bash
python -m quote_funnel           # simulate, build the marts, run the teardown and sizing, write results/
python -m quote_funnel --check   # fail if the committed results are out of date (CI)
```

The one-page decision memo is [results/memo.md](results/memo.md).

## The data

`simulate.py` makes 26 weeks of sessions (2026-01-05 to the week of 2026-06-29): 38,929 sessions, 47,780
logged quote requests, 131,697 carrier prices, 20,382 click-throughs and 4,589 binds. Each session is one risk
in one of four segments (standard or non-standard, auto or home). Six carriers each quote some of the segments,
at their own price level; non-standard auto has the thinnest panel (1.7 prices per session vs 4.2 in standard
auto). Shoppers click more when the best price is low and there are more prices to compare, pick a carrier on
price and brand, and bind less often when the price they picked is high.

Two facts are planted. From 2026-04-06 the site logs every form submit as its own quote request, where before
it kept only the first submit of a session; shoppers do not change that day. And a candidate carrier, keenly
priced in non-standard auto, is asking to join the panel. Every random draw a shopper makes is fixed up front,
so the same shoppers can be replayed with the candidate on the panel. That replay is the truth the sizing is
checked against; the sizing code never reads it (a test spies on the simulator to make sure).

## Metric definitions

`metrics.py` builds `mart.session_funnel` (one row per session), `mart.funnel_weekly` and
`mart.funnel_by_segment` in SQL. The unit is the session, so every rate is sessions over sessions:

| Metric | Definition | Half-year |
|---|---|---|
| Quote rate | Sessions with at least one price / sessions | 98.5% |
| Click rate | Sessions that clicked through / quoted sessions | 53.2% |
| Bind rate | Bound sessions / clicked sessions | 22.5% |
| Quote-to-bind | Bound sessions / quoted sessions | 12.0% |
| Commission per session | Commission on binds / sessions | $10.63 |
| Requests per session | Logged requests / sessions; a logging health check, not a shopper metric | 1.23 |

Quote-to-bind is 14.0% in standard auto and 4.0% in non-standard auto. The old dashboard's version, binds per
quoted request, is kept in the weekly mart only so the teardown can show what it does.

## The fake drop

`counting.py` looks for the week where requests per session jumps the most (it is not told the date) and
compares both rates either side of it. It finds 2026-04-06, where requests per session go from 1.00 to 1.46.

| | Weeks 1-13 | Weeks 14-26 | Change (95% CI) |
|---|---|---|---|
| Binds per quoted request (old dashboard) | 12.0% | 8.2% | -3.8 pp (-4.4 to -3.3), p < 0.001 |
| Bound sessions per quoted session | 12.0% | 11.9% | -0.1 pp (-0.7 to +0.6), p = 0.77 |

Sessions (1,501 vs 1,493 a week) and binds (178 vs 175 a week) stay flat; the larger request count explains 98%
of the 32% relative fall. A test checks that the old rate falls by more than a quarter while the session rate's
interval covers zero.

## Sizing the candidate carrier

`carrier.py` works from what a team would have before launch: the half's history and a rating sample, where the
candidate priced 3,000 random past auto sessions (it quoted 2,302). Three models are fitted on the history: a
logistic click model (segment, number of prices, best price), a conditional-logit choice model (each price
against the session's best, plus a pull per carrier; the newcomer gets the panel average), and a logistic bind
model (segment, the chosen price). Prices are read against a per-session risk index (how far the session's
prices sit above or below each carrier's usual level), so a risky shopper's high price is not taken for a bad
deal. Each sampled session is scored with and without the candidate's price, scaled to all 27,081 auto
sessions, and bootstrapped over the sample for an interval (models held fixed).

| Per half-year | Estimate (95% CI) | Replayed truth |
|---|---|---|
| Added binds | 561 (515 to 621) | 534 |
| Added commission | $58,988 ($54,404 to $64,866) | $56,060 |
| Policies the candidate writes | 967 | 866 |

So about 4 in 10 of the candidate's policies would have gone to another carrier anyway. A first version without
the risk index estimated only 196 added binds against the true 534: high prices were mostly risky shoppers, not
bad deals, so the models read shoppers as far less price-sensitive than they are. With an assumed $25,000
one-off onboarding cost (a placeholder for the real figure), the added commission pays it back in about 2.5
months. The interval covers sampling noise only, not model error; the memo says to launch on a share of auto
traffic first.

## Files

| File | What it does |
|---|---|
| `simulate.py` | The seeded sessions, carriers, prices, clicks and binds; the logging change; the replay |
| `metrics.py` | Metric definitions and the three marts in DuckDB SQL |
| `counting.py` | Finds the logging break and tests both rates either side of it |
| `carrier.py` | Rating sample, click / choice / bind models, the estimate and the replayed truth |
| `memo.py` | Writes `results/memo.md` from the summary, so no number in it is typed by hand |
| `results/` | `summary.json`, `funnel_weekly.csv` (26 rows) and `memo.md`, checked by `--check` |

Tests: `tests/quote_funnel/` (11 tests: the metric rules on hand-made rows, the planted logging change, the
sizing against the replay, the memo against the summary, committed results up to date).
