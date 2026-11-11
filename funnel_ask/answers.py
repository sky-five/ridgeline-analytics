"""The tables behind the panel, all queried through MetricFlow (dbt/models/semantic/).

funnel_answers holds every value the panel can show: each funnel metric by month and by year, for all channels
together and for each channel. Nothing in it is computed outside the semantic layer, so an answer can only
be a governed number. funnel_vocab holds the phrases from vocab.py.
"""
from datetime import date, timedelta

import pandas as pd

from funnel_ask.vocab import METRICS, vocab_rows


def _shown(fmt: str, v: float | None) -> str | None:
    if v is None or pd.isna(v):
        return None
    if fmt == "usd":
        return f"${v:,.0f}"
    if fmt == "pct":
        return f"{100 * v:.1f}%"
    return f"{v:,.0f}"


def _period_end(start: date, grain: str) -> date:
    if grain == "year":
        return date(start.year, 12, 31)
    nxt = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def answers_table(as_of: date) -> pd.DataFrame:
    """One row per (metric, grain, period, channel). `complete` is false for a period that has not ended, or
    whose 60-day outcomes are not all known yet on as_of."""
    from semantic import list_metrics, query

    info = {m.name: m for m in list_metrics()}
    rows = []
    for m in METRICS:
        for grain in ("month", "year"):
            time = f"metric_time__{grain}"
            for dims in ([time], [time, m.channel_dim]):
                df = query([m.name], dims)
                channel = df[m.channel_dim] if len(dims) == 2 else ["all"] * len(df)
                for start, ch, v in zip(df[time], channel, df[m.name], strict=True):
                    start = pd.Timestamp(start).date()
                    if start > as_of:
                        continue
                    value = None if v is None or pd.isna(v) else float(v)
                    end = _period_end(start, grain)
                    rows.append({
                        "metric": m.name, "label": info[m.name].label, "description": info[m.name].description,
                        "grain": grain, "period": start, "month_num": f"{start.month:02d}",
                        "year": str(start.year),
                        "period_label": start.strftime("%b %Y") if grain == "month" else str(start.year),
                        "channel": ch, "value": value, "value_shown": _shown(m.fmt, value),
                        "complete": end + timedelta(days=m.mature_days) <= as_of,
                        "mf_query": f"mf query --metrics {m.name} --group-by {','.join(dims)}",
                    })
    return pd.DataFrame(rows)


def vocab_table(answers: pd.DataFrame) -> pd.DataFrame:
    channels = sorted(c for c in answers["channel"].unique() if c != "all")
    return pd.DataFrame(vocab_rows(channels))
