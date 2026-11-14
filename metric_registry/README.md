# Metric registry (simulated vehicle sales and incentives)

An AI analyst asked "what is our incentive spend per unit on electric vehicles?" can get three different
answers depending on whether it counts financing support, divides by every unit or only the incentivised
ones, and which table it starts from. This folder fixes the answer before anyone asks: one registry file
defines every metric once, a compiler turns it into the MetricFlow semantic layer and a glossary, and a lock
file stops a metric's number from changing without a version bump. Everything runs on seeded synthetic data;
no real manufacturer, dealer or sale is in it.

```bash
python -m metric_registry.compile           # registry.yml -> dbt/models/semantic/*.yml, GLOSSARY.md, registry.lock.json
python -m metric_registry                   # compile, simulate, load, dbt build, query the layer, write results/
python -m metric_registry --check           # fail if any generated file or result is out of date (CI)
pytest tests/metric_registry -q             # 19 tests, about 15 seconds
```

The warehouse goes to `warehouse/metric_registry.duckdb`; the main warehouse is not touched.

## The data

`simulate.py` writes 40 dealers in four regions selling twelve models in four segments (sedan, SUV, truck,
electric) from 2025-01-01 to the as-of date, 2026-06-30: 29,611 sales, each paid in cash, financed or
leased, and 32,721 incentive applications from 15 programs. Programs come in six types. Cash rebates,
loyalty cash, an electric-vehicle bonus and a quarter-end cash program come off the price; APR subvention
and lease support are paid to the lender and never show in the transaction price.

Two patterns are planted: electric vehicles carry several times the incentive per unit of any other
segment, and the last ten days of each quarter sell about 45% more vehicles a day with a quarter-end cash
program on top.

| Model | Grain |
|---|---|
| `dim_dealer`, `dim_vehicle`, `dim_program` | dealer, vehicle model, incentive program |
| `fct_sales` | vehicle sold, with its incentive and customer-cash totals and a quarter-end flag |
| `fct_incentive_applications` | program applied to a sale, with the sale's date, dealer and vehicle |

dbt tests check keys, relationships and accepted values, that every price is MSRP less the dealer discount
and the customer cash, and that program spend and the per-sale totals hold the same dollars.

## The registry

[`registry.yml`](registry.yml) is the only place a metric is defined. It holds:

- a **glossary** of eight terms (MSRP, customer cash, financing support, incentive spend, ...),
- the **semantic models**: each dbt model's entities, dimensions, time column and measures,
- **11 metrics**: 7 simple and 4 ratios (average transaction price, incentive per unit, incentive share of
  MSRP, incentive penetration), each with a label, a plain definition, an owner, a version and a changelog.

[`compile.py`](compile.py) validates it (every metric has an owner and a changelog entry for its version, a
ratio names two simple metrics, no unknown keys) and writes:

| File | What it is |
|---|---|
| [`dbt/models/semantic/_semantic_models.yml`](dbt/models/semantic/_semantic_models.yml) | MetricFlow semantic models and the time spine |
| [`dbt/models/semantic/_metrics.yml`](dbt/models/semantic/_metrics.yml) | MetricFlow metrics, with version, owner and fingerprint in `config.meta` |
| [`GLOSSARY.md`](GLOSSARY.md) | terms, every metric's definition and formula, the group-bys it allows, the changelog |
| [`registry.lock.json`](registry.lock.json) | each metric's version and fingerprint |

### Versions

A metric's fingerprint is a hash of what it computes: for a simple metric, its measure's model, time
column, aggregation and expression; for a ratio, its numerator's and denominator's fingerprints. When a
fingerprint changes and the version has not, the compiler stops and names the metric:

```
metric versions need attention:
incentive_spend: what it computes changed but it is still version 1; bump it to 2 and add a changelog line
incentive_per_unit: what it computes changed but it is still version 1; bump it to 2 and add a changelog line
incentive_share_of_msrp: what it computes changed but it is still version 1; bump it to 2 and add a changelog line
```

That is the output of changing one measure (incentive spend counting customer cash only): the two ratios
built on it are caught too, and nothing else is. A new metric must start at version 1, a version cannot go
down, and a metric cannot leave the registry quietly. Wording changes to a label or definition, and new
dimensions, need no bump. CI runs `python -m metric_registry --check`, so a hand edit to a generated file,
or a registry change nobody compiled, fails the build.

## What the first queries show (as of 2026-06-30)

| Segment | Units | Average transaction price | Incentive per unit | Share of MSRP | Penetration |
|---|---|---|---|---|---|
| Electric | 4,651 | $41,228 | $6,434 | 13.3% | 100% |
| Sedan | 7,032 | $27,632 | $1,231 | 4.2% | 70.1% |
| SUV | 10,511 | $35,458 | $1,436 | 3.8% | 80.3% |
| Truck | 7,417 | $44,871 | $1,196 | 2.5% | 61.1% |
| **All** | **29,611** | **$36,863** | **$2,112** | **5.3%** | **76.2%** |

Incentive per unit is $3,388 in the last ten days of a quarter against $1,886 the rest of the time. Incentive
spend is $62.6M, of which $45.6M is customer cash; program spend by type adds back to the same total. All the
numbers are in [results/summary.json](results/summary.json), every one from a MetricFlow query.

## Tests

`tests/metric_registry/` builds the warehouse once and recomputes all 11 metrics in pandas straight from
the raw simulated rows (by segment, and units and incentive per unit by quarter end and region). It checks
that MetricFlow serves exactly the registry's metrics, with the same versions, owners and group-bys; that
the committed generated files match the registry; that the version guard catches a changed measure (and
only the metrics that read it), a new metric not at version 1, a removed metric and a version going down,
and lets wording changes through; that invalid registries are rejected; that `explain` returns the SQL
behind a filtered answer; and that the committed results are current.

## Next

The second half puts a read-only MCP server over this semantic layer (list metrics, explain, query, with
the SQL MetricFlow ran returned as lineage) and scores an AI analyst on 20 golden questions through it.
