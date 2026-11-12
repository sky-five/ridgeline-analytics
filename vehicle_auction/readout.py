"""Read out the reserve-price test from the warehouse, and check it against the planted truth.

Unit: a vehicle consigned from 2026-04-06, split 50/50 by a hash of its id. Outcome: its first run.
- Sample-ratio check first: a split far from 50/50 means the assignment is broken and nothing else is read.
- Conversion (sold on the block or if-sale, per offered first run): difference, 95% CI, two-sided p.
- Proceeds per offered first run (0 when it does not sell): the money question, same treatment.
- Price-to-book when sold is reported but not tested: the lower reserve sells cars the control arm
  would have no-sold, so the sold groups are different cars and their average price is not a fair comparison.
- A/A check: the same hash split on vehicles consigned before the test should show no difference.
- Truth: the simulator knows every test car's first-run outcome under both arms, so the true effect on
  exactly these cars is known and the CI either covers it or not.
"""
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from vehicle_auction.simulate import Auction, arm_for

RESULTS = Path(__file__).resolve().parent / "results" / "summary.json"
Z95 = 1.959964


@dataclass
class Diff:
    control: float
    treatment: float
    diff: float
    ci_low: float
    ci_high: float
    p_value: float


@dataclass
class Readout:
    vehicles_control: int
    vehicles_treatment: int
    srm_p_value: float
    conversion: Diff
    proceeds_per_offered_usd: Diff
    price_to_book_when_sold_control: float
    price_to_book_when_sold_treatment: float
    aa_conversion_diff: float
    aa_conversion_p_value: float
    true_conversion_diff: float
    true_proceeds_diff_usd: float
    ci_covers_truth: bool


def _p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def srm_p_value(a: int, b: int) -> float:
    """Chi-square test (1 df) of a 50/50 split."""
    expected = (a + b) / 2
    chi2 = ((a - expected) ** 2 + (b - expected) ** 2) / expected
    return math.erfc(math.sqrt(chi2 / 2))


def proportion_diff(x_c: int, n_c: int, x_t: int, n_t: int) -> Diff:
    p_c, p_t = x_c / n_c, x_t / n_t
    se = math.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    pooled = (x_c + x_t) / (n_c + n_t)
    se0 = math.sqrt(pooled * (1 - pooled) * (1 / n_c + 1 / n_t))
    d = p_t - p_c
    return Diff(p_c, p_t, d, d - Z95 * se, d + Z95 * se, _p_two_sided(d / se0))


def mean_diff(m_c: float, sd_c: float, n_c: int, m_t: float, sd_t: float, n_t: int) -> Diff:
    se = math.sqrt(sd_c**2 / n_c + sd_t**2 / n_t)
    d = m_t - m_c
    return Diff(m_c, m_t, d, d - Z95 * se, d + Z95 * se, _p_two_sided(d / se))


def _truth(auction: Auction) -> tuple[float, float]:
    """True effect on exactly the test cars: each car's first run under both arms (withdrawn excluded)."""
    t = auction.truth[auction.truth["control_status"] != "withdrawn"]
    sold = {arm: t[f"{arm}_status"].isin(["sold", "if_sale"]) for arm in ("control", "treatment")}
    proceeds = {arm: (sold[arm] * t["high_bid_usd"].fillna(0)).mean() for arm in sold}
    return float(sold["treatment"].mean() - sold["control"].mean()), float(proceeds["treatment"] - proceeds["control"])


def readout(db_path: Path, auction: Auction) -> Readout:
    with duckdb.connect(str(db_path), read_only=True) as con:
        arms = {r[0]: r for r in con.execute(
            "select arm, vehicles, offered, converted, proceeds_per_offered_usd, proceeds_sd_usd,"
            " price_to_book_when_sold from reserve_test_arms"
        ).fetchall()}
        pre = con.execute("""
            select vehicle_id, first_run_converted
            from fct_vehicles
            where test_arm is null and first_run_offered
        """).fetchall()
    c, t = arms["control"], arms["treatment"]
    aa = {"control": [0, 0], "treatment": [0, 0]}
    for vehicle_id, converted in pre:
        aa[arm_for(vehicle_id)][0] += int(converted)
        aa[arm_for(vehicle_id)][1] += 1
    aa_diff = proportion_diff(*aa["control"], *aa["treatment"])
    conversion = proportion_diff(c[3], c[2], t[3], t[2])
    true_conv, true_proceeds = _truth(auction)
    return Readout(
        vehicles_control=c[1],
        vehicles_treatment=t[1],
        srm_p_value=srm_p_value(c[1], t[1]),
        conversion=conversion,
        proceeds_per_offered_usd=mean_diff(c[4], c[5], c[2], t[4], t[5], t[2]),
        price_to_book_when_sold_control=c[6],
        price_to_book_when_sold_treatment=t[6],
        aa_conversion_diff=aa_diff.diff,
        aa_conversion_p_value=aa_diff.p_value,
        true_conversion_diff=true_conv,
        true_proceeds_diff_usd=true_proceeds,
        ci_covers_truth=conversion.ci_low <= true_conv <= conversion.ci_high,
    )


def _rounded(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _rounded(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_rounded(v) for v in x]
    return x


def summary(db_path: Path, auction: Auction) -> dict:
    """Everything the README quotes: channel sell-through and the test readout."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        cols = ["channel", "listings_offered", "sell_through_on_block", "conversion_rate",
                "vehicles_offered", "vehicle_sell_through", "avg_bidders"]
        channels = [dict(zip(cols, r, strict=True)) for r in con.execute(
            f"select {', '.join(cols)} from sell_through_by_channel order by channel").fetchall()]
        totals = con.execute("""
            select count(*), count(*) filter (where is_offered), count(*) filter (where is_converted),
                   count(distinct vehicle_id)
            from fct_listings
        """).fetchone()
    return _rounded({
        "listings": totals[0],
        "listings_offered": totals[1],
        "listings_converted": totals[2],
        "vehicles": totals[3],
        "bids": len(auction.bids),
        "channels": channels,
        "reserve_test": asdict(readout(db_path, auction)),
    })


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2) + "\n"
