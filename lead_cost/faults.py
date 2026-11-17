"""Silent failures, planted one at a time into the deliveries. Each one still loads and still builds: the cost
figures just come out wrong. The dbt tests are there to catch them; `run_fault` builds a fresh warehouse with the
fault, runs the tests, and reports which failed and what cost per issued lead would have shown without them."""
import json
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import duckdb

from lead_cost.load import dbt, load
from lead_cost.simulate import Delivery


@dataclass
class Fault:
    name: str
    what: str
    caught_by: str  # the dbt test written for it


def truncated_file(ds: list[Delivery]) -> list[Delivery]:
    """The 2026-06-10 CRM file arrives cut off: 60% of its rows, though the manifest still says all of them."""
    return [replace(d, rows=d.rows.iloc[: int(len(d.rows) * 0.6)]) if d.file == "crm_leads_20260610.csv" else d
            for d in ds]


def missing_day(ds: list[Delivery]) -> list[Delivery]:
    """The social platform's 2026-06-20 file never arrives (it carries only that day, so nothing restates it)."""
    return [d for d in ds if d.file != "social_spend_20260620.csv"]


def renamed_campaign(ds: list[Delivery]) -> list[Delivery]:
    """From 2026-06-15 the social home-battery campaign is renamed in the platform; its spend and clicks no longer
    map to a campaign."""
    old, new = "VALLEY_SOLAR_HOME-BATTERY", "VALLEY_SOLAR_BATTERY-SUMMER"
    out = []
    for d in ds:
        day = date(int(d.file[-12:-8]), int(d.file[-8:-6]), int(d.file[-6:-4])) if d.file[-12:-4].isdigit() else None
        if d.source in ("social_spend", "social_clicks") and day and day >= date(2026, 6, 15):
            rows = d.rows.copy()
            col = "campaign" if d.source == "social_spend" else "campaign_name"
            rows[col] = rows[col].str.replace(old, new, regex=False)
            d = replace(d, rows=rows)
        out.append(d)
    return out


def click_id_case(ds: list[Delivery]) -> list[Delivery]:
    """From 2026-06-01 a form update stores click ids in lower case; they stop matching the ad platforms' clicks."""
    out = []
    for d in ds:
        if d.source == "crm_leads" and d.file >= "crm_leads_20260601.csv":
            rows = d.rows.copy()
            rows["click_id"] = rows["click_id"].map(lambda v: v.lower() if isinstance(v, str) else v)
            d = replace(d, rows=rows)
        out.append(d)
    return out


FAULTS = [
    (Fault("truncated_file", truncated_file.__doc__.split(":")[0], "assert_every_batch_fully_loaded"), truncated_file),
    (Fault("missing_day", missing_day.__doc__.split(" (")[0], "assert_spend_every_day"), missing_day),
    (Fault("renamed_campaign", renamed_campaign.__doc__.split(";")[0], "assert_spend_maps_to_a_campaign"),
     renamed_campaign),
    (Fault("click_id_case", click_id_case.__doc__.split(";")[0], "assert_crm_click_ids_match"), click_id_case),
]


def headline(db: Path) -> dict:
    """The figures a silent failure would move: spend, issued leads and demos attributed to a campaign, cost per
    issued lead, unattributed leads."""
    with duckdb.connect(str(db), read_only=True) as con:
        spend, issued, demos, unattr = con.sql("""select round(sum(spend), 2)::double, sum(issued_leads)::int,
                                                  sum(demos)::int, sum(unattributed_leads)::int
                                                  from gold_client_cost""").fetchone()
        by_client = {c: v for c, v in con.sql("select client, cost_per_issued_lead::double from gold_client_cost "
                                              "order by client").fetchall()}
    return {"spend": float(spend), "paid_issued_leads": issued, "paid_demos": demos, "unattributed_leads": unattr,
            "cost_per_issued_lead": round(spend / issued, 2), "cost_per_issued_lead_by_client": by_client}


def failing_tests(target: Path) -> list[str]:
    results = json.loads((target / "run_results.json").read_text())["results"]
    return sorted({r["unique_id"].split(".")[2] for r in results if r["status"] in ("fail", "error")})


def run_fault(deliveries: list[Delivery], fn) -> dict:
    """Load the faulty deliveries, build without tests (dbt run), then test. What the build shows and what failed."""
    with tempfile.TemporaryDirectory() as tmp:
        db, target = Path(tmp) / "fault.duckdb", Path(tmp) / "target"
        load(db, fn(deliveries))
        dbt(db, "seed", target)
        dbt(db, "run", target)
        dbt(db, "test", target, check=False)
        return {"failing_tests": failing_tests(target), "headline": headline(db)}
