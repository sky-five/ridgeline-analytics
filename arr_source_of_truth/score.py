"""Score the reconciliation against the planted labels, and summarise the as-of snapshot.

The labels (crm_side.labels) never enter the warehouse, so this is a check on data the models never saw.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import duckdb

from arr_source_of_truth.crm_side import labels

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "summary.json"

# status in arr_deal_matches that each planted defect should end up with
EXPECTED = {
    "duplicate": "duplicate",
    "won_not_billed": "won_not_billed",
    "annual_at_billed": "annual_at_billed",
    "amount_typo": "amount_differs",
}


@dataclass
class Summary:
    as_of: str
    won_deals: int
    sales_led_billing_changes: int
    deals_matched: int
    wrong_matches: int
    status_counts: dict[str, int]
    planted: dict[str, int]
    caught: dict[str, int]
    false_flags: int
    awaiting_billing: int
    closing_arr: int
    paying_customers: int
    last_month: dict[str, int]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def score(as_of: date, db_path: Path) -> Summary:
    with duckdb.connect(str(db_path), read_only=True) as con:
        deals = con.execute("select deal_id, status, change_key from arr_deal_matches").df()
        unmatched_changes = set(con.execute(
            "select change_key from stg_billing__subscription_changes where is_sales_led and change_key not in "
            "(select change_key from arr_deal_matches where change_key is not null)").df()["change_key"])
        sales_led = con.execute(
            "select count(*) from stg_billing__subscription_changes where is_sales_led").fetchone()[0]
        bridge = con.execute("select * from arr_bridge order by month_start desc limit 1").df().iloc[0]
        walk = con.execute("select * from arr_booking_walk order by month_start desc limit 1").df().iloc[0]

    lab = labels()
    x = deals.merge(lab[lab["deal_id"].notna()], on="deal_id", how="left")
    planted, caught = {}, {}
    for defect, status in EXPECTED.items():
        rows = x[x["defect"] == defect]
        planted[defect] = len(rows)
        caught[defect] = int((rows["status"] == status).sum())
    missing = lab[(lab["defect"] == "missing_deal")]
    missing = missing[missing["billing_change"].isin(
        set(unmatched_changes) | set(deals["change_key"].dropna()))]  # changes effective by the as-of date
    planted["missing_deal"] = len(missing)
    caught["missing_deal"] = int(missing["billing_change"].isin(unmatched_changes).sum())

    clean = x[x["defect"].isna()]
    flags = {"duplicate", "won_not_billed", "annual_at_billed", "amount_differs"}
    matched = x[x["change_key"].notna()]
    return Summary(
        as_of=str(as_of),
        won_deals=len(deals),
        sales_led_billing_changes=int(sales_led),
        deals_matched=len(matched),
        wrong_matches=int((matched["change_key"] != matched["billing_change"]).sum()),
        status_counts={k: int(v) for k, v in deals["status"].value_counts().sort_index().items()},
        planted=planted,
        caught=caught,
        false_flags=int(clean["status"].isin(flags).sum()),
        awaiting_billing=int((deals["status"] == "awaiting_billing").sum()),
        closing_arr=int(bridge["closing_arr_cents"]) // 100,
        paying_customers=int(bridge["paying_customers"]),
        last_month={k.removesuffix("_cents"): int(v) // 100 for k, v in walk.items() if k.endswith("_cents")}
        | {"month": str(walk["month_start"])[:7]},
    )
