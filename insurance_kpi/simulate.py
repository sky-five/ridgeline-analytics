"""A seeded, simulated personal-lines insurance book: auto and home, four provinces, broker and direct, one-year
policies starting 2023-01-01 to 2025-12-31, claims valued on 2026-06-30.

Two feeds, as a policy admin system and a claims system would export them:

- `policies`: policy_id, line, province, channel, start_date, end_date (start + 1 year), written_premium,
  commission_rate (broker 12%, direct 3% platform fee);
- `claims`: claim_id, policy_id, loss_date, reported_date, status (open or closed), paid, case_reserve. Only claims
  reported by the valuation date are in the export. Case reserves are the true remaining cost, so incurred
  (paid + case reserve) is the claim's full cost.

Planted business changes for the KPI tree to explain (accident year 2025 against 2024):

- auto severity +15% on losses from 2025-01-01 (repair and parts costs);
- auto rate +6% on policies starting from 2025-01-01;
- hail: home claim frequency in AB doubles for losses in 2025.

Planted data-quality faults, added to the feeds after the true book is made (`DQ_FAULTS`, counts below). Each one is
labelled in `Book.planted` so the profile can be scored, and undoing them gives back the true book exactly:

- duplicate_claim: a claim exported twice (same row);
- orphan_claim: a claim whose policy_id is in no policy export (a mis-keyed id);
- loss_outside_term: a claim on a real policy with a loss date after the policy ended;
- negative_paid: a closed claim's paid amount exported with the wrong sign;
- reported_before_loss: reported and loss dates swapped;
- missing_province: a policy with no province;
- zero_premium_test_policy: a test policy left in the export, premium 0, no claims.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 540
START_YEARS = [2023, 2024, 2025]
VALUATION = date(2026, 6, 30)

# line -> policies starting a year, base annual premium, claims per policy-year, mean claim cost, lognormal sigma
LINES = {
    "auto": dict(policies=12000, premium=1650.0, frequency=0.075, severity=6800.0, sigma=0.9),
    "home": dict(policies=9000, premium=1450.0, frequency=0.055, severity=11500.0, sigma=1.0),
}
PROVINCES = {"ON": (0.40, 1.10), "AB": (0.20, 1.05), "BC": (0.25, 1.00), "QC": (0.15, 0.85)}  # share, rate factor
CHANNELS = {"broker": (0.65, 0.12), "direct": (0.35, 0.03)}  # share, commission rate
PREMIUM_TREND = 0.03  # a year, on policy start year
ADMIN_COST_PER_POLICY_YEAR = 95.0  # policy admin and servicing, earned with exposure
REPORT_LAG_DAYS = 12.0  # mean, exponential
SETTLE_DAYS = 120.0  # mean days from report to close, exponential

AUTO_SEVERITY = ("auto", date(2025, 1, 1), 1.15)  # line, losses from, factor
AUTO_RATE = ("auto", date(2025, 1, 1), 1.06)  # line, policies starting from, factor
HAIL = ("home", "AB", 2025, 2.0)  # line, province, loss year, frequency factor

DQ_FAULTS = {
    "duplicate_claim": 40,
    "orphan_claim": 15,
    "loss_outside_term": 20,
    "negative_paid": 12,
    "reported_before_loss": 10,
    "missing_province": 30,
    "zero_premium_test_policy": 8,
}


@dataclass
class Book:
    policies: pd.DataFrame  # as exported, with the faults
    claims: pd.DataFrame
    true_policies: pd.DataFrame  # the book before the faults were added
    true_claims: pd.DataFrame
    planted: pd.DataFrame = field(default_factory=pd.DataFrame)  # fault, table, key, row (row number in the export)


def _pick(rng, options: dict, n: int) -> np.ndarray:
    keys = list(options)
    return rng.choice(keys, size=n, p=[options[k][0] for k in keys])


def true_book(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    pol_rows, claim_rows = [], []
    for line, p in LINES.items():
        for year in START_YEARS:
            n = p["policies"]
            provinces, channels = _pick(rng, PROVINCES, n), _pick(rng, CHANNELS, n)
            starts = [date(year, 1, 1) + timedelta(days=int(d)) for d in rng.integers(0, 365, n)]
            noise = rng.lognormal(0.0, 0.25, n)
            for i in range(n):
                start = starts[i]
                rate = p["premium"] * PROVINCES[provinces[i]][1] * (1 + PREMIUM_TREND) ** (year - 2023) * noise[i]
                if line == AUTO_RATE[0] and start >= AUTO_RATE[1]:
                    rate *= AUTO_RATE[2]
                pol_rows.append((line, provinces[i], channels[i], start, date(start.year + 1, start.month, start.day)
                                 if not (start.month == 2 and start.day == 29) else date(start.year + 1, 3, 1),
                                 round(rate, 2), CHANNELS[channels[i]][1]))
    policies = pd.DataFrame(pol_rows, columns=["line", "province", "channel", "start_date", "end_date",
                                               "written_premium", "commission_rate"])
    policies = policies.sort_values(["start_date", "line", "province"], kind="stable").reset_index(drop=True)
    policies.insert(0, "policy_id", [f"P{i:06d}" for i in range(1, len(policies) + 1)])

    for pol in policies.itertuples():
        p = LINES[pol.line]
        # one piece of the term per calendar year, so year-based changes apply to the loss date
        piece_start = pol.start_date
        while piece_start < pol.end_date:
            piece_end = min(pol.end_date, date(piece_start.year + 1, 1, 1))
            days = (piece_end - piece_start).days
            freq = p["frequency"]
            if (pol.line, pol.province, piece_start.year) == HAIL[:3]:
                freq *= HAIL[3]
            for _ in range(rng.poisson(freq * days / 365.0)):
                loss = piece_start + timedelta(days=int(rng.integers(0, days)))
                reported = loss + timedelta(days=int(rng.exponential(REPORT_LAG_DAYS)))
                mu = np.log(p["severity"]) - p["sigma"] ** 2 / 2
                cost = rng.lognormal(mu, p["sigma"])
                if pol.line == AUTO_SEVERITY[0] and loss >= AUTO_SEVERITY[1]:
                    cost *= AUTO_SEVERITY[2]
                closed = reported + timedelta(days=int(rng.exponential(SETTLE_DAYS)))
                if reported > VALUATION:
                    continue
                cost = round(cost, 2)
                if closed <= VALUATION:
                    claim_rows.append((pol.policy_id, loss, reported, "closed", cost, 0.0))
                else:
                    paid = round(cost * float(rng.uniform(0.0, 0.5)), 2)
                    claim_rows.append((pol.policy_id, loss, reported, "open", paid, round(cost - paid, 2)))
            piece_start = piece_end
    claims = pd.DataFrame(claim_rows, columns=["policy_id", "loss_date", "reported_date", "status", "paid",
                                               "case_reserve"])
    claims = claims.sort_values(["reported_date", "policy_id"], kind="stable").reset_index(drop=True)
    claims.insert(0, "claim_id", [f"C{i:06d}" for i in range(1, len(claims) + 1)])
    return policies, claims


def plant_faults(rng: np.random.Generator, policies: pd.DataFrame, claims: pd.DataFrame):
    pol, clm = policies.copy(), claims.copy()
    planted = []  # (fault, table, key)
    n_claims = len(clm)

    # changes to existing rows; each fault takes rows no other fault touches
    taken: set[int] = set()

    def sample(pool: np.ndarray, k: int) -> np.ndarray:
        pool = np.array([i for i in pool if i not in taken])
        out = np.sort(rng.choice(pool, size=k, replace=False))
        taken.update(out.tolist())
        return out

    closed = np.flatnonzero(clm["status"].to_numpy() == "closed")
    for i in sample(closed, DQ_FAULTS["negative_paid"]):
        clm.loc[i, "paid"] = -clm.loc[i, "paid"]
        planted.append(("negative_paid", "claims", clm.loc[i, "claim_id"]))
    lagged = np.flatnonzero((clm["reported_date"] > clm["loss_date"]).to_numpy())
    for i in sample(lagged, DQ_FAULTS["reported_before_loss"]):
        clm.loc[i, ["loss_date", "reported_date"]] = [clm.loc[i, "reported_date"], clm.loc[i, "loss_date"]]
        planted.append(("reported_before_loss", "claims", clm.loc[i, "claim_id"]))
    for i in np.sort(rng.choice(len(pol), size=DQ_FAULTS["missing_province"], replace=False)):
        pol.loc[i, "province"] = None
        planted.append(("missing_province", "policies", pol.loc[i, "policy_id"]))

    # added rows
    dups = clm.loc[sample(np.arange(n_claims), DQ_FAULTS["duplicate_claim"])]
    planted += [("duplicate_claim", "claims", c) for c in dups["claim_id"]]

    next_id = n_claims + 1
    extra = []
    template = clm.loc[rng.choice(n_claims, size=DQ_FAULTS["orphan_claim"], replace=False)].copy()
    for k, (_, r) in enumerate(template.iterrows()):
        r = r.copy()
        r["claim_id"], r["policy_id"] = f"C{next_id + k:06d}", f"P9{int(r['policy_id'][1:]):05d}"
        extra.append(r)
        planted.append(("orphan_claim", "claims", r["claim_id"]))
    next_id += DQ_FAULTS["orphan_claim"]
    expired = pol[pol["end_date"] < VALUATION - timedelta(days=60)]
    for k, (_, p) in enumerate(expired.sample(DQ_FAULTS["loss_outside_term"], random_state=rng).iterrows()):
        loss = p["end_date"] + timedelta(days=int(rng.integers(5, 50)))
        cost = round(float(rng.lognormal(np.log(LINES[p["line"]]["severity"]) - 0.4, 0.9)), 2)
        extra.append(pd.Series({"claim_id": f"C{next_id + k:06d}", "policy_id": p["policy_id"], "loss_date": loss,
                                "reported_date": loss + timedelta(days=3), "status": "closed", "paid": cost,
                                "case_reserve": 0.0}))
        planted.append(("loss_outside_term", "claims", f"C{next_id + k:06d}"))
    clm = pd.concat([clm, dups, pd.DataFrame(extra)], ignore_index=True)

    tests = pol.sample(DQ_FAULTS["zero_premium_test_policy"], random_state=rng).copy()
    tests["policy_id"] = [f"T{i:06d}" for i in range(1, len(tests) + 1)]
    tests["written_premium"] = 0.0
    planted += [("zero_premium_test_policy", "policies", t) for t in tests["policy_id"]]
    pol = pd.concat([pol, tests], ignore_index=True)

    # the export comes out in no useful order
    pol = pol.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    clm = clm.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    return pol, clm, pd.DataFrame(planted, columns=["fault", "table_name", "key"])


def simulate(seed: int = SEED) -> Book:
    rng = np.random.default_rng(seed)
    policies, claims = true_book(rng)
    pol, clm, planted = plant_faults(rng, policies, claims)
    return Book(pol, clm, policies, claims, planted)
