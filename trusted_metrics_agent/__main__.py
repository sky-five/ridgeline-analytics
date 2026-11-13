"""python -m trusted_metrics_agent [--db PATH]: load the exports, build the dbt project, print the catalog."""
import argparse
from pathlib import Path

from trusted_metrics_agent.load import DEFAULT_DB, dbt_build, load
from trusted_metrics_agent.metrics import Catalog, MetricStore

p = argparse.ArgumentParser(prog="python -m trusted_metrics_agent")
p.add_argument("--db", type=Path, default=DEFAULT_DB)
args = p.parse_args()

for table, n in load(args.db).items():
    print(f"{table:28}{n:>8,}")
dbt_build(args.db)
store = MetricStore.open("hr_partner", args.db)
last = store.last_month
print(f"\ngoverned metrics, {last}:")
for name in Catalog.load().metrics:
    (row,) = store.query_metric(name, last)["rows"]
    print(f"  {name:24}{row['value']:>14,}")
