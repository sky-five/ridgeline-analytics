"""The staging generator: committed staging files match their specs, each column type renders the right SQL,
hand edits and orphan models are caught, bad specs are refused, and a new source goes from raw DuckDB tables
to a drafted spec to staging SQL that runs."""
import shutil
from pathlib import Path

import duckdb
import jinja2
import pytest
import yaml

from staging_codegen.draft import draft
from staging_codegen.generate import (
    STAGING,
    Column,
    SpecError,
    Table,
    build,
    load_spec,
    problems,
    render_tests,
    write,
)

SOURCES_YML = """version: 2
sources:
  - name: {source}
    schema: raw_{source}
    tables:
{tables}
"""


def sources_yml(source, tables):
    return SOURCES_YML.format(source=source, tables="\n".join(f"      - name: {t}" for t in tables))


def run_sql(con, sql):
    """Render a staging model the way dbt does on DuckDB (macros stubbed) and run it."""
    env = jinja2.Environment()
    rendered = env.from_string(sql).render(
        source=lambda s, t: f"raw_{s}.{t}",
        to_utc=lambda c: f"timezone('UTC', {c})",
        json_number=lambda c, k: f"cast(json_extract_string({c}, '$.{k}') as double)",
        dbt={"type_numeric": lambda: "decimal(28, 6)", "type_int": lambda: "integer"},
    )
    return con.execute(rendered)


@pytest.fixture
def new_source(tmp_path):
    specs, staging = tmp_path / "specs", tmp_path / "staging"
    specs.mkdir()
    (staging / "billing").mkdir(parents=True)
    (staging / "billing" / "_billing__sources.yml").write_text(sources_yml("billing", ["invoices"]))
    (specs / "billing.yml").write_text(
        """source: billing
tables:
  - table: invoices
    description: One row per invoice.
    columns:
      - {name: invoice_id, tests: [unique, not_null]}
      - {name: account_id, tests: [{relationships: stg_app_db__accounts.account_id}]}
      - {name: plan_code, from: plan, tests: [{accepted_values: [1, basic, pro]}]}
      - {name: issued_at, type: timestamp}
      - {name: due_date, type: date}
      - {name: amount_usd, type: numeric}
      - {name: lines, type: int}
      - {name: tax_usd, type: json_number, from: details}
"""
    )
    return specs, staging


# --- the committed project ---


def test_committed_staging_files_match_their_specs():
    expected = build()
    assert problems(STAGING, expected) == []
    assert len(list(Path(STAGING.parent.parent.parent / "staging_codegen" / "sources").glob("*.yml"))) == 6
    assert sum(p.suffix == ".sql" for p in expected) == 11
    assert len(expected) == 17


def test_every_staging_test_is_generated():
    tests = {}
    for path, text in build().items():
        if path.suffix == ".yml":
            for model in yaml.safe_load(text)["models"]:
                for col in model.get("columns", []):
                    for t in col["data_tests"]:
                        kind = t if isinstance(t, str) else next(iter(t))
                        tests[kind] = tests.get(kind, 0) + 1
    assert tests == {"unique": 11, "not_null": 11, "accepted_values": 18, "relationships": 6}
    assert sum(tests.values()) == 46  # the same 46 staging tests dbt parsed before the generator


def test_generated_files_say_where_they_come_from():
    for path, text in build().items():
        marker = "--" if path.suffix == ".sql" else "#"
        assert text.splitlines()[0].startswith(f"{marker} Generated from staging_codegen/")


# --- rendering ---


@pytest.mark.parametrize(
    "column, line",
    [
        (Column("rep"), "rep"),
        (Column("lead_source", source_column="source"), "source as lead_source"),
        (Column("signup_at", "timestamp"), "{{ to_utc('signup_at') }} as signup_at"),
        (Column("spend_date", "date"), "cast({{ to_utc('spend_date') }} as date) as spend_date"),
        (Column("mrr_usd", "numeric"), "cast(mrr_usd as {{ dbt.type_numeric() }}) as mrr_usd"),
        (Column("clicks", "int"), "cast(clicks as {{ dbt.type_int() }}) as clicks"),
        (Column("value_usd", "json_number", "properties"), "{{ json_number('properties', 'value_usd') }} as value_usd"),
    ],
)
def test_each_column_type_renders_its_select_line(column, line):
    assert column.select == line


def test_tests_render_in_dbt_form_with_values_as_text():
    t = Table("s", "t", "stg_s__t", None, [
        Column("id", tests=["unique", "not_null"]),
        Column("size", tests=[{"accepted_values": [1, "2-5"]}]),
        Column("account_id", tests=[{"relationships": "stg_app_db__accounts.account_id"}]),
        Column("note"),
    ])
    (model,) = yaml.safe_load(render_tests("s", [t]))["models"]
    assert "description" not in model
    assert [c["name"] for c in model["columns"]] == ["id", "size", "account_id"]
    assert model["columns"][1]["data_tests"] == [{"accepted_values": {"arguments": {"values": ["1", "2-5"]}}}]
    assert model["columns"][2]["data_tests"] == [
        {"relationships": {"arguments": {"to": "ref('stg_app_db__accounts')", "field": "account_id"}}}
    ]


# --- drift ---


