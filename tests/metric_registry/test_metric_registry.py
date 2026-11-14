"""Builds the vehicle-sales warehouse once (simulate + load + dbt build, about 10 s) and checks the simulator's
planted patterns, the registry compiler and its version guard, every registry metric from MetricFlow against
an independent pandas computation from the raw rows, and the committed results."""
import copy

import pandas as pd
import pytest

from metric_registry import compile as registry
from metric_registry import metrics
from metric_registry.load import dbt_build, load
from metric_registry.run import SUMMARY, summary, to_json
from metric_registry.simulate import CASH_TYPES, is_quarter_end, simulate


@pytest.fixture(scope="module")
def net():
    return simulate()


@pytest.fixture(scope="module")
def db(tmp_path_factory, net):
    path = tmp_path_factory.mktemp("metric_registry") / "metric_registry.duckdb"
    load(path, net)
    dbt_build(path)
    return path


@pytest.fixture(scope="module")
def sales(net):
    """One row per sale with its segment, region and incentive totals, computed from the raw tables only."""
    inc = net.incentives.merge(net.programs[["program_id", "program_type"]], on="program_id")
    inc["cash"] = inc["amount"].where(inc["program_type"].isin(CASH_TYPES), 0.0)
    per_sale = inc.groupby("sale_id").agg(incentive=("amount", "sum"), cash=("cash", "sum"))
    s = net.sales.merge(net.vehicles[["vehicle_id", "segment"]], on="vehicle_id")
    s = s.merge(net.dealers, on="dealer_id").merge(per_sale, on="sale_id", how="left")
    s[["incentive", "cash"]] = s[["incentive", "cash"]].fillna(0.0)
    s["quarter_end"] = s["sale_date"].dt.date.map(is_quarter_end)
    return s


@pytest.fixture()
def reg():
    return registry.load_registry()


# --- the simulator ---------------------------------------------------------------------------


def test_simulation_is_seeded(net):
    again = simulate()
    pd.testing.assert_frame_equal(net.sales, again.sales)
    pd.testing.assert_frame_equal(net.incentives, again.incentives)


def test_price_is_msrp_less_discount_and_customer_cash(sales):
    gap = sales["msrp"] - sales["dealer_discount"] - sales["cash"] - sales["transaction_price"]
    assert gap.abs().max() < 0.01


def test_planted_ev_incentives_and_quarter_end_push(sales):
    per_unit = sales.groupby("segment")["incentive"].mean()
    assert per_unit["ev"] > 3 * per_unit.drop("ev").max()
    daily = sales.groupby(["sale_date", "quarter_end"]).size().groupby("quarter_end").mean()
    assert daily[True] > 1.3 * daily[False]
    per_unit_qe = sales.groupby("quarter_end")["incentive"].mean()
    assert per_unit_qe[True] > 1.5 * per_unit_qe[False]


# --- the registry compiler -------------------------------------------------------------------


def test_committed_generated_files_match_the_registry(reg):
    for path, text in registry.compile_registry(reg).items():
        assert path.read_text() == text, f"{path.name} is stale: run python -m metric_registry.compile"
    assert registry.check_versions(reg, registry.read_lock()) == []


def test_changing_a_measure_without_a_bump_is_refused(reg):
    lock = registry.read_lock()
    changed = copy.deepcopy(reg)
    changed["semantic_models"]["sales"]["measures"]["incentive_amount"]["expr"] = "customer_cash_amount"
    problems = registry.check_versions(changed, lock)
    # every metric that reads the measure, directly or through a ratio, must move, and only those
    flagged = sorted(p.split(":")[0] for p in problems)
    assert flagged == ["incentive_per_unit", "incentive_share_of_msrp", "incentive_spend"]
    for name in flagged:
        changed["metrics"][name]["version"] += 1
        changed["metrics"][name]["changelog"][changed["metrics"][name]["version"]] = "Spend is customer cash only."
    assert registry.check_versions(changed, lock) == []
    registry.validate(changed)


def test_wording_changes_need_no_bump(reg):
    changed = copy.deepcopy(reg)
    changed["metrics"]["revenue"]["definition"] = "Sum of transaction prices."
    changed["semantic_models"]["sales"]["dimensions"].append("dealer_id")
    assert registry.check_versions(changed, registry.read_lock()) == []


def test_new_removed_and_downgraded_metrics_are_caught(reg):
    lock = registry.read_lock()
    changed = copy.deepcopy(reg)
    changed["metrics"]["dealer_discount"] = {
        "label": "Dealer discount", "definition": "Dealer discount summed.", "owner": "Finance", "version": 2,
        "changelog": {2: "x"}, "measure": "sales.msrp_amount"}
    del changed["metrics"]["customer_cash"]
    lock = lock | {"revenue": {**lock["revenue"], "version": 3}}
    problems = "\n".join(registry.check_versions(changed, lock))
    assert "dealer_discount: a new metric starts at version 1" in problems
    assert "customer_cash: removed from the registry" in problems
    assert "revenue: version went down from 3 to 1" in problems


