"""Write the dashboard tables (schema `reporting`) from the governed metrics.

The Evidence site reads only these tables and a few marts for row-level lists, so every KPI on the
site comes from the same MetricFlow definition the AI analyst uses.

    python scripts/export_reporting.py [--warehouse warehouse/ridgeline.duckdb] [--as-of YYYY-MM-DD]
"""
import argparse
import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KPIS = ["mrr", "paying_accounts", "new_mrr", "expansion_mrr", "churned_mrr", "net_new_mrr", "signups",
        "activation_rate", "free_to_paid_60d", "leads", "lead_close_rate", "speed_to_lead_median_min",
        "tickets", "measurement_redo_rate"]


def _rename_time(df: pd.DataFrame, grain: str, to: str) -> pd.DataFrame:
    df = df.rename(columns={f"metric_time__{grain}": to})
    df[to] = pd.to_datetime(df[to]).dt.date
    return df


def _plain(text: str) -> str:
    """The agent's reply as plain text: drop the trailing JSON block and markdown emphasis."""
    text = re.sub(r"```json.*?```", "", text, flags=re.S)
    return re.sub(r"\*\*|`", "", text).strip()


def export(warehouse: Path, as_of: date | None = None) -> dict[str, int]:
    """Write the reporting tables. With as_of, also grade that day's source batches (data_health/)."""
    os.environ["RIDGELINE_DUCKDB_PATH"] = str(warehouse)
    from semantic import list_metrics, query

    tables: dict[str, pd.DataFrame] = {
        "kpi_monthly": _rename_time(query(KPIS + ["ad_spend"], ["metric_time__month"]), "month", "month"),
        "kpi_weekly": _rename_time(query(KPIS, ["metric_time__week"]), "week", "week"),
        "channel_funnel": query(["signups", "activation_rate", "free_to_paid_60d"], ["account__channel"])
        .rename(columns={"account__channel": "channel"}),
        "channel_cac_monthly": _rename_time(
            query(["ad_spend", "paid_conversions", "cac"], ["metric_time__month", "channel_day__marketing_channel"]),
            "month", "month").rename(columns={"channel_day__marketing_channel": "channel"}),
        "headline": query(["nrr_12m", "measurement_redo_rate", "lead_close_rate", "free_to_paid_60d"]),
        "lead_speed": query(["leads", "lead_close_rate"], ["lead__speed_bucket"])
        .rename(columns={"lead__speed_bucket": "speed_bucket"}),
        "lead_sources": query(["leads", "lead_close_rate", "speed_to_lead_median_min"], ["lead__lead_source"])
        .rename(columns={"lead__lead_source": "lead_source"}),
        "redo_rates": query(["measurement_redo_rate"],
                            ["measurement_order__order_region", "measurement_order__roof_type"])
        .rename(columns={"measurement_order__order_region": "region", "measurement_order__roof_type": "roof_type"}),
        "metric_catalog": pd.DataFrame(
            [{"name": m.name, "label": m.label, "description": m.description,
              "dimensions": ", ".join(d for d in m.dimensions if not d.startswith("metric_time"))}
             for m in list_metrics()]),
    }

    run_results = ROOT / "dbt" / "target" / "run_results.json"
    if run_results.exists():
        results = json.loads(run_results.read_text())
        tables["dbt_run_results"] = pd.DataFrame([
            {"unique_id": r["unique_id"], "resource_type": r["unique_id"].split(".")[0], "status": r["status"],
             "execution_time_s": round(r["execution_time"], 2),
             "generated_at": results["metadata"]["generated_at"]}
            for r in results["results"]])

    # the AI analyst's latest recorded eval run, shown on the "Ask the data" page (no live LLM calls)
    evals = sorted((ROOT / "analyst" / "evals" / "results").glob("*.json"))
    if evals:
        run = json.loads(evals[-1].read_text(encoding="utf-8"))
        tables["analyst_run"] = pd.DataFrame([{k: run[k] for k in
                                               ("backend", "ran_at", "as_of", "correct", "grounded", "total")}])
        tables["analyst_answers"] = pd.DataFrame([
            {"n": i + 1, "id": r["id"], "question": r["question"], "type": r["type"],
             "reply": _plain(r["text"]), "truth": str(r["truth"]), "answer": str(r["answer"]),
             "correct": r["correct"], "grounded": r["grounded"], "models": ", ".join(r["cited_models"]),
             "metric": r.get("metric") or "", "sql": r.get("sql") or "",
             "tool_calls": " → ".join(r["tool_calls"]), "n_tool_calls": len(r["tool_calls"]),
             "seconds": r["seconds"], "cost_usd": r.get("cost_usd")}
            for i, r in enumerate(run["results"])])

    # the raw-vs-governed eval's recorded runs (semantic_eval/), on the "Raw tables vs governed metrics" page
    from semantic_eval.report import tables as eval_tables

    tables.update(eval_tables())

    # the simulated A/B test readout (experiments/), shown on the "A/B test" page
    exp_file = ROOT / "experiments" / "results" / "onboarding-checklist.json"
    if exp_file.exists():
        exp = json.loads(exp_file.read_text(encoding="utf-8"))
        res, bug, pk, rp = exp["result"], exp["srm_tracking_bug"], exp["peeking"], exp["replays"]
        tables["experiment_summary"] = pd.DataFrame([{
            **{k: exp["design"][k] for k in ("p_control", "planted_lift", "alpha", "power", "days",
                                             "sample_size_per_arm", "days_needed", "power_at_planned_size")},
            **{k: res[k] for k in ("n_control", "n_treatment", "rate_control", "rate_treatment", "diff",
                                   "ci_low", "ci_high", "p_value", "significant")},
            "srm_p": exp["srm"]["p_value"], "bug_n_treatment": bug["n_treatment"], "bug_srm_p": bug["p_value"],
            "bug_diff": bug["biased_result"]["diff"], "replay_runs": rp["runs"],
            "replay_significant": rp["significant"], "replay_ci_covers": rp["ci_covers_planted"],
            "aa_tests": pk["n_tests"], "fp_fixed": pk["false_positive_fixed"],
            "fp_peeking": pk["false_positive_peeking"]}])
        tables["experiment_looks"] = pd.DataFrame(exp["daily_looks"]).assign(planted=exp["design"]["planted_lift"])
        tables["experiment_funnel"] = pd.DataFrame(exp["funnel"])

    # customer health scoring (customer_health/), shown on the "Renewals at risk" page
    health_dir = ROOT / "customer_health" / "results"
    if (health_dir / "summary.json").exists() and (health_dir / "at_risk.csv").exists():
        hs = json.loads((health_dir / "summary.json").read_text(encoding="utf-8"))
        tables["health_compare"] = pd.DataFrame([
            {"method": label, "auc": hs[f"auc_{key}"], "churn_in_riskiest": hs[f"churn_in_riskiest_{short}"],
             "churners_caught": hs[f"churners_caught_{short}"], "churn_rate": hs["churn_rate"],
             "snapshots": hs["snapshots"], "test_accounts": hs["test_accounts"]}
            for label, key, short in (("Health score (hand-weighted)", "health_score", "score"),
                                      ("Logistic regression", "model", "model"))])
        tables["health_at_risk"] = pd.read_csv(health_dir / "at_risk.csv")

    # account reviews (account_reviews/): one templated page per large account, from the governed metrics
    from account_reviews.reviews import build as build_reviews

    tables.update(build_reviews(warehouse))

    # table health scorecard (data_health/): each source table's batch for the as-of day, on "Data health"
    if as_of is not None:
        from data_health.batches import arrivals
        from data_health.scorecard import WINDOW_DAYS, scorecard
        from pipelines.engine import TABLES

        tables["table_health"] = scorecard(arrivals(str(as_of), WINDOW_DAYS), str(as_of),
                                           {name: spec.primary_key for name, spec in TABLES.items()})

    with duckdb.connect(str(warehouse)) as con:  # same config as MetricFlow's in-process connection
        con.sql("create schema if not exists reporting")
        for name, df in tables.items():
            con.register("_df", df)
            con.sql(f"create or replace table reporting.{name} as select * from _df")
            con.unregister("_df")
        # pipeline freshness: last successful dlt load per source system
        systems = [r[0] for r in con.sql(
            "select schema_name from information_schema.schemata where schema_name like 'raw_%' "
            "and schema_name not like '%_staging'").fetchall()]
        union = " union all ".join(
            f"select '{s.removeprefix('raw_')}' as source_system, timezone('UTC', max(inserted_at)) as last_loaded_at, "
            f"count(*) as loads from {s}._dlt_loads where status = 0" for s in systems)
        # freshness is judged when the site is built (UTC), using the same thresholds as dbt source freshness
        con.sql(f"""
            create or replace table reporting.source_loads as
            with l as ({union}),
            now_utc as (select timezone('UTC', current_timestamp) as built_at)
            select l.*, n.built_at,
                   date_diff('hour', l.last_loaded_at, n.built_at) as hours_before_build,
                   case when date_diff('hour', l.last_loaded_at, n.built_at) > 72 then 'error'
                        when date_diff('hour', l.last_loaded_at, n.built_at) > 36 then 'warn'
                        else 'fresh' end as freshness
            from l cross join now_utc as n
        """)
    return {name: len(df) for name, df in tables.items()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--warehouse", type=Path, default=ROOT / "warehouse" / "ridgeline.duckdb")
    p.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1),
                   help="day whose source batches the table health scorecard grades (default: yesterday, UTC)")
    args = p.parse_args()
    for name, n in export(args.warehouse, args.as_of).items():
        print(f"{name:22}{n:>8,}")


if __name__ == "__main__":
    main()
