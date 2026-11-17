"""On the lead-cost warehouse built once in conftest.py: the simulated exports and their mess, Bronze's audit,
Silver against the simulator, Gold against the simulator's truth and a pandas recomputation, the planted faults,
and the committed results."""
import json
import re
from datetime import date

import duckdb
import pandas as pd
import pytest

from lead_cost.faults import FAULTS, click_id_case, missing_day, renamed_campaign, run_fault, truncated_file
from lead_cost.load import checksum
from lead_cost.run import (
    CAMPAIGN_COST,
    CLIENT_COST,
    FAULTS_FILE,
    SUMMARY,
    campaign_cost_csv,
    client_cost_csv,
    summary,
    to_json,
)
from lead_cost.simulate import AS_OF, CAMPAIGNS, DOUBLE_DELIVERED, FIRST_DAY, campaign_id, simulate


@pytest.fixture(scope="module")
def con(lead_db):
    with duckdb.connect(str(lead_db), read_only=True) as c:
        yield c


@pytest.fixture(scope="module")
def s(lead_db, world):
    return summary(lead_db, world)


def _rows(world, source):
    return pd.concat([d.rows for d in world.deliveries if d.source == source], ignore_index=True)


def test_simulation_is_seeded(world):
    again = simulate()
    assert len(again.deliveries) == len(world.deliveries) == 548
    assert [checksum(d) for d in again.deliveries] == [checksum(d) for d in world.deliveries]
    pd.testing.assert_frame_equal(again.truth, world.truth)


def test_campaign_seed_matches_the_simulator():
    seed = pd.read_csv("lead_cost/dbt/seeds/campaigns.csv")
    assert seed["campaign_id"].tolist() == [campaign_id(c, p, t) for c, p, t, *_ in CAMPAIGNS]
    assert seed["campaign_id"].is_unique


def test_exports_are_messy_the_way_the_docstring_says(world):
    crm = _rows(world, "crm_leads")
    shapes = crm["phone"].str.replace(r"\d", "9", regex=True).unique()  # the +1 becomes +9 too
    assert sorted(shapes) == sorted(["(999) 999-9999", "999-999-9999", "+9 999 999 9999", "9999999999"])
    assert crm["click_id"].dropna().str.match(r"^(gclid|fbclid)=").any()
    assert (crm["email"].dropna() != crm["email"].dropna().str.lower()).any()
    social = _rows(world, "social_spend")
    assert social["campaign"].str.endswith(" ").any()
    search_names = set(_rows(world, "search_spend")["campaign_name"])
    assert "North Roofing - Roof Repair" in search_names and "NORTH_ROOFING_ROOF-REPAIR" in set(social["campaign"])
    # the same search day arrives in up to three files with different spend; the last one is final
    search = _rows(world, "search_spend")
    day = search[(search["date"] == "2026-05-10") & (search["campaign_name"] == "North Roofing - Roof Repair")]
    assert len(day) == 3 and day["cost_micros"].nunique() > 1


def test_bronze_audit_counts_what_landed(con):
    a = con.sql("select * from bronze.load_audit").df()
    assert len(a) == 548 and (a["loaded_rows"] == a["declared_rows"]).all()
    repeated = a[a.duplicated("checksum", keep=False)]
    assert repeated["file"].unique().tolist() == [f"{DOUBLE_DELIVERED[0]}_{DOUBLE_DELIVERED[1]:%Y%m%d}.csv"]
    assert len(repeated) == 2


def test_silver_spend_is_the_final_restated_value(con, world):
    silver = con.sql("select campaign_id, day, spend, clicks from slv_ad_spend").df()
    assert silver["campaign_id"].notna().all()
    assert len(silver) == len(CAMPAIGNS) * ((AS_OF - FIRST_DAY).days + 1)
    truth = world.spend[["campaign_id", "day", "spend", "clicks"]].copy()
    m = truth.merge(silver.assign(day=pd.to_datetime(silver["day"]).dt.date), on=["campaign_id", "day"])
    assert len(m) == len(truth)
    assert (m["spend_x"].round(2) == m["spend_y"].round(2)).all() and (m["clicks_x"] == m["clicks_y"]).all()