@pytest.mark.parametrize("edit, message", [
    (lambda r: r["metrics"]["revenue"].pop("owner"), "metric revenue: missing owner"),
    (lambda r: r["metrics"]["revenue"].update(version=2), "changelog has no entry for version 2"),
    (lambda r: r["metrics"]["revenue"].update(measure="sales.nope"), "no measure sales.nope"),
    (lambda r: r["metrics"]["incentive_per_unit"].update(numerator="average_transaction_price"),
     "numerator must name a simple metric"),
    (lambda r: r["metrics"]["revenue"].update(filter="x"), "unknown keys ['filter']"),
])
def test_invalid_registry_is_rejected(reg, edit, message):
    edit(reg)
    with pytest.raises(registry.RegistryError, match=message.replace("[", r"\[").replace("]", r"\]")):
        registry.validate(reg)


def test_every_metric_is_in_the_glossary_with_its_version(reg):
    text = registry.GLOSSARY.read_text()
    for name, m in reg["metrics"].items():
        assert f"| `{name}` ({m['label']}) |" in text and f"`{name}` v{m['version']}:" in text
    for term in reg["glossary"]:
        assert f"| {term} |" in text


# --- the semantic layer ----------------------------------------------------------------------


def test_metricflow_serves_exactly_the_registry(db, reg):
    served = {m["name"]: m for m in metrics.list_metrics(db)}
    assert set(served) == set(reg["metrics"])
    for name, m in reg["metrics"].items():
        assert served[name]["version"] == m["version"] and served[name]["owner"] == m["owner"]
        mf_dims = {d for d in served[name]["dimensions"] if not d.startswith("metric_time") and "_date" not in d}
        assert mf_dims == set(registry.dimensions(reg, name)) - {"metric_time"}, name


def test_every_metric_matches_pandas_by_segment(db, sales):
    g = sales.groupby("segment")
    expected = pd.DataFrame({
        "units_sold": g.size(),
        "msrp_value": g["msrp"].sum(),
        "revenue": g["transaction_price"].sum(),
        "incentive_spend": g["incentive"].sum(),
        "customer_cash": g["cash"].sum(),
        "incentivised_units": g["incentive"].apply(lambda x: (x > 0).sum()),
    })
    expected["average_transaction_price"] = expected["revenue"] / expected["units_sold"]
    expected["incentive_per_unit"] = expected["incentive_spend"] / expected["units_sold"]
    expected["incentive_share_of_msrp"] = expected["incentive_spend"] / expected["msrp_value"]
    expected["incentive_penetration"] = expected["incentivised_units"] / expected["units_sold"]
    got = metrics.query(list(expected.columns), ["vehicle__segment"], db=db).set_index("vehicle__segment")
    pd.testing.assert_frame_equal(got[expected.columns].astype(float), expected.astype(float),
                                  check_names=False, rtol=1e-9)


def test_quarter_end_and_region_slices_match_pandas(db, sales):
    got = metrics.query(["units_sold", "incentive_per_unit"], ["sale__is_quarter_end", "dealer__region"], db=db)
    exp = sales.groupby(["quarter_end", "region"]).agg(units_sold=("sale_id", "size"),
                                                        incentive_per_unit=("incentive", "mean")).reset_index()
    got = got.sort_values(["sale__is_quarter_end", "dealer__region"]).reset_index(drop=True)
    exp = exp.sort_values(["quarter_end", "region"]).reset_index(drop=True)
    assert list(got["units_sold"]) == list(exp["units_sold"])
    assert (got["incentive_per_unit"] - exp["incentive_per_unit"]).abs().max() < 1e-6


def test_program_spend_adds_up_to_incentive_spend(db, net):
    by_type = metrics.query(["program_spend"], ["program__program_type"], db=db)
    typed = net.incentives.merge(net.programs[["program_id", "program_type"]], on="program_id")
    exp = typed.groupby("program_type")["amount"].sum()
    assert dict(zip(by_type["program__program_type"], by_type["program_spend"].astype(float), strict=True)) == \
        pytest.approx(exp.to_dict())
    total = metrics.query(["program_spend", "incentive_spend"], db=db).iloc[0]
    assert float(total["program_spend"]) == pytest.approx(float(total["incentive_spend"]))


def test_explain_returns_the_sql_behind_an_answer(db):
    sql = metrics.explain(["incentive_per_unit"], ["vehicle__segment"],
                          ["{{ Dimension('dealer__region') }} = 'west'"], db=db)
    assert "fct_sales" in sql and "dim_vehicle" in sql and "west" in sql


def test_committed_summary_is_current(db, net):
    assert SUMMARY.read_text() == to_json(summary(db, net)), "run python -m metric_registry"
