# Staging generator

dbt staging models are mostly the same select written again for every table: list the columns, convert
timestamps to UTC, cast money and counts, rename the odd column, then repeat the column names in a YAML file
to attach `unique`, `not_null`, `accepted_values` and `relationships` tests. Copying that by hand is where
typos and missing tests come from. Here each source has one spec file, and the generator writes the models
and their tests from it.

```bash
python -m staging_codegen                    # specs -> dbt/models/staging/<source>/*.sql and _<source>__models.yml
python -m staging_codegen --check            # fail if a generated file is missing, edited by hand or out of date (CI)
python -m staging_codegen --draft billing    # print a starting spec from raw_billing's tables in the warehouse
pytest tests/staging_codegen -q              # 22 tests, under a second
```

## A spec

```yaml
# staging_codegen/sources/crm.yml
source: crm
tables:
  - table: crm_calls
    model: stg_crm__calls          # optional; default stg_<source>__<table>
    columns:
      - {name: call_id, tests: [unique, not_null]}
      - {name: account_id}
      - {name: rep}
      - {name: called_at, type: timestamp}
      - {name: outcome, tests: [{accepted_values: [connected, voicemail, no_answer, demo_booked]}]}
      - {name: duration_s, type: int}
```

| `type` | Select line |
|---|---|
| `text` (default) | `rep` (or `source as lead_source` with `from: source`) |
| `timestamp` | `{{ to_utc('called_at') }} as called_at` |
| `date` | `cast({{ to_utc('spend_date') }} as date) as spend_date` |
| `numeric` | `cast(amount_usd as {{ dbt.type_numeric() }}) as amount_usd` |
| `int` | `cast(duration_s as {{ dbt.type_int() }}) as duration_s` |
| `json_number` | `{{ json_number('properties', 'value_usd') }} as value_usd` (needs `from:`) |

Tests are `unique`, `not_null`, `{accepted_values: [...]}` and `{relationships: <model>.<column>}`. The
`to_utc` and `json_number` macros already switch between DuckDB and Snowflake, so one spec serves both.

## What it owns and what it doesn't

- **Owns:** every `stg_*.sql` file and one `_<source>__models.yml` per source. Each starts with a
  "generated, do not edit" line.
- **Doesn't own:** `_<source>__sources.yml` (schema, freshness, owners). Those stay hand-written; the
  generator only refuses a spec whose table is not declared there.
- `--check` reports three kinds of drift: a generated file that is missing, one that was edited by hand,
  and a staging model or tests file that no spec produced.
- Unknown column types, unknown tests, a `json_number` without `from:`, duplicate columns, a model name
  outside `stg_<source>__` and a spec named differently from its source are refused before anything is written.

## Moving the existing models over

The six sources (11 staging models) were hand-written before this folder existed. Their specs were written
to reproduce them, and the result was checked:

- the generated SQL is the old SQL line for line, apart from the new header line;
- the old single `_stg_models.yml` became one generated tests file per source, and `dbt parse` lists the
  same 91 test ids before and after (46 of them on staging models);
- `dbt build` on the warehouse as of 2026-11-16 passes all 133 nodes.

## Adding a source

1. Load it with a dlt pipeline into `raw_<source>` and declare it in `dbt/models/staging/<source>/_<source>__sources.yml`.
2. `python -m staging_codegen --draft <source> > staging_codegen/sources/<source>.yml`. The draft maps
   warehouse types to spec types, skips dlt's own columns and tables, and puts `unique` + `not_null` on each
   table's first `*_id` column.
3. Add renames, accepted values and relationships by hand, then run `python -m staging_codegen`.

A test does this end to end on a made-up `billing` source: raw DuckDB tables, a drafted spec, generated
SQL, and the SQL run on DuckDB with a non-UTC session time zone to show timestamps come out in UTC.

All data in this project is synthetic.
