"""The simulated exports, the data-quality checks scored against the planted faults, the cleaning that must give back
the true book, the KPI tree's identities, the exact change split, and the committed results."""
import math
from datetime import date

import duckdb
import pandas as pd
import pytest

from insurance_kpi import kpi
from insurance_kpi.profile import CHECKS, column_profile, load, run_checks, score_checks
from insurance_kpi.run import outputs
from insurance_kpi.simulate import DQ_FAULTS, HAIL, VALUATION, Book, simulate


def test_simulation_is_seeded(book):
    again = simulate()
    pd.testing.assert_frame_equal(book.claims, again.claims)
    pd.testing.assert_frame_equal(book.policies, again.policies)
    pd.testing.assert_frame_equal(book.planted, again.planted)


def test_true_book_holds_together(book):
    p, c = book.true_policies, book.true_claims
    assert p["policy_id"].is_unique and c["claim_id"].is_unique
    assert (p["end_date"] > p["start_date"]).all() and (p["written_premium"] > 0).all()
    m = c.merge(p, on="policy_id", how="left", validate="many_to_one")
    assert m["line"].notna().all()
    assert ((m["loss_date"] >= m["start_date"]) & (m["loss_date"] < m["end_date"])).all()
    assert (c["reported_date"] >= c["loss_date"]).all() and (c["reported_date"] <= VALUATION).all()
    assert (c.loc[c["status"] == "closed", "case_reserve"] == 0).all() and (c["paid"] >= 0).all()


def test_every_planted_fault_is_in_the_export(book):
    assert book.planted.groupby("fault").size().to_dict() == DQ_FAULTS
    assert len(book.claims) == len(book.true_claims) + sum(
        DQ_FAULTS[f] for f in ("duplicate_claim", "orphan_claim", "loss_outside_term"))
    assert len(book.policies) == len(book.true_policies) + DQ_FAULTS["zero_premium_test_policy"]


def test_each_check_flags_exactly_its_planted_rows(con, book):
    scored = score_checks(run_checks(con), book.planted).set_index("check_name")
    for fault, n in DQ_FAULTS.items():
        assert scored.loc[fault, ["rows_flagged", "caught", "false_flags", "missed"]].tolist() == [n, n, 0, 0], fault
    passing = scored.drop(index=list(DQ_FAULTS))
    assert (passing["rows_flagged"] == 0).all()


def _set(df: pd.DataFrame, col: str, value, where=None) -> pd.DataFrame:
    """A copy with one row's column changed (the first row matching `where`, else the first row)."""
    df = df.copy()
    i = df.index[where(df)][0] if where else df.index[0]
    df[col] = df[col].astype(object) if isinstance(value, str) else df[col]
    df.loc[i, col] = value
    return df


NEW_FAULTS = {  # passing check -> a change to (policies, claims) that one row should trip
    "duplicate_policy": lambda p, c: (pd.concat([p, p.iloc[[5]]], ignore_index=True), c),
    "term_not_positive": lambda p, c: (_set(p, "end_date", p.loc[0, "start_date"]), c),
    "unknown_code": lambda p, c: (_set(p, "channel", "agent"), c),
    "commission_out_of_range": lambda p, c: (_set(p, "commission_rate", 0.45), c),
    "unknown_status": lambda p, c: (p, _set(c, "status", "reopened")),
    "negative_reserve": lambda p, c: (p, _set(c, "case_reserve", -1.0, lambda d: d["status"] == "open")),
    "closed_with_reserve": lambda p, c: (p, _set(c, "case_reserve", 50.0, lambda d: d["status"] == "closed")),
}


@pytest.mark.parametrize("check", list(NEW_FAULTS))
def test_passing_checks_catch_a_new_fault(book, check):
    assert check in CHECKS and check not in DQ_FAULTS
    p, c = NEW_FAULTS[check](book.policies, book.claims)
    with duckdb.connect() as fresh:
        load(fresh, Book(p, c, book.true_policies, book.true_claims, book.planted))
        flagged = run_checks(fresh)
    assert len(flagged[check]) == 1
    assert all(len(flagged[f]) == n for f, n in DQ_FAULTS.items())  # the planted ones are unchanged


def test_cleaning_gives_back_the_true_book(con, book):
    claims = con.sql("select * from clean.claims order by claim_id").df()
    true_c = book.true_claims.sort_values("claim_id").reset_index(drop=True)
    for col in ("loss_date", "reported_date"):
        claims[col] = pd.to_datetime(claims[col]).dt.date
    pd.testing.assert_frame_equal(claims, true_c, check_dtype=False)

    pols = con.sql("select * from clean.policies order by policy_id").df()
    true_p = book.true_policies.sort_values("policy_id").reset_index(drop=True)
    missing = set(book.planted.loc[book.planted["fault"] == "missing_province", "key"])
    assert set(pols.loc[pols["province"] == "unknown", "policy_id"]) == missing
    keep = ~pols["policy_id"].isin(missing)
    for col in ("start_date", "end_date"):
        pols[col] = pd.to_datetime(pols[col]).dt.date
    pd.testing.assert_frame_equal(pols[keep].reset_index(drop=True), true_p[keep].reset_index(drop=True),
                                  check_dtype=False)


def test_column_profile(con):
    prof = column_profile(con).set_index(["table_name", "column_name"])
    assert prof.loc[("policies", "province"), "nulls"] == DQ_FAULTS["missing_province"]
    assert prof.loc[("claims", "claim_id"), "rows"] - prof.loc[("claims", "claim_id"), "distinct_values"] == \
        DQ_FAULTS["duplicate_claim"]
    assert float(prof.loc[("claims", "paid"), "min_value"]) < 0
    assert (prof.drop(index=[("policies", "province")])["nulls"] == 0).all()


