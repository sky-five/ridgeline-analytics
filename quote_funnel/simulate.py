"""Seeded synthetic data for an insurance quote-comparison site.

A shopper opens a session, fills in one risk (auto or home, standard or non-standard), and the site asks each
carrier on its panel for a price. The shopper may edit the form and resubmit (a re-quote), may click through to
one carrier, and the carrier reports back when a policy is bound.

  source.carriers         6 carriers on the panel, which segments each one quotes, commission per bind
  source.sessions         one row per shopping session: week, line, tier, device
  source.quote_requests   one row per logged form submit (see the tracking change below)
  source.carrier_quotes   one row per price a carrier returned for a session
  source.clicks           the carrier a shopper clicked through to, if any
  source.binds            policies the carriers reported as bound

The tracking change: from TRACKING_CHANGE the site logs every submit as its own quote request, where before
it kept only the first submit of a session (edits overwrote it). Nothing about shoppers or carriers changes
that day. The simulator's true bind propensity is flat across the half.

Every random draw a shopper makes is fixed per session and per carrier up front, so the same shoppers can be
replayed with a candidate carrier added to the panel (`simulate(..., carriers=PANEL + [CANDIDATE])`). That
replay is the truth the new-carrier sizing is checked against; the sizing itself never reads it.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

START = date(2026, 1, 5)  # a Monday
WEEKS = 26
TRACKING_CHANGE = date(2026, 4, 6)  # week 14: every submit logged as its own request
SEGMENTS = ("auto_standard", "auto_non_standard", "home_standard", "home_non_standard")
SEGMENT_MIX = (0.53, 0.17, 0.25, 0.05)
BASE_PREMIUM = {"auto_standard": 1600.0, "auto_non_standard": 2900.0,
                "home_standard": 1300.0, "home_non_standard": 2200.0}
SESSIONS_PER_WEEK = 1500  # mean; each week's count is Poisson
REQUOTE_MEAN = 0.45  # extra submits per session (Poisson)


@dataclass(frozen=True)
class Carrier:
    carrier_id: str
    appetite: dict[str, float]  # segment -> chance a quote comes back
    relativity: dict[str, float]  # segment -> price level vs the market base
    brand: float  # pull on the shopper's choice beyond price
    commission: float  # paid to the site per bind


PANEL = [
    Carrier("carrier_a", {"auto_standard": .92, "home_standard": .90}, {"auto_standard": 1.00, "home_standard": 1.02},
            .30, 95.0),
    Carrier("carrier_b", {"auto_standard": .88, "auto_non_standard": .35, "home_standard": .85},
            {"auto_standard": 1.04, "auto_non_standard": 1.18, "home_standard": .97}, .20, 90.0),
    Carrier("carrier_c", {"auto_standard": .85, "home_standard": .80, "home_non_standard": .60},
            {"auto_standard": .97, "home_standard": 1.05, "home_non_standard": 1.10}, .00, 85.0),
    Carrier("carrier_d", {"auto_standard": .80, "home_standard": .75},
            {"auto_standard": 1.08, "home_standard": 1.00}, .10, 80.0),
    Carrier("carrier_e", {"auto_non_standard": .82, "home_non_standard": .70},
            {"auto_non_standard": 1.12, "home_non_standard": 1.06}, -.10, 110.0),
    Carrier("carrier_f", {"auto_standard": .70, "auto_non_standard": .55},
            {"auto_standard": 1.10, "auto_non_standard": 1.20}, -.20, 100.0),
]
# A carrier asking to join the panel: quotes all auto, priced keenly in non-standard auto.
CANDIDATE = Carrier("carrier_new", {"auto_standard": .75, "auto_non_standard": .85},
                    {"auto_standard": 1.03, "auto_non_standard": .97}, .00, 100.0)
CARRIER_SLOTS = [c.carrier_id for c in PANEL + [CANDIDATE]]  # fixed draw columns, panel or not


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def draws(seed: int = 7) -> dict:
    """Everything random about shoppers and carriers, fixed before any panel is chosen."""
    rng = np.random.default_rng(seed)
    per_week = rng.poisson(SESSIONS_PER_WEEK, WEEKS)
    n = int(per_week.sum())
    k = len(CARRIER_SLOTS)
    seg = rng.choice(len(SEGMENTS), n, p=SEGMENT_MIX)
    return {
        "n": n,
        "week": np.repeat(np.arange(WEEKS), per_week),
        "seg": seg,
        "segment": np.array(SEGMENTS)[seg],
        "device": rng.choice(["mobile", "desktop"], n, p=[0.64, 0.36]),
        "risk": np.exp(rng.normal(0, 0.22, n)),  # this shopper vs the segment base; the site never sees it
        "submits": 1 + rng.poisson(REQUOTE_MEAN, n),
        "u_quote": rng.random((n, k)),  # does carrier j return a price
        "price_noise": np.exp(rng.normal(0, 0.12, (n, k))),
        "gumbel": rng.gumbel(0, 1, (n, k)),  # taste for carrier j
        "u_click": rng.random(n),
        "u_bind": rng.random(n),
        "minute": rng.integers(0, 7 * 24 * 60, n),
    }


def simulate(d: dict | None = None, carriers: list[Carrier] | None = None) -> dict[str, pd.DataFrame]:
    """Run the shoppers in `d` against a panel. Same draws + same panel = same tables."""
    d = d or draws()
    carriers = carriers or PANEL
    n = d["n"]
    cols = [CARRIER_SLOTS.index(c.carrier_id) for c in carriers]
    base = np.array([BASE_PREMIUM[s] for s in d["segment"]]) * d["risk"]

    appetite = np.array([[c.appetite.get(s, 0.0) for c in carriers] for s in SEGMENTS])
    relativity = np.array([[c.relativity.get(s, 1.0) for c in carriers] for s in SEGMENTS])
    seg_idx = d["seg"]
    quoted = d["u_quote"][:, cols] < appetite[seg_idx]
    premium = np.round(base[:, None] * relativity[seg_idx] * d["price_noise"][:, cols], -1)
    premium = np.where(quoted, premium, np.nan)

    n_quotes = quoted.sum(1)
    best = np.nanmin(np.where(quoted, premium, np.inf), axis=1)
    rel_best = np.log(np.where(n_quotes > 0, best, base) / base)
    p_click = _sigmoid(-1.10 + 0.30 * np.minimum(n_quotes, 4) - 4.0 * rel_best) * (n_quotes > 0)
    clicked = d["u_click"] < p_click

    brand = np.array([c.brand for c in carriers])
    utility = np.where(quoted, -8.0 * np.log(np.where(quoted, premium, 1) / base[:, None]) + brand
                       + d["gumbel"][:, cols], -np.inf)
    choice = utility.argmax(1)
    chosen_premium = premium[np.arange(n), choice]
    p_bind = _sigmoid(-1.55 - 5.0 * np.log(np.where(clicked, chosen_premium, base) / base))
    bound = clicked & (d["u_bind"] < p_bind)

    week_start = np.array([START + timedelta(weeks=int(w)) for w in d["week"]])
    session_id = np.array([f"S{i:06d}" for i in range(1, n + 1)])
    started = pd.to_datetime(week_start) + pd.to_timedelta(d["minute"], unit="m")
    line, tier = zip(*(s.split("_", 1) for s in d["segment"]), strict=True)
    sessions = pd.DataFrame({"session_id": session_id, "started_at": started, "line": line, "tier": tier,
                             "device": d["device"]})

    # Request log: before the tracking change only the first submit of a session is kept.
    logged = np.where(started.date >= TRACKING_CHANGE, d["submits"], 1)
    rep = np.repeat(np.arange(n), logged)
    nth = np.concatenate([np.arange(m) for m in logged])
    quote_requests = pd.DataFrame({
        "request_id": [f"Q{i:07d}" for i in range(1, len(rep) + 1)],
        "session_id": session_id[rep],
        "submitted_at": started[rep] + pd.to_timedelta(nth * 3, unit="m"),
        "submit_number": nth + 1,
    })

    ids = np.array([c.carrier_id for c in carriers])
    qi, qj = np.nonzero(quoted)
    carrier_quotes = pd.DataFrame({"session_id": session_id[qi], "carrier_id": ids[qj],
                                   "premium": premium[qi, qj]})
    ci = np.nonzero(clicked)[0]
    clicks = pd.DataFrame({"session_id": session_id[ci], "carrier_id": ids[choice[ci]],
                           "clicked_at": started[ci] + pd.to_timedelta(logged[ci] * 3 + 2, unit="m")})
    bi = np.nonzero(bound)[0]
    binds = pd.DataFrame({"session_id": session_id[bi], "carrier_id": ids[choice[bi]],
                          "bound_on": (started[bi] + pd.Timedelta(days=2)).date,
                          "annual_premium": chosen_premium[bi]})
    carrier_table = pd.DataFrame([{"carrier_id": c.carrier_id, "commission_per_bind": c.commission,
                                   "segments_quoted": ",".join(sorted(c.appetite))} for c in carriers])
    return {"carriers": carrier_table, "sessions": sessions, "quote_requests": quote_requests,
            "carrier_quotes": carrier_quotes, "clicks": clicks, "binds": binds}


def load(con: duckdb.DuckDBPyConnection, data: dict[str, pd.DataFrame], schema: str = "source") -> None:
    con.execute(f"create schema if not exists {schema}")
    for name, df in data.items():
        con.register("_df", df)
        con.execute(f"create or replace table {schema}.{name} as select * from _df")
        con.unregister("_df")
