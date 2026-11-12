"""A seeded, simulated wholesale vehicle auction: 26 weekly sales, January to June 2026.

Dealers consign used vehicles. Each vehicle runs in one channel (physical lane, lane with online
simulcast, or a timed online-only sale) against a seller's reserve. Bidding is an English auction:
each bidder has a private valuation and the high bid lands one increment above the second-highest
valuation. A run ends one of four ways:

- sold on the block: the high bid meets the reserve;
- if-sale accepted: the high bid is within 10% under the reserve and the seller takes it afterwards;
- no-sale: anything else (the seller may relist it next week with a lower reserve);
- withdrawn: pulled before it ran (no bids).

From week 14 (2026-04-06) a reserve-price test runs. Vehicles first consigned in the test window are
split 50/50 by a hash of the vehicle id. Control keeps the usual reserve guidance (100% of book value);
treatment gets 95% of book value. Bids never depend on the reserve, so the outcome of each first run
under the other arm is known exactly. That counterfactual is the planted truth: it is kept in
`Auction.truth` and never loaded into the warehouse.
"""
import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 2026
FIRST_SALE = date(2026, 1, 5)
WEEKS = 26
TEST_START = date(2026, 4, 6)  # week 14
CHANNELS = {
    # share of consignments, mean bidders per run, valuation spread around book
    "in_lane": (0.40, 4.2, 0.07),
    "simulcast": (0.35, 5.6, 0.08),
    "online_timed": (0.25, 3.0, 0.10),
}
RESERVE_GUIDANCE = {"control": 1.00, "treatment": 0.95}
RESERVE_SPREAD = 0.05  # sellers drift around the guidance
RELIST_RESERVE_STEP = 0.03  # each relist takes 3% off the reserve
RELIST_CHANCE = 0.6
MAX_RUNS = 3
IF_SALE_WINDOW = 0.10
IF_SALE_ACCEPT = 0.45
WITHDRAW_CHANCE = 0.04
INCREMENT = 100
MAKES = ["compact", "midsize sedan", "small suv", "midsize suv", "pickup", "minivan"]
BOOK_BY_SEGMENT = {
    "compact": 14_000, "midsize sedan": 18_000, "small suv": 21_000,
    "midsize suv": 27_000, "pickup": 32_000, "minivan": 23_000,
}


@dataclass
class Auction:
    vehicles: pd.DataFrame
    listings: pd.DataFrame
    bids: pd.DataFrame
    truth: pd.DataFrame  # one row per test vehicle: first-run outcome under each arm (never loaded)


def arm_for(vehicle_id: str) -> str:
    """50/50 split by a hash of the vehicle id, so the arm never depends on anything about the car."""
    h = int(hashlib.sha256(vehicle_id.encode()).hexdigest()[:8], 16)
    return "treatment" if h % 2 else "control"


def _high_bid(valuations: np.ndarray, book: float) -> float | None:
    """English auction: one increment over the second-highest valuation, capped at the highest.
    A lone bidder opens at the lower of their valuation and 80% of book. The reserve is never an
    input, which is what makes the other arm's outcome knowable."""
    if len(valuations) == 0:
        return None
    top = valuations.max()
    if len(valuations) == 1:
        bid = min(top, 0.8 * book)
    else:
        bid = min(top, np.sort(valuations)[-2] + INCREMENT)
    return float(np.floor(bid / INCREMENT) * INCREMENT)


def _outcome(high_bid: float | None, reserve: float, accept_draw: float) -> str:
    if high_bid is None:
        return "no_sale"
    if high_bid >= reserve:
        return "sold"
    if high_bid >= (1 - IF_SALE_WINDOW) * reserve and accept_draw < IF_SALE_ACCEPT:
        return "if_sale"
    return "no_sale"


