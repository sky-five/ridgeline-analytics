"""Write dbt staging models and their tests from one YAML spec per source.

Each spec in staging_codegen/sources/<source>.yml lists the source's tables and, for each column,
its type and its tests. From that the generator writes, into dbt/models/staging/<source>/:

- stg_<source>__<table>.sql: select the columns, convert timestamps to UTC, cast numbers;
- _<source>__models.yml: the column tests (unique, not_null, accepted_values, relationships).

The source definitions (_<source>__sources.yml: schema, freshness, owners) stay hand-written;
the generator only checks that every table a spec names is declared there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "staging_codegen" / "sources"
STAGING = ROOT / "dbt" / "models" / "staging"

# column type -> how its select line is written (col = source column, name = output name)
RENDER = {
    "text": lambda col, name: col if col == name else f"{col} as {name}",
    "timestamp": lambda col, name: f"{{{{ to_utc('{col}') }}}} as {name}",
    "date": lambda col, name: f"cast({{{{ to_utc('{col}') }}}} as date) as {name}",
    "numeric": lambda col, name: f"cast({col} as {{{{ dbt.type_numeric() }}}}) as {name}",
    "int": lambda col, name: f"cast({col} as {{{{ dbt.type_int() }}}}) as {name}",
    # a number read from a JSON text column; the key is the output name
    "json_number": lambda col, name: f"{{{{ json_number('{col}', '{name}') }}}} as {name}",
}
SIMPLE_TESTS = {"unique", "not_null"}


class SpecError(ValueError):
    pass


@dataclass
class Column:
    name: str
    type: str = "text"
    source_column: str | None = None
    tests: list = field(default_factory=list)

    @property
    def select(self) -> str:
        return RENDER[self.type](self.source_column or self.name, self.name)


@dataclass
class Table:
    source: str
    table: str
    model: str
    description: str | None
    columns: list[Column]


def _column(raw: dict, where: str) -> Column:
    unknown = set(raw) - {"name", "type", "from", "tests"}
    if unknown:
        raise SpecError(f"{where}: unknown keys {sorted(unknown)}")
    if "name" not in raw:
        raise SpecError(f"{where}: a column needs a name")
    col = Column(raw["name"], raw.get("type", "text"), raw.get("from"), list(raw.get("tests") or []))
    where = f"{where}.{col.name}"
    if col.type not in RENDER:
        raise SpecError(f"{where}: unknown type {col.type!r} (use one of {', '.join(RENDER)})")
    if col.type == "json_number" and not col.source_column:
        raise SpecError(f"{where}: a json_number column needs `from:` (the JSON column)")
    for test in col.tests:
        if isinstance(test, str):
            if test not in SIMPLE_TESTS:
                raise SpecError(f"{where}: unknown test {test!r}")
        elif isinstance(test, dict) and len(test) == 1:
            (kind, arg), = test.items()
            if kind == "accepted_values" and isinstance(arg, list) and arg:
                continue
            if kind == "relationships" and isinstance(arg, str) and arg.count(".") == 1:
                continue
            raise SpecError(f"{where}: bad test {test!r}")
        else:
            raise SpecError(f"{where}: bad test {test!r}")
    return col


def load_spec(path: Path) -> list[Table]:
    spec = yaml.safe_load(path.read_text())
    source = spec.get("source")
    if source != path.stem:
        raise SpecError(f"{path.name}: `source: {source}` must match the file name")
    tables = []
    for t in spec.get("tables") or []:
        name = t["table"]
        where = f"{path.name}:{name}"
        columns = [_column(c, where) for c in t.get("columns") or []]
        if not columns:
            raise SpecError(f"{where}: no columns")
        names = [c.name for c in columns]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise SpecError(f"{where}: duplicate columns {dupes}")
        model = t.get("model", f"stg_{source}__{name}")
        if not model.startswith(f"stg_{source}__"):
            raise SpecError(f"{where}: model {model!r} must start with stg_{source}__")
        tables.append(Table(source, name, model, t.get("description"), columns))
    if not tables:
        raise SpecError(f"{path.name}: no tables")
    return tables


def render_sql(t: Table) -> str:
    selects = ",\n".join(f"    {c.select}" for c in t.columns)
    return (
        f"-- Generated from staging_codegen/sources/{t.source}.yml by python -m staging_codegen. Do not edit.\n"
        "with source as (\n"
        f"    select * from {{{{ source('{t.source}', '{t.table}') }}}}\n"
        ")\n\n"
        "select\n"
        f"{selects}\n"
        "from source\n"
    )


def _dbt_test(test):
    if isinstance(test, str):
        return test
    (kind, arg), = test.items()
    if kind == "accepted_values":
        return {"accepted_values": {"arguments": {"values": [str(v) for v in arg]}}}
    model, column = arg.split(".")
    return {"relationships": {"arguments": {"to": f"ref('{model}')", "field": column}}}


def render_tests(source: str, tables: list[Table]) -> str:
    models = []
    for t in tables:
        entry: dict = {"name": t.model}
        if t.description:
            entry["description"] = t.description
        tested = [{"name": c.name, "data_tests": [_dbt_test(x) for x in c.tests]} for c in t.columns if c.tests]
        if tested:
            entry["columns"] = tested
        models.append(entry)
    body = yaml.safe_dump({"version": 2, "models": models}, sort_keys=False, default_flow_style=None, width=120)
    return f"# Generated from staging_codegen/sources/{source}.yml by python -m staging_codegen. Do not edit.\n{body}"


def declared_tables(source_dir: Path, source: str) -> set[str]:
    path = source_dir / f"_{source}__sources.yml"
    if not path.exists():
        raise SpecError(f"{path.name} is missing: declare the source (schema, freshness) by hand first")
    doc = yaml.safe_load(path.read_text())
    return {t["name"] for s in doc["sources"] if s["name"] == source for t in s.get("tables") or []}


def build(specs: Path = SPECS, staging: Path = STAGING) -> dict[Path, str]:
    """Every file the specs produce: path -> content."""
    out: dict[Path, str] = {}
    for spec in sorted(specs.glob("*.yml")):
        tables = load_spec(spec)
        source_dir = staging / spec.stem
        missing = sorted({t.table for t in tables} - declared_tables(source_dir, spec.stem))
        if missing:
            raise SpecError(f"{spec.name}: tables {missing} are not in _{spec.stem}__sources.yml")
        for t in tables:
            out[source_dir / f"{t.model}.sql"] = render_sql(t)
        out[source_dir / f"_{spec.stem}__models.yml"] = render_tests(spec.stem, tables)
    return out


def problems(staging: Path, expected: dict[Path, str]) -> list[str]:
    """Generated files that are missing or edited by hand, and staging models no spec owns."""
    found = []
    for path, text in expected.items():
        if not path.exists():
            found.append(f"missing: {path.relative_to(staging)}")
        elif path.read_text() != text:
            found.append(f"edited by hand or out of date: {path.relative_to(staging)}")
    owned = set(expected)
    for path in sorted(staging.rglob("*")):
        is_model = path.suffix == ".sql" or path.name.endswith("__models.yml") or path.name == "_stg_models.yml"
        if path.is_file() and is_model and path not in owned:
            found.append(f"not from a spec: {path.relative_to(staging)}")
    return found


def write(expected: dict[Path, str]) -> list[Path]:
    changed = []
    for path, text in expected.items():
        if not path.exists() or path.read_text() != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            changed.append(path)
    return changed