def test_every_name_and_number_maps_to_a_campaign(con):
    assert con.sql("select count(*) from slv_ad_clicks where campaign_id is null").fetchone()[0] == 0
    assert con.sql("select count(*) from slv_tracking_numbers where campaign_id is null").fetchone()[0] == 0
    keys = con.sql("select distinct campaign_key from slv_ad_spend").df()["campaign_key"]
    assert keys.str.fullmatch(r"[a-z0-9_]+").all() and len(keys) == 8  # three keys are shared by search and social


def test_silver_crm_keeps_the_last_version_and_cleans_ids(con, world):
    raw = _rows(world, "crm_leads")
    last = raw.sort_values("updated_at", kind="stable").groupby("crm_id").tail(1).set_index("crm_id")
    silver = con.sql("select crm_id, status, phone, email, click_id from slv_crm_records").df().set_index("crm_id")
    assert len(silver) == len(last)
    assert (silver["status"] == last.loc[silver.index, "status"]).all()
    assert silver["phone"].str.fullmatch(r"\d{10}").all()
    assert not silver["click_id"].dropna().str.contains("=").any()
    assert (silver["email"].dropna() == silver["email"].dropna().str.strip().str.lower()).all()


def test_gold_leads_against_the_truth(s):
    t = s["truth_check"]
    assert t["people"] == s["gold_leads"]["leads"]
    assert t["people_missing_from_gold"] == 0
    assert t["attributed_to_the_wrong_campaign"] == 0
    assert t["outcome_mismatches"] == 0
    assert t["unattributed_paid_were_lost_click_id_forms_with_no_call"]
    assert t["paid_leads_unattributed"] + t["organic_leads"] == s["gold_leads"]["attributed_by"]["none"]


def test_unattributed_paid_leads_recomputed_from_the_exports(con, world):
    """Independently of Gold: a paid person is unreachable when none of their CRM records has a click id and they
    never phoned."""
    crm = _rows(world, "crm_leads")
    crm["digits"] = crm["phone"].str.replace(r"\D", "", regex=True).str[-10:]
    has_click = set(crm.loc[crm["click_id"].notna(), "digits"])
    callers = set(_rows(world, "calls")["caller"].str[-10:])
    paid = world.truth[world.truth["campaign_id"].notna()]
    unreachable = paid[~paid["phone"].isin(has_click) & ~paid["phone"].isin(callers)]
    gold = con.sql("select phone from gold_leads where campaign_id is null").df()["phone"]
    assert set(unreachable["phone"]) == set(gold) - set(world.truth.loc[world.truth["campaign_id"].isna(), "phone"])


def test_duplicate_crm_records_become_one_lead(con, world):
    multi = world.truth[world.truth["crm_records"] > 1]
    assert len(multi) > 200
    g = con.sql("select phone, crm_records from gold_leads").df().set_index("phone")
    delivered = multi[multi["phone"].isin(g.index)]
    assert (g.loc[delivered["phone"], "crm_records"].values >= 1).all()
    assert g["crm_records"].sum() == con.sql("select count(*) from slv_crm_records").fetchone()[0]


def test_campaign_cost_recomputed_in_pandas(con, world):
    leads = con.sql("select campaign_id, issued, demo from gold_leads where campaign_id is not null").df()
    by = leads.groupby("campaign_id").agg(leads=("issued", "size"), issued=("issued", "sum"), demos=("demo", "sum"))
    spend = world.spend.groupby("campaign_id")["spend"].sum()
    gold = con.sql("select * from gold_campaign_cost").df().set_index("campaign_id")
    for cid, r in gold.iterrows():
        assert r["spend"] == pytest.approx(spend[cid], abs=0.01)
        assert (r["leads"], r["issued_leads"], r["demos"]) == tuple(by.loc[cid])
        assert r["cost_per_issued_lead"] == pytest.approx(round(spend[cid] / by.loc[cid, "issued"], 2), abs=0.01)
        assert r["cost_per_demo"] == pytest.approx(round(spend[cid] / by.loc[cid, "demos"], 2), abs=0.01)


