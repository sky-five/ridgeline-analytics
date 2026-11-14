"""A seeded, simulated vehicle retail network: dealers, vehicle models, incentive programs, the sales they
made and the incentives applied to each sale, January 2025 to June 2026.

40 dealers in four regions sell twelve models in four segments (sedan, SUV, truck, electric). Each sale is
paid in cash, financed or leased. Five kinds of incentive program run on top of a dealer discount:

- cash_rebate: cash off the price on a segment for a set period
- apr_subvention: a below-market loan rate; the cost goes to the lender, not off the price
- lease_support: the same for leases
- loyalty: cash off for returning customers
- ev_bonus: cash off every electric vehicle

Two things are planted for the metrics to find: electric vehicles carry several times the incentive per
unit of any other segment, and the last ten days of every quarter run a quarter-end cash program that
lifts both units sold and incentive per unit.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 1808
FIRST_DAY = date(2025, 1, 1)
AS_OF = date(2026, 6, 30)
REGIONS = ["north", "south", "east", "west"]
DEALERS = 40
VEHICLES = {
    # vehicle_id: (segment, MSRP, share of sales)
    "sedan_compact": ("sedan", 24_500, 0.11),
    "sedan_midsize": ("sedan", 31_000, 0.10),
    "sedan_sport": ("sedan", 42_000, 0.03),
    "suv_compact": ("suv", 29_500, 0.16),
    "suv_midsize": ("suv", 39_000, 0.13),
    "suv_large": ("suv", 56_000, 0.06),
    "truck_midsize": ("truck", 37_500, 0.09),
    "truck_fullsize": ("truck", 49_000, 0.12),
    "truck_heavy": ("truck", 64_000, 0.04),
    "ev_compact": ("ev", 36_000, 0.07),
    "ev_suv": ("ev", 52_000, 0.06),
    "ev_truck": ("ev", 71_000, 0.03),
}
SALES_PER_DAY = 52
FINANCE = {"cash": 0.22, "finance": 0.52, "lease": 0.26}
DEALER_DISCOUNT = 0.035  # mean dealer discount off MSRP, before any program
LOYAL_SHARE = 0.30  # share of buyers who already own one of our vehicles
QUARTER_END_DAYS = 10
QUARTER_END_LIFT = 1.45  # sales per day in the last ten days of a quarter, as a multiple of normal

# program_id: (program_type, segment or "all", first day, last day, amount, who qualifies)
# amount is dollars per unit, except apr_subvention and lease_support, where it is a share of MSRP.
PROGRAMS = {
    "rebate_sedan_25h1": ("cash_rebate", "sedan", date(2025, 1, 1), date(2025, 6, 30), 1_000, "all"),
    "rebate_truck_25q3": ("cash_rebate", "truck", date(2025, 7, 1), date(2025, 9, 30), 2_000, "all"),
    "rebate_suv_26h1": ("cash_rebate", "suv", date(2026, 1, 1), date(2026, 6, 30), 1_250, "all"),
    "apr_suv_25": ("apr_subvention", "suv", date(2025, 1, 1), date(2025, 12, 31), 0.045, "finance"),
    "apr_truck_26": ("apr_subvention", "truck", date(2026, 1, 1), date(2026, 6, 30), 0.050, "finance"),
    "lease_sedan_all": ("lease_support", "sedan", date(2025, 1, 1), date(2026, 6, 30), 0.060, "lease"),
    "lease_ev_all": ("lease_support", "ev", date(2025, 1, 1), date(2026, 6, 30), 0.080, "lease"),
    "loyalty_all": ("loyalty", "all", date(2025, 1, 1), date(2026, 6, 30), 750, "loyal"),
    "ev_bonus_all": ("ev_bonus", "ev", date(2025, 1, 1), date(2026, 6, 30), 5_000, "all"),
}
QUARTER_END_CASH = 1_500  # per unit, every segment, last ten days of each quarter
CASH_TYPES = ("cash_rebate", "loyalty", "ev_bonus", "quarter_end_cash")  # paid off the price


@dataclass
class Network:
    dealers: pd.DataFrame
    vehicles: pd.DataFrame
    programs: pd.DataFrame
    sales: pd.DataFrame
    incentives: pd.DataFrame


def quarter_ends(first: date = FIRST_DAY, last: date = AS_OF) -> list[tuple[date, date]]:
    out = []
    for year in range(first.year, last.year + 1):
        for month in (3, 6, 9, 12):
            end = (date(year, month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            start = end - timedelta(days=QUARTER_END_DAYS - 1)
            if start >= first and end <= last:
                out.append((start, end))
    return out


def is_quarter_end(d: date) -> bool:
    return any(a <= d <= b for a, b in quarter_ends())


def _programs() -> pd.DataFrame:
    rows = [(pid, t, seg, a, b, amt, who) for pid, (t, seg, a, b, amt, who) in PROGRAMS.items()]
    rows += [(f"quarter_end_{b:%Y%m}", "quarter_end_cash", "all", a, b, QUARTER_END_CASH, "all")
             for a, b in quarter_ends()]
    df = pd.DataFrame(rows, columns=["program_id", "program_type", "segment", "start_date", "end_date",
                                     "amount", "eligibility"])
    for c in ("start_date", "end_date"):
        df[c] = pd.to_datetime(df[c])
    return df


def _amount(program, msrp: float) -> float:
    if program.program_type in ("apr_subvention", "lease_support"):
        return round(program.amount * msrp, 2)
    return float(program.amount)


def simulate(seed: int = SEED) -> Network:
    rng = np.random.default_rng(seed)
    dealers = pd.DataFrame({
        "dealer_id": [f"D{i:03d}" for i in range(1, DEALERS + 1)],
        "region": [REGIONS[i % len(REGIONS)] for i in range(DEALERS)],
    })
    size = rng.lognormal(0, 0.4, DEALERS)
    dealer_p = size / size.sum()
    vehicles = pd.DataFrame(
        [(vid, seg, msrp) for vid, (seg, msrp, _) in VEHICLES.items()],
        columns=["vehicle_id", "segment", "msrp"],
    )
    vehicle_p = np.array([v[2] for v in VEHICLES.values()])
    vehicle_p = vehicle_p / vehicle_p.sum()
    programs = _programs()

    plist = list(programs.itertuples(index=False))
    dealer_ids, vehicle_ids = dealers["dealer_id"].to_numpy(), vehicles["vehicle_id"].to_numpy()
    sales, applied = [], []
    day = FIRST_DAY
    while day <= AS_OF:
        ts = pd.Timestamp(day)
        live = [p for p in plist if p.start_date <= ts <= p.end_date]
        n = rng.poisson(SALES_PER_DAY * (QUARTER_END_LIFT if is_quarter_end(day) else 1.0))
        vids = rng.choice(vehicle_ids, n, p=vehicle_p)
        finances = rng.choice(list(FINANCE), n, p=list(FINANCE.values()))
        loyals = rng.random(n) < LOYAL_SHARE
        dealer_draw = rng.choice(dealer_ids, n, p=dealer_p)
        discounts = np.maximum(0.0, rng.normal(DEALER_DISCOUNT, 0.015, n))
        for vid, finance, loyal, dealer, disc in zip(vids, finances, loyals, dealer_draw, discounts, strict=True):
            segment, msrp, _ = VEHICLES[vid]
            sale_id = f"S{len(sales) + 1:06d}"
            cash_off = 0.0
            for prog in live:
                if prog.segment not in ("all", segment):
                    continue
                if prog.eligibility in ("finance", "lease") and prog.eligibility != finance:
                    continue
                if prog.eligibility == "loyal" and not loyal:
                    continue
                amount = _amount(prog, msrp)
                applied.append((sale_id, prog.program_id, amount))
                if prog.program_type in CASH_TYPES:
                    cash_off += amount
            discount = round(msrp * float(disc), 2)
            sales.append((sale_id, day, str(dealer), str(vid), str(finance), bool(loyal), float(msrp), discount,
                          round(msrp - discount - cash_off, 2)))
        day += timedelta(days=1)

    sales = pd.DataFrame(sales, columns=["sale_id", "sale_date", "dealer_id", "vehicle_id", "finance_type",
                                         "is_returning_customer", "msrp", "dealer_discount", "transaction_price"])
    sales["sale_date"] = pd.to_datetime(sales["sale_date"])
    incentives = pd.DataFrame(applied, columns=["sale_id", "program_id", "amount"])
    incentives.insert(0, "application_id", [f"A{i:07d}" for i in range(1, len(incentives) + 1)])
    return Network(dealers=dealers, vehicles=vehicles, programs=programs, sales=sales, incentives=incentives)
