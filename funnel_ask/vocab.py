"""The words the panel understands, and the governed metric each one points to.

A question is answered only when one of these phrases names a funnel metric; everything else is refused.
Phrases are matched as whole words after lowercasing and replacing punctuation with spaces, and the longest
matching phrase wins ("spend per paid conversion" is CAC, not spend).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FunnelMetric:
    name: str  # the governed metric in dbt/models/semantic/_metrics.yml
    fmt: str  # usd | pct | int
    channel_dim: str  # the MetricFlow dimension that splits it by acquisition channel
    mature_days: int  # days after month end before the month's value is final (60-day outcomes)
    phrases: tuple[str, ...]


METRICS = [
    FunnelMetric("signups", "int", "account__channel", 0, (
        "signups", "signup", "sign ups", "sign up", "signed up", "new accounts", "registrations", "trials",
        "trial starts", "trials started")),
    FunnelMetric("activation_rate", "pct", "account__channel", 14, (
        "activation rate", "activation", "activated", "activate", "proposal within 14 days")),
    FunnelMetric("free_to_paid_60d", "pct", "account__channel", 60, (
        "free to paid", "trial to paid", "conversion rate", "convert to paid", "converted to paid",
        "paid within 60 days", "paid rate", "trial conversion")),
    FunnelMetric("paid_conversions", "int", "channel_day__marketing_channel", 60, (
        "paid conversions", "paid conversion", "conversions", "new paying accounts", "new paying customers",
        "new customers")),
    FunnelMetric("ad_spend", "usd", "channel_day__marketing_channel", 0, (
        "ad spend", "spend", "spent", "spending", "marketing spend", "advertising", "budget")),
    FunnelMetric("cac", "usd", "channel_day__marketing_channel", 60, (
        "cac", "customer acquisition cost", "acquisition cost", "cost to acquire", "cost per customer",
        "cost per paid", "spend per paid conversion", "spend per conversion", "cost per conversion",
        "cost per paying account")),
]

BY_NAME = {m.name: m for m in METRICS}

# extra ways to name a channel; each channel's own name (underscores as spaces) is always understood
CHANNEL_ALIASES = {
    "google_ads": ("google", "adwords", "search ads"),
    "facebook": ("facebook ads", "meta", "meta ads", "fb"),
    "supplier_partner": ("supplier", "suppliers", "supplier partners", "partner", "partners"),
    "trade_show": ("trade shows", "tradeshow"),
    "organic": ("seo", "organic search", "unpaid"),
    "referral": ("referrals", "word of mouth"),
}

BREAKDOWN_PHRASES = ("by channel", "per channel", "each channel", "which channel", "channels", "every channel")

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


def normalize(text: str) -> str:
    """Lowercase words separated by single spaces, the same normalization the router SQL applies."""
    import re

    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def vocab_rows(channels: list[str]) -> list[dict]:
    """(kind, phrase, target) rows for the funnel_vocab table."""
    rows = [{"kind": "metric", "phrase": normalize(p), "target": m.name} for m in METRICS for p in m.phrases]
    for ch in channels:
        for p in (ch.replace("_", " "), *CHANNEL_ALIASES.get(ch, ())):
            rows.append({"kind": "channel", "phrase": normalize(p), "target": ch})
    rows += [{"kind": "breakdown", "phrase": normalize(p), "target": "channel"} for p in BREAKDOWN_PHRASES]
    for i, name in enumerate(MONTHS, start=1):
        for p in (name, name[:3], *(("sept",) if i == 9 else ())):
            rows.append({"kind": "month", "phrase": p, "target": f"{i:02d}"})
    seen, out = set(), []
    for r in rows:  # a phrase that collides keeps its first meaning
        if (r["kind"], r["phrase"]) not in seen:
            seen.add((r["kind"], r["phrase"]))
            out.append(r)
    return out
