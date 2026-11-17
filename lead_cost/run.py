"""Write the lead-cost results: results/summary.json (what arrived, what Bronze/Silver/Gold did with it, how the
leads were attributed, the pipeline against the simulator's truth, the headline cost figures),
results/campaign_cost.csv and results/client_cost.csv (Gold as built), and results/faults.json (each planted
silent failure, the tests that caught it, and what the cost figures would have shown). Every number comes from the
warehouse, except the truth check, which compares it with the simulator."""
import json
from pathlib import Path

import duckdb
import numpy as np

from lead_cost.faults import FAULTS, headline, run_fault
from lead_cost.simulate import AS_OF, FIRST_DAY, World

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SUMMARY = RESULTS / "summary.json"
CAMPAIGN_COST = RESULTS / "campaign_cost.csv"
CLIENT_COST = RESULTS / "client_cost.csv"
FAULTS_FILE = RESULTS / "faults.json"


def to_json(obj) -> str:
    return json.dumps(obj, indent=2) + "\n"


def _one(con, sql: str):
    v = con.sql(sql).fetchone()[0]
    return int(v) if isinstance(v, int | np.integer) else v


def truth_check(con, w: World) -> dict:
    """Gold against what really happened: a lead's campaign is never wrong, outcomes match, and the paid leads Gold
    can't attribute are exactly the form leads whose click id got lost and who never phoned."""
    g = con.sql("select client, phone, campaign_id, issued, demo from gold_leads").df()
    m = w.truth.merge(g, on=["client", "phone"], how="left", suffixes=("_true", "_gold"), indicator=True)
    attributed = m[m["campaign_id_gold"].notna()]
    lost = m[m["campaign_id_true"].notna() & m["campaign_id_gold"].isna()]
    return {
        "people": len(w.truth),
        "people_missing_from_gold": int((m["_merge"] == "left_only").sum()),
        "attributed_to_the_wrong_campaign": int((attributed["campaign_id_gold"] != attributed["campaign_id_true"])
                                                .sum()),
        "outcome_mismatches": int(((m["issued_true"] != m["issued_gold"]) | (m["demo_true"] != m["demo_gold"])).sum()),
        "paid_leads": int(m["campaign_id_true"].notna().sum()),
        "paid_leads_unattributed": len(lost),
        "paid_leads_unattributed_issued": int(lost["issued_true"].sum()),
        "unattributed_paid_were_lost_click_id_forms_with_no_call": bool(
            ((lost["came_by"] == "form") & ~lost["click_id_reaches_crm"]).all()),
        "organic_leads": int(m["campaign_id_true"].isna().sum()),
    }


def summary(db: Path, w: World) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        files = con.sql("""select source, count(*) as files, sum(loaded_rows)::int as rows,
                                  (count(*) - count(distinct checksum))::int as repeated_files
                           from bronze.load_audit group by source order by source""").df()
        exports = {r.source: {"files": int(r.files), "rows": int(r.rows), "repeated_files": int(r.repeated_files)}
                   for r in files.itertuples()}
        spend_rows_in = _one(con, "select count(*) from bronze.search_spend") + \
            _one(con, "select count(*) from bronze.social_spend")
        spend_rows = _one(con, "select count(*) from slv_ad_spend")
        silver = {
            "spend_rows": spend_rows,
            "spend_rows_dropped_as_restated_or_repeated": spend_rows_in - spend_rows,
            "clicks": _one(con, "select count(*) from slv_ad_clicks"),
            "calls": _one(con, "select count(*) from slv_calls"),
            "crm_rows_delivered": _one(con, "select count(*) from bronze.crm_leads"),
            "crm_records": _one(con, "select count(*) from slv_crm_records"),
            "crm_click_ids_stored_as_param": _one(con, "select count(distinct crm_id) from bronze.crm_leads "
                                                       "where click_id like '%clid=%'"),
            "phone_formats_seen": _one(con, """select count(distinct regexp_replace(phone, '[0-9]', '9', 'g'))
                                               from bronze.crm_leads"""),
        }
        n_leads = _one(con, "select count(*) from gold_leads")
        leads = {
            "leads": n_leads,
            "crm_records_merged_into_another_lead": silver["crm_records"] - n_leads,
            "came_by": dict(con.sql("select came_by, count(*)::int from gold_leads group by 1 order by 1").fetchall()),
            "attributed_by": dict(con.sql("""select attributed_by, count(*)::int from gold_leads group by 1
                                             order by 2 desc""").fetchall()),
            "issued": _one(con, "select count(*) filter (where issued) from gold_leads"),
            "demos": _one(con, "select count(*) filter (where demo) from gold_leads"),
        }
        truth = truth_check(con, w)
    return {"first_day": FIRST_DAY.isoformat(), "as_of": AS_OF.isoformat(), "exports": exports, "silver": silver,
            "gold_leads": leads, "truth_check": truth, "headline": headline(db)}


def _csv(db: Path, table: str) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql(f"select * from {table} order by 1").df()
    return df.to_csv(index=False, lineterminator="\n")


def campaign_cost_csv(db: Path) -> str:
    return _csv(db, "gold_campaign_cost")


def client_cost_csv(db: Path) -> str:
    return _csv(db, "gold_client_cost")


def faults(w: World, clean: dict) -> list[dict]:
    out = []
    for f, fn in FAULTS:
        r = run_fault(w.deliveries, fn)
        h = r["headline"]
        move = round(h["cost_per_issued_lead"] - clean["cost_per_issued_lead"], 2)
        out.append({"fault": f.name, "what": f.what, "written_to_catch_it": f.caught_by,
                    "failing_tests": r["failing_tests"], "caught": f.caught_by in r["failing_tests"],
                    "without_the_tests": h,
                    "cost_per_issued_lead_moves_by": move})
    return out
