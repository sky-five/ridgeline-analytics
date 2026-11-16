"""A seeded, simulated home and auto insurance book across eight provinces, 2022-01 to 2026-06.

Policies are written through three channels (broker, direct, digital) and renew every 12 months. At each renewal
the premium moves by that renewal's rate change and the customer stays or leaves; staying is less likely the
bigger the increase. Claims arrive per policy-month (auto more often in winter) and are reported with a lag, so
claims from the last weeks before the as-of date are mostly not in the claims feed yet.

The book is run from 2020-01, starting from an opening book about as big as each segment's new business and
retention would settle at, so the policies in force at 2022-01 are a settled mix of new and long-held policies.
The feeds keep only terms still running on or after 2022-01-01.

Planted for the model and the dashboard to find:

- a hailstorm in Alberta on 2024-07-22 gives 4% of Alberta home policies a large claim;
- Alberta home renewals from 2025-01 take a 10% rate increase after it (others about 4%);
- Ontario auto renewals from 2025-04 take a 14% rate increase, so Ontario auto retention drops;
- digital customers renew less often than broker customers; customers in their third term or later more often;
- Alberta grows fastest, Quebec is flat.

Claims that happened by the as-of date but are reported after it are kept in `late_claims`, out of the feed, so
the dashboard can say how far the last months' loss ratio is understated.
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

SEED = 519
BURN_IN = pd.Period("2020-01", "M")  # the book starts here
FIRST_MONTH, LAST_MONTH = pd.Period("2022-01", "M"), pd.Period("2026-06", "M")  # what the feeds cover
AS_OF = date(2026, 6, 30)

# province -> (new policies a month in 2020-01, monthly growth of new business, premium factor home, auto)
PROVINCES = {
    "ON": (62, 0.004, 1.00, 1.45),
    "QC": (40, 0.000, 0.90, 0.80),
    "BC": (26, 0.006, 1.05, 1.10),
    "AB": (22, 0.012, 1.15, 1.20),
    "MB": (7, 0.002, 0.95, 0.90),
    "SK": (6, 0.002, 0.95, 0.90),
    "NS": (6, 0.005, 0.90, 0.95),
    "NB": (4, 0.003, 0.85, 0.90),
}
# product -> (share of new business, mean premium in 2020, claims per policy-month, mean claim)
PRODUCTS = {"home": (0.45, 1_450, 0.0075, 10_500), "auto": (0.55, 1_650, 0.0090, 9_000)}
# channel -> (share of new business, base chance of renewing)
CHANNELS = {"broker": (0.55, 0.88), "direct": (0.30, 0.85), "digital": (0.15, 0.77)}
PRODUCT_RETENTION = {"home": 0.02, "auto": -0.01}
LOYALTY_TERM, LOYALTY_BONUS = 3, 0.03  # from the third term on, a customer is this much more likely to stay
NORMAL_RATE_CHANGE, ELASTICITY = 0.04, 1.0  # each point of increase above 4% costs a point of retention
PREMIUM_TREND = 0.04  # yearly, on new business premiums and on the cost of a claim
WINTER_AUTO = 1.5  # auto claims per policy-month in December to February, times the base

HAIL_DATE, HAIL_PROVINCE, HAIL_SHARE, HAIL_MEAN = date(2024, 7, 22), "AB", 0.04, 22_000
RATE_ACTIONS = [  # (province, product, renewals from, rate change)
    ("AB", "home", date(2025, 1, 1), 0.10),
    ("ON", "auto", date(2025, 4, 1), 0.14),
]
REPORT_LAG_DAYS = 25  # mean days from loss to report; hail claims take longer
HAIL_REPORT_LAG_DAYS = 40


@dataclass
class Book:
    policies: pd.DataFrame  # one row per policy: province, product, channel
    terms: pd.DataFrame  # one row per 12-month term: written premium, its rate change, the change offered at its end
    claims: pd.DataFrame  # the claims feed: losses reported on or before AS_OF
    late_claims: pd.DataFrame  # losses on or before AS_OF reported after it (kept out of the feed)


def rate_change(province: str, product: str, on: date, noise: float) -> float:
    for p, prod, start, change in RATE_ACTIONS:
        if province == p and product == prod and on >= start:
            return round(change + noise / 2, 4)
    return round(NORMAL_RATE_CHANGE + noise, 4)


def renew_chance(channel: str, product: str, next_term: int, change: float) -> float:
    p = CHANNELS[channel][1] + PRODUCT_RETENTION[product]
    p += LOYALTY_BONUS if next_term >= LOYALTY_TERM else 0.0
    p -= ELASTICITY * (change - NORMAL_RATE_CHANGE)
    return float(np.clip(p, 0.05, 0.98))


def _new_business(rng, month: pd.Period, start_id: int) -> list[dict]:
    t = month.ordinal - BURN_IN.ordinal
    rows = []
    for prov, (base, growth, f_home, f_auto) in PROVINCES.items():
        for prod, (p_share, premium, _, _) in PRODUCTS.items():
            factor = f_home if prod == "home" else f_auto
            for ch, (c_share, _) in CHANNELS.items():
                n = rng.poisson(base * (1 + growth) ** t * p_share * c_share)
                for _ in range(n):
                    start = month.start_time.date().replace(day=int(rng.integers(1, 29)))
                    prem = premium * factor * (1 + PREMIUM_TREND) ** (t / 12) * rng.lognormal(0, 0.25)
                    rows.append({"policy_id": f"P{start_id + len(rows):06d}", "province": prov, "product": prod,
                                 "channel": ch, "start_date": start, "premium": round(prem, 2)})
    return rows


def _opening_book(rng) -> list[dict]:
    """Policies in force at BURN_IN: per segment about a year of new business over one minus its settled
    renewal chance, with terms that started in the 12 months before and a mix of first and later terms."""
    rows = []
    for prov, (base, _, f_home, f_auto) in PROVINCES.items():
        for prod, (p_share, premium, _, _) in PRODUCTS.items():
            factor = f_home if prod == "home" else f_auto
            for ch, (c_share, _) in CHANNELS.items():
                stay = renew_chance(ch, prod, LOYALTY_TERM, NORMAL_RATE_CHANGE)
                for _ in range(rng.poisson(base * p_share * c_share * 12 / (1 - stay))):
                    month = BURN_IN - int(rng.integers(1, 13))
                    start = month.start_time.date().replace(day=int(rng.integers(1, 29)))
                    prem = premium * factor * rng.lognormal(0, 0.25) / (1 + PREMIUM_TREND)
                    rows.append({"policy_id": f"P{len(rows) + 1:06d}", "province": prov, "product": prod,
                                 "channel": ch, "start_date": start, "premium": round(prem, 2),
                                 "term_number": 1 + int(rng.geometric(1 - stay))})
    return rows


def _terms(rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    policies, terms = [], []
    due: dict[pd.Period, list[dict]] = {}  # month a term ends -> terms ending then
    offered: dict[str, float] = {}  # term_id -> rate change offered at its renewal, taken up or not
    for p in _opening_book(rng):
        policies.append({k: p[k] for k in ("policy_id", "province", "product", "channel")})
        term = {"policy_id": p["policy_id"], "term_number": p["term_number"], "start_date": p["start_date"],
                "written_premium": p["premium"], "rate_change": None}
        terms.append(term)
        due.setdefault(pd.Period(p["start_date"], "M") + 12, []).append(term | p)
    month = BURN_IN
    while month <= LAST_MONTH:
        for p in _new_business(rng, month, len(policies) + 1):
            policies.append({k: p[k] for k in ("policy_id", "province", "product", "channel")})
            term = {"policy_id": p["policy_id"], "term_number": 1, "start_date": p["start_date"],
                    "written_premium": p["premium"], "rate_change": None}
            terms.append(term)
            due.setdefault(month + 12, []).append(term | p)
        for old in due.pop(month, []):
            end = old["start_date"].replace(year=old["start_date"].year + 1)
            change = rate_change(old["province"], old["product"], end, rng.normal(0, 0.015))
            offered[f"{old['policy_id']}-{old['term_number']}"] = change
            nxt = old["term_number"] + 1
            if rng.random() < renew_chance(old["channel"], old["product"], nxt, change):
                term = {"policy_id": old["policy_id"], "term_number": nxt, "start_date": end,
                        "written_premium": round(old["written_premium"] * (1 + change), 2), "rate_change": change}
                terms.append(term)
                due.setdefault(month + 12, []).append(old | term)
        month += 1
    pol = pd.DataFrame(policies)
    t = pd.DataFrame(terms)
    t["end_date"] = [d.replace(year=d.year + 1) for d in t["start_date"]]
    t.insert(0, "term_id", t["policy_id"] + "-" + t["term_number"].astype(str))
    t["renewal_offer_change"] = t["term_id"].map(offered)
    t = t[["term_id", "policy_id", "term_number", "start_date", "end_date", "written_premium", "rate_change",
           "renewal_offer_change"]]
    return pol, t


def _claims(rng, pol: pd.DataFrame, terms: pd.DataFrame) -> pd.DataFrame:
    t = terms.merge(pol[["policy_id", "province", "product"]], on="policy_id")
    starts = pd.to_datetime(t["start_date"])
    # a claim costs more where premiums are higher, by the same province factor
    factor = np.array([PROVINCES[pr][2 if prod == "home" else 3]
                       for pr, prod in zip(t["province"], t["product"], strict=True)])
    frames = []
    for k in range(12):  # month k of each term
        lo = starts + pd.DateOffset(months=k)
        hi = starts + pd.DateOffset(months=k + 1)
        winter = lo.dt.month.isin([12, 1, 2]) & (t["product"] == "auto")
        freq = t["product"].map({p: v[2] for p, v in PRODUCTS.items()}) * np.where(winter, WINTER_AUTO, 1.0)
        n = rng.poisson(freq.to_numpy())
        idx = np.repeat(np.arange(len(t)), n)
        if not len(idx):
            continue
        span = (hi - lo).dt.days.to_numpy()[idx]
        loss = lo.to_numpy()[idx] + pd.to_timedelta(rng.integers(0, span), "D")
        mean = t["product"].map({p: v[3] for p, v in PRODUCTS.items()}).to_numpy()[idx] * factor[idx]
        mean = mean * (1 + PREMIUM_TREND) ** ((loss - pd.Timestamp(BURN_IN.start_time)).days / 365.25)
        frames.append(pd.DataFrame({"term_id": t["term_id"].to_numpy()[idx], "loss_date": loss,
                                    "amount": mean * rng.lognormal(-0.5, 1.0, len(idx)), "cause": "ordinary"}))
    hail = t[(t["province"] == HAIL_PROVINCE) & (t["product"] == "home")
             & (t["start_date"] <= HAIL_DATE) & (t["end_date"] > HAIL_DATE)]
    hit = hail[rng.random(len(hail)) < HAIL_SHARE]
    frames.append(pd.DataFrame({"term_id": hit["term_id"].to_numpy(), "loss_date": pd.Timestamp(HAIL_DATE),
                                "amount": HAIL_MEAN * rng.lognormal(-0.18, 0.6, len(hit)), "cause": "hail"}))
    c = pd.concat(frames, ignore_index=True)
    lag = np.where(c["cause"] == "hail", HAIL_REPORT_LAG_DAYS, REPORT_LAG_DAYS)
    c["reported_date"] = c["loss_date"] + pd.to_timedelta(np.ceil(rng.exponential(lag)), "D")
    c["loss_date"], c["reported_date"] = c["loss_date"].dt.date, c["reported_date"].dt.date
    c["amount"] = c["amount"].round(2)
    c = c.sort_values(["loss_date", "term_id"], kind="stable").reset_index(drop=True)
    c.insert(0, "claim_id", [f"C{i:07d}" for i in range(1, len(c) + 1)])
    c["policy_id"] = c["term_id"].str.split("-").str[0]
    return c[["claim_id", "policy_id", "term_id", "loss_date", "reported_date", "amount", "cause"]]


def simulate(seed: int = SEED) -> Book:
    rng = np.random.default_rng(seed)
    pol, terms = _terms(rng)
    claims = _claims(rng, pol, terms)
    first = FIRST_MONTH.start_time.date()
    terms = terms[terms["end_date"] > first].reset_index(drop=True)
    pol = pol[pol["policy_id"].isin(terms["policy_id"])].reset_index(drop=True)
    claims = claims[(claims["loss_date"] >= first) & (claims["loss_date"] <= AS_OF)
                    & claims["term_id"].isin(terms["term_id"])]
    late = claims["reported_date"] > AS_OF
    return Book(pol, terms, claims[~late].reset_index(drop=True), claims[late].reset_index(drop=True))