def test_hand_edits_missing_files_and_orphan_models_are_caught(tmp_path):
    staging = tmp_path / "staging"
    shutil.copytree(STAGING, staging)
    expected = build(staging=staging)
    assert problems(staging, expected) == []

    sql = staging / "crm" / "stg_crm__calls.sql"
    sql.write_text(sql.read_text().replace("    rep,\n", "    rep as rep_name,\n"))
    (staging / "support" / "_support__models.yml").unlink()
    (staging / "ads" / "stg_ads__ad_clicks.sql").write_text("select 1 as x\n")

    assert problems(staging, expected) == [
        "edited by hand or out of date: crm/stg_crm__calls.sql",
        "missing: support/_support__models.yml",
        "not from a spec: ads/stg_ads__ad_clicks.sql",
    ]
    assert len(write(expected)) == 2
    assert problems(staging, expected) == ["not from a spec: ads/stg_ads__ad_clicks.sql"]


# --- bad specs ---


@pytest.mark.parametrize(
    "column, message",
    [
        ("{name: x, type: money}", "unknown type 'money'"),
        ("{name: x, type: json_number}", "needs `from:`"),
        ("{name: x, tests: [unique_combo]}", "unknown test 'unique_combo'"),
        ("{name: x, tests: [{accepted_values: []}]}", "bad test"),
        ("{name: x, tests: [{relationships: stg_app_db__accounts}]}", "bad test"),
        ("{name: x, colour: red}", "unknown keys ['colour']"),
    ],
)
def test_bad_columns_are_refused(tmp_path, column, message):
    spec = tmp_path / "billing.yml"
    spec.write_text(f"source: billing\ntables:\n  - table: invoices\n    columns:\n      - {column}\n")
    with pytest.raises(SpecError, match=message.replace("[", r"\[").replace("(", r"\(")):
        load_spec(spec)


def test_bad_specs_are_refused(new_source):
    specs, staging = new_source
    spec = specs / "billing.yml"
    good = spec.read_text()

    spec.write_text(good.replace("source: billing", "source: invoicing"))
    with pytest.raises(SpecError, match="must match the file name"):
        build(specs, staging)

    spec.write_text(good + "      - {name: lines}\n")
    with pytest.raises(SpecError, match=r"duplicate columns \['lines'\]"):
        build(specs, staging)

    spec.write_text(good.replace("    description:", "    model: stg_other__invoices\n    description:"))
    with pytest.raises(SpecError, match="must start with stg_billing__"):
        build(specs, staging)

    spec.write_text(good.replace("table: invoices", "table: payments"))
    with pytest.raises(SpecError, match=r"tables \['payments'\] are not in _billing__sources.yml"):
        build(specs, staging)

    spec.write_text(good)
    (staging / "billing" / "_billing__sources.yml").unlink()
    with pytest.raises(SpecError, match="declare the source"):
        build(specs, staging)


# --- a new source end to end ---


def test_a_new_source_spec_writes_sql_that_runs_and_casts(new_source):
    specs, staging = new_source
    written = write(build(specs, staging))
    assert sorted(p.name for p in written) == ["_billing__models.yml", "stg_billing__invoices.sql"]
    model = yaml.safe_load((staging / "billing" / "_billing__models.yml").read_text())["models"][0]
    assert model["description"] == "One row per invoice."

    con = duckdb.connect()
    con.execute("set TimeZone = 'America/Toronto'")
    con.execute("create schema raw_billing")
    con.execute(
        """create table raw_billing.invoices as select
             'inv_1' as invoice_id, 'acc_1' as account_id, 'pro' as plan,
             timestamptz '2026-03-01 23:30:00-05' as issued_at, timestamptz '2026-03-31 12:00:00+00' as due_date,
             '120.50' as amount_usd, '3' as lines, '{"tax_usd": 15.67}' as details"""
    )
    sql = (staging / "billing" / "stg_billing__invoices.sql").read_text()
    rel = run_sql(con, sql)
    assert [d[0] for d in rel.description] == [
        "invoice_id", "account_id", "plan_code", "issued_at", "due_date", "amount_usd", "lines", "tax_usd",
    ]
    row = rel.fetchone()
    assert str(row[3]) == "2026-03-02 04:30:00"  # converted to UTC, not the session's local time
    assert str(row[4]) == "2026-03-31"
    assert float(row[5]) == 120.5 and row[6] == 3 and row[7] == pytest.approx(15.67)


def test_draft_starts_a_spec_from_raw_tables(new_source):
    specs, staging = new_source
    con = duckdb.connect()
    con.execute("create schema raw_billing")
    con.execute(
        """create table raw_billing.invoices (
             invoice_id varchar, account_id varchar, issued_at timestamptz, due_date date,
             amount_usd decimal(12, 2), lines bigint, note varchar, _dlt_load_id varchar, _dlt_id varchar)"""
    )
    con.execute("create table raw_billing._dlt_loads (load_id varchar, status integer)")

    text = draft(con, "billing")
    assert "_dlt" not in text
    (specs / "billing.yml").write_text(text)
    (table,) = load_spec(specs / "billing.yml")
    assert [(c.name, c.type, c.tests) for c in table.columns] == [
        ("invoice_id", "text", ["unique", "not_null"]),
        ("account_id", "text", []),
        ("issued_at", "timestamp", []),
        ("due_date", "date", []),
        ("amount_usd", "numeric", []),
        ("lines", "int", []),
        ("note", "text", []),
    ]
    write(build(specs, staging))
    assert run_sql(con, (staging / "billing" / "stg_billing__invoices.sql").read_text()).fetchall() == []


def test_draft_refuses_an_empty_schema():
    with pytest.raises(SystemExit, match="no tables in schema raw_nothing"):
        draft(duckdb.connect(), "nothing")
