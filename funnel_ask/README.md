# Ask the funnel

A question box on the site's [Ask the funnel page](https://sky-five.github.io/ridgeline-analytics/ask-the-funnel/)
that answers only with governed funnel metrics, and refuses anything else.

There is no language model in it. The [raw-vs-governed eval](../semantic_eval/README.md) showed where an AI
analyst goes wrong: it picks its own definition of trial-to-paid or CAC and returns a confident number. This
panel removes that choice. A question can only resolve to one of six MetricFlow metrics, and the value comes
from a table queried through MetricFlow, so a definition or a number can't be invented.

| Metric | Example phrases | Split by channel through |
|---|---|---|
| `signups` | signups, new accounts, trials | `account__channel` |
| `activation_rate` | activation, activated | `account__channel` |
| `free_to_paid_60d` | free to paid, trial to paid, conversion rate | `account__channel` |
| `paid_conversions` | paid conversions, new customers | `channel_day__marketing_channel` |
| `ad_spend` | ad spend, spend, budget | `channel_day__marketing_channel` |
| `cac` | CAC, cost to acquire, spend per paid conversion | `channel_day__marketing_channel` |

## How a question is answered

1. `answers.py` queries each metric through MetricFlow by month and by year, for all channels and for each
   channel, and writes `reporting.funnel_answers` (1,596 values on the warehouse as of 2026-11-10). A period is
   marked not final until it has ended and, for the 60-day outcomes, 60 more days have passed.
2. `vocab.py` lists the phrases for each metric, the six channels and their aliases, "by channel", and month
   names; they go to `reporting.funnel_vocab` (101 phrases).
3. `route.sql` lowercases the question, matches phrases as whole words (the longest match wins, so "spend per
   paid conversion" is CAC), reads a year if there is one, and looks the value up. No period means the latest
   final month; a month without a year means the latest such month. No metric phrase means a refusal; a
   period with no value means "no value", never a guess.

The site page runs `route.sql` in the browser (Evidence's DuckDB-WASM) against the two tables; a test keeps the
page's query identical to the file. The question is passed as a quoted SQL string, with quotes escaped.

## Run it

```bash
python scripts/run_all.py --fresh                                    # build the warehouse
python -m funnel_ask "What was CAC for Google Ads in March 2026?"     # CAC (google ads), Mar 2026: $791
python -m funnel_ask "Free to paid by channel in 2025"               # one line per channel
python -m funnel_ask "What is our churn rate?"                       # refused, exits 1
```

## Tests

- `tests/funnel_ask/test_route.py` (no warehouse): 17 cases on a hand-made table: routing of channel, month,
  year and "by channel" questions, longest phrase wins, refusals (including SQL in the question), a period with
  no value, quotes, and the page query matching `route.sql`.
- `tests/test_funnel_ask.py` (warehouse): every per-channel monthly CAC value equals MetricFlow's, every metric
  has month and year rows for all six channels, and the page's example questions are answered.

## Limits

It understands only the listed phrases, so a reworded question ("how much did each lead cost us?") is refused
rather than guessed. It answers one metric for one period; trends and comparisons are on the
[Acquisition funnel page](https://sky-five.github.io/ridgeline-analytics/acquisition/).