def simulate(seed: int = SEED) -> Auction:
    rng = np.random.default_rng(seed)
    vehicles, listings, bids, truth = [], [], [], []
    channel_names = list(CHANNELS)
    channel_p = [CHANNELS[c][0] for c in channel_names]
    v_no = l_no = b_no = 0

    pending: list[tuple[dict, int, date]] = []  # relists waiting: (vehicle, run number, sale date)
    for week in range(WEEKS):
        sale_date = FIRST_SALE + timedelta(weeks=week)
        new = []
        for _ in range(rng.poisson(480)):
            v_no += 1
            segment = MAKES[rng.integers(len(MAKES))]
            year = int(rng.integers(2016, 2025))
            age = 2026 - year
            mileage = int(max(3_000, rng.normal(14_000 * age, 9_000)))
            grade = float(np.clip(np.round(rng.normal(3.4, 0.8), 1), 1.0, 5.0))
            book = BOOK_BY_SEGMENT[segment] * 0.88**age * (1 + 0.06 * (grade - 3.4)) * (1 - mileage / 1_500_000)
            book = round(book / INCREMENT) * INCREMENT
            v = {
                "vehicle_id": f"VEH-{v_no:06d}",
                "seller_id": f"SLR-{int(rng.integers(1, 321)):03d}",
                "segment": segment,
                "model_year": year,
                "mileage": mileage,
                "condition_grade": grade,
                "book_value_usd": float(book),
                "consigned_on": sale_date - timedelta(days=int(rng.integers(2, 9))),
                "channel": channel_names[rng.choice(len(channel_names), p=channel_p)],
                "reserve_z": float(rng.normal()),
                "in_test": sale_date >= TEST_START,
            }
            v["guidance"] = RESERVE_GUIDANCE[arm_for(v["vehicle_id"])] if v["in_test"] else 1.0
            vehicles.append(v)
            new.append((v, 1, sale_date))

        this_week, pending = pending + new, []
        for v, run, run_date in this_week:
            l_no += 1
            listing_id = f"LST-{l_no:07d}"
            _, mean_bidders, spread = CHANNELS[v["channel"]]
            reserve = v["book_value_usd"] * (v["guidance"] + RESERVE_SPREAD * v["reserve_z"])
            reserve *= (1 - RELIST_RESERVE_STEP) ** (run - 1)
            reserve = float(round(reserve / INCREMENT) * INCREMENT)
            withdrawn = rng.random() < WITHDRAW_CHANCE
            n = 0 if withdrawn else int(rng.poisson(mean_bidders * (0.8 + 0.1 * v["condition_grade"]) / 1.14))
            vals = v["book_value_usd"] * rng.lognormal(-0.02, spread, n)
            accept = float(rng.random())
            high = _high_bid(vals, v["book_value_usd"])
            status = "withdrawn" if withdrawn else _outcome(high, reserve, accept)
            listings.append({
                "listing_id": listing_id,
                "vehicle_id": v["vehicle_id"],
                "sale_date": run_date,
                "run_number": run,
                "channel": v["channel"],
                "reserve_usd": reserve,
                "status": status,
                "sold_price_usd": high if status in ("sold", "if_sale") else None,
            })
            if n:
                # each bidder's last bid: the winner's is the high bid, the rest stopped at their valuation
                last = np.minimum(np.floor(vals / INCREMENT) * INCREMENT, high)
                last[np.argmax(vals)] = high
                for amount in last:
                    b_no += 1
                    bids.append({
                        "bid_id": f"BID-{b_no:08d}",
                        "listing_id": listing_id,
                        "bidder_id": f"BYR-{int(rng.integers(1, 1201)):04d}",
                        "bid_usd": float(amount),
                        "is_online": v["channel"] != "in_lane" and (
                            v["channel"] == "online_timed" or rng.random() < 0.55),
                    })
            if run == 1 and v["in_test"]:
                other = "control" if arm_for(v["vehicle_id"]) == "treatment" else "treatment"
                other_reserve = v["book_value_usd"] * (RESERVE_GUIDANCE[other] + RESERVE_SPREAD * v["reserve_z"])
                other_reserve = float(round(other_reserve / INCREMENT) * INCREMENT)
                other_status = "withdrawn" if withdrawn else _outcome(high, other_reserve, accept)
                by_arm = {arm_for(v["vehicle_id"]): (status, high), other: (other_status, high)}
                truth.append({
                    "vehicle_id": v["vehicle_id"],
                    "arm": arm_for(v["vehicle_id"]),
                    "control_status": by_arm["control"][0],
                    "treatment_status": by_arm["treatment"][0],
                    "high_bid_usd": high,
                    "book_value_usd": v["book_value_usd"],
                })

            if status == "no_sale" and run < MAX_RUNS and rng.random() < RELIST_CHANCE and week + 1 < WEEKS:
                pending.append((v, run + 1, run_date + timedelta(weeks=1)))

    v_df = pd.DataFrame(vehicles)
    v_df["consigned_on"] = pd.to_datetime(v_df["consigned_on"])
    l_df = pd.DataFrame(listings)
    l_df["sale_date"] = pd.to_datetime(l_df["sale_date"])
    keep = ["vehicle_id", "seller_id", "segment", "model_year", "mileage", "condition_grade",
            "book_value_usd", "consigned_on", "channel"]
    return Auction(v_df[keep], l_df, pd.DataFrame(bids), pd.DataFrame(truth))
