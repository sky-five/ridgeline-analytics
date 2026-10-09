"""Write the dashboard tables (schema `reporting`) from the governed metrics.

The Evidence site reads only these tables and a few marts for row-level lists, so every KPI on the
site comes from the same MetricFlow definition the AI analyst uses.

    python scripts/export_reporting.py [--warehouse warehouse/ridgeline.duckdb]
"""
import argparse
import json
import os
import sys
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


def export(warehouse: Path) -> dict[str, int]:
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
    for name, n in export(p.parse_args().warehouse).items():
        print(f"{name:22}{n:>8,}")


if __name__ == "__main__":
    main()
