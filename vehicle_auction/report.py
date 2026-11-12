"""The vehicle auction's dashboard tables, from its committed results (no warehouse needed).

`python -m vehicle_auction` writes results/summary.json and results/sell_through_weekly.csv;
scripts/export_reporting.py turns them into reporting.auction_* tables for the Evidence page.
The auction is a separate learning project, so its numbers are fixed and do not move with the nightly build.
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS_DIR / "summary.json"
WEEKLY = RESULTS_DIR / "sell_through_weekly.csv"

CHANNEL_LABELS = {"in_lane": "Physical lane", "simulcast": "Lane + simulcast", "online_timed": "Timed online"}
CHANNEL_ORDER = ["in_lane", "simulcast", "online_timed"]


def weekly_frame(db_path: Path) -> pd.DataFrame:
    """Each channel and sale week with the three rates side by side (vehicle basis by week first offered)."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        df = con.execute("""
            select l.channel, cast(l.sale_week as date) as sale_week,
                   l.offered, l.sold_on_block, l.if_sales,
                   round(l.sell_through_on_block, 4) as sell_through_on_block,
                   round(l.conversion_rate, 4) as conversion_rate,
                   v.vehicles_offered, v.vehicles_sold,
                   round(v.vehicle_sell_through, 4) as vehicle_sell_through
            from sell_through_weekly as l
            inner join vehicle_sell_through_weekly as v
                on l.channel = v.channel and l.sale_week = v.sale_week
            order by l.sale_week, l.channel
        """).df()
    return df


def to_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, lineterminator="\n")


def tables() -> dict[str, pd.DataFrame]:
    """reporting.auction_channels, auction_weekly and auction_reserve_test, or nothing if results are missing."""
    if not (SUMMARY.exists() and WEEKLY.exists()):
        return {}
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    rt = s["reserve_test"]

    channels = pd.DataFrame(s["channels"])
    channels["channel_label"] = channels["channel"].map(CHANNEL_LABELS)
    channels["sort"] = channels["channel"].map(CHANNEL_ORDER.index)
    channels = channels.sort_values("sort").reset_index(drop=True)
    channels["listings_total"], channels["vehicles_total"], channels["bids_total"] = (
        s["listings"], s["vehicles"], s["bids"])

    weekly = pd.read_csv(WEEKLY, parse_dates=["sale_week"])
    weekly["sale_week"] = weekly["sale_week"].dt.date
    weekly["channel_label"] = weekly["channel"].map(CHANNEL_LABELS)

    checks = {"vehicles_control": rt["vehicles_control"], "vehicles_treatment": rt["vehicles_treatment"],
              "srm_p_value": rt["srm_p_value"], "aa_conversion_diff": rt["aa_conversion_diff"],
              "aa_conversion_p_value": rt["aa_conversion_p_value"], "ci_covers_truth": rt["ci_covers_truth"]}
    reserve = pd.DataFrame([
        {"sort": 0, "metric": "Conversion rate, first run", "unit": "rate", **rt["conversion"],
         "true_diff": rt["true_conversion_diff"], **checks},
        {"sort": 1, "metric": "Seller proceeds per car offered (0 if no sale)", "unit": "usd",
         **rt["proceeds_per_offered_usd"], "true_diff": rt["true_proceeds_diff_usd"], **checks},
    ])
    reserve["ci_covers"] = (reserve["ci_low"] <= reserve["true_diff"]) & (reserve["true_diff"] <= reserve["ci_high"])
    reserve["price_to_book_control"] = rt["price_to_book_when_sold_control"]
    reserve["price_to_book_treatment"] = rt["price_to_book_when_sold_treatment"]
    return {"auction_channels": channels, "auction_weekly": weekly, "auction_reserve_test": reserve}