def _earned(p: pd.DataFrame, year: int) -> pd.Series:
    lo, hi = pd.Timestamp(date(year, 1, 1)), pd.Timestamp(date(year + 1, 1, 1))
    s, e = pd.to_datetime(p["start_date"]), pd.to_datetime(p["end_date"])
    days = (e.clip(upper=hi) - s.clip(lower=lo)).dt.days.clip(lower=0)
    return days / (e - s).dt.days


def test_tree_totals_match_a_pandas_recount(con, book):
    t = kpi.tree(con).set_index(["ay", "line"])
    p, c = book.true_policies, book.true_claims.merge(book.true_policies[["policy_id", "line"]], on="policy_id")
    c = c.assign(ay=pd.to_datetime(c["loss_date"]).dt.year, incurred=c["paid"] + c["case_reserve"])
    for year in kpi.YEARS:
        share = _earned(p, year)
        for line in ("auto", "home"):
            on = p["line"] == line
            row = t.loc[(year, line)]
            assert row["exposure"] == pytest.approx(share[on].sum())
            assert row["earned_premium"] == pytest.approx((share * p["written_premium"])[on].sum())
            cl = c[(c["ay"] == year) & (c["line"] == line)]
            assert row["claims"] == len(cl) and row["incurred"] == pytest.approx(cl["incurred"].sum())
        assert t.loc[(year, "all"), "claims"] == t.loc[(year, "auto"), "claims"] + t.loc[(year, "home"), "claims"]


def test_a_full_term_earns_one_policy_year(book):
    p = book.true_policies
    total = sum(_earned(p, y) for y in range(2023, 2027))
    assert total.round(9).eq(1).all()


def test_tree_identities_hold(con):
    t = kpi.tree(con)
    assert t["loss_ratio"].to_numpy() == pytest.approx(
        (t["frequency"] * t["severity"] / t["avg_earned_premium"]).to_numpy())
    assert t["combined_ratio"].to_numpy() == pytest.approx((t["loss_ratio"] + t["commission_ratio"]
                                                            + t["admin_ratio"]).to_numpy())


def test_change_contributions_add_up_to_the_parent(con):
    ch = kpi.change(kpi.tree(con))
    for line in kpi.LINES:
        c = ch[ch["line"] == line].set_index("node")["contribution_pts"]
        assert c["frequency"] + c["severity"] + c["avg_earned_premium"] == pytest.approx(c["loss_ratio"], abs=1e-12)
        assert c["commission_ratio"] + c["admin_ratio"] == pytest.approx(c["expense_ratio"], abs=1e-12)
        assert c["loss_ratio"] + c["expense_ratio"] == pytest.approx(c["combined_ratio"], abs=1e-12)


def test_change_split_on_hand_numbers():
    t = pd.DataFrame([(y, ln, 100.0, 100.0 * prem, 0.0, n, n * sev) for ln in kpi.LINES
                      for y, prem, n, sev in [(2024, 1000, 10, 3000), (2025, 1100, 12, 3000)]],
                     columns=["ay", "line"] + kpi.SUMS)
    t["commission"] = t["earned_premium"] * 0.1
    c = kpi.change(kpi._ratios(t)).query("line == 'all'").set_index("node")["contribution_pts"]
    lr24, lr25 = 10 * 3000 / 100000, 12 * 3000 / 110000
    w = (lr25 - lr24) / math.log(lr25 / lr24)
    assert c["severity"] == pytest.approx(0)
    assert c["frequency"] == pytest.approx(w * math.log(1.2))
    assert c["avg_earned_premium"] == pytest.approx(-w * math.log(1.1))


def test_planted_changes_show_up_in_the_tree(con):
    ch = kpi.change(kpi.tree(con)).set_index(["line", "node"])
    # home: the hail frequency is the biggest driver; auto: severity is, and premium pulls the other way
    assert ch.loc[("home", "frequency"), "contribution_pts"] > ch.loc[("home", "severity"), "contribution_pts"]
    assert ch.loc[("auto", "severity"), "contribution_pts"] > ch.loc[("auto", "frequency"), "contribution_pts"]
    assert ch.loc[("auto", "avg_earned_premium"), "contribution_pts"] < 0
    # auto premium: 3% trend plus about half of the 6% rate earned in 2025
    assert 0.045 < ch.loc[("auto", "avg_earned_premium"), "relative_change"] < 0.075
    seg = kpi.segments(con)
    home = seg[seg["line"] == "home"].pivot(index="province", columns="ay", values="frequency").drop(index="unknown")
    jump = home[2025] / home[2024]
    assert jump.idxmax() == HAIL[1] and 1.6 < jump[HAIL[1]] < 2.5
    assert (jump.drop(index=HAIL[1]) < 1.35).all()


def test_raw_query_overstates_the_loss_ratio(con, book):
    rvc = kpi.raw_vs_clean(con)
    assert (rvc["loss_ratio_gap_pts"] > 0).all()
    # a pandas recount: every exported claim row by its exported loss year, against the true book
    raw_years = pd.to_datetime(book.claims["loss_date"]).dt.year.value_counts()
    true_years = pd.to_datetime(book.true_claims["loss_date"]).dt.year.value_counts()
    for r in rvc.itertuples():
        assert r.claims_raw == raw_years[r.ay] and r.claims_clean == true_years[r.ay]
    assert rvc["claims_raw"].sum() > rvc["claims_clean"].sum()


def test_checks_table_lists_every_check(con, book):
    assert list(score_checks(run_checks(con), book.planted)["check_name"]) == list(CHECKS)


def test_committed_results_are_current(con):
    for path, text in outputs(con).items():
        assert path.read_text() == text, f"{path.name} is out of date: run python -m insurance_kpi"