def test_client_cost_adds_up(con):
    c = con.sql("select * from gold_client_cost").df()
    k = con.sql("""select client, sum(spend) as spend, sum(issued_leads) as issued from gold_campaign_cost
                   group by 1""").df().set_index("client")
    for r in c.itertuples():
        assert r.spend == pytest.approx(k.loc[r.client, "spend"], abs=0.01)
        assert r.issued_leads == k.loc[r.client, "issued"]


def _file_day(f: str) -> date:
    d = re.search(r"(\d{8})\.csv$", f).group(1)
    return date(int(d[:4]), int(d[4:6]), int(d[6:]))


def test_faults_change_only_what_they_say(world):
    ds = world.deliveries
    cut = {d.file: d for d in truncated_file(ds)}
    for d in ds:
        n = len(cut[d.file].rows)
        assert n == (int(len(d.rows) * 0.6) if d.file == "crm_leads_20260610.csv" else len(d.rows))
        assert cut[d.file].declared_rows == d.declared_rows
    assert {d.file for d in ds} - {d.file for d in missing_day(ds)} == {"social_spend_20260620.csv"}
    renamed = renamed_campaign(ds)
    for before, after in zip(ds, renamed, strict=True):
        changed = not before.rows.equals(after.rows)
        touches = before.source in ("social_spend", "social_clicks") and _file_day(before.file) >= date(2026, 6, 15)
        assert changed == touches
    lowered = click_id_case(ds)
    for before, after in zip(ds, lowered, strict=True):
        if before.source == "crm_leads" and before.file < "crm_leads_20260601.csv":
            assert before.rows.equals(after.rows)


def test_a_lowercased_click_id_is_caught_and_only_by_its_test(world):
    r = run_fault(world.deliveries, click_id_case)
    assert r["failing_tests"] == ["assert_crm_click_ids_match"]
    assert r["headline"]["unattributed_leads"] > 1000  # paid leads quietly turned into unattributed ones


def test_committed_faults_were_all_caught():
    faults = json.loads(FAULTS_FILE.read_text())
    assert [f["fault"] for f in faults] == [f.name for f, _ in FAULTS]
    for f in faults:
        assert f["caught"] and f["written_to_catch_it"] in f["failing_tests"]


def test_committed_results_are_current(lead_db, s):
    assert SUMMARY.read_text() == to_json(s)
    assert CAMPAIGN_COST.read_text() == campaign_cost_csv(lead_db)
    assert CLIENT_COST.read_text() == client_cost_csv(lead_db)


def test_readme_quotes_the_committed_results():
    readme = open("lead_cost/README.md").read()
    s = json.loads(SUMMARY.read_text())
    h, t, g = s["headline"], s["truth_check"], s["gold_leads"]
    for figure in (f"${h['spend']:,.2f}", f"{h['paid_issued_leads']} issued leads", f"{h['paid_demos']} demos",
                   f"${h['cost_per_issued_lead']:.2f} per issued lead", f"{g['leads']:,} leads from",
                   f"{s['silver']['crm_records']:,} records", f"({g['attributed_by']['crm_click_id']:,} leads)",
                   f"{t['organic_leads']} of the {g['attributed_by']['none']} unattributed",
                   f"The other {t['paid_leads_unattributed']} are paid leads ({t['paid_leads_unattributed_issued']}"):
        assert figure in readme, figure
    for f in json.loads(FAULTS_FILE.read_text()):
        w = f["without_the_tests"]["cost_per_issued_lead"]
        assert f"${w:.2f} ({f['cost_per_issued_lead_moves_by']:+.2f})".replace("+", "+$").replace("-", "-$") in readme
