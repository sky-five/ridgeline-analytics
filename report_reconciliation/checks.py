"""Four checks per report, each comparing the mart (SQL) with what the source says (pandas or the catalog).

  row_count     the mart has one row per grain key the source produces, and no other keys
  totals        every measure's total matches the source, and no key's value differs by more than a cent
  refresh_age   each input was extracted within the report's SLA, and the mart was built after the newest extract
  lineage       every mart column is documented, and every source column it names exists
"""
from datetime import datetime, timedelta

import duckdb
import pandas as pd

from report_reconciliation.reports import BOOKKEEPING, REPORTS, Report

TOLERANCE = 0.01


def source_frames(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    names = [r[0] for r in con.execute("select table_name from information_schema.tables "
                                       "where table_schema = 'source'").fetchall()]
    return {n: con.execute(f"select * from source.{n}").df() for n in names}


def columns(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> list[str]:
    return [r[0] for r in con.execute("select column_name from information_schema.columns where table_schema = ? "
                                      "and table_name = ? order by ordinal_position", [schema, table]).fetchall()]


def keyed(df: pd.DataFrame, grain: tuple[str, ...]) -> pd.DataFrame:
    df = df.copy()
    for g in grain:
        df[g] = df[g].astype(str).str[:10] if g in ("month", "week_start") else df[g].astype(str)
    return df.set_index(list(grain))


def check_report(con: duckdb.DuckDBPyConnection, rep: Report, src: dict, now: datetime) -> dict:
    mart = keyed(con.execute(f"select * from {rep.mart}").df(), rep.grain)
    exp = keyed(rep.expected(src), rep.grain)
    only_mart, only_src = mart.index.difference(exp.index), exp.index.difference(mart.index)
    row_count = {"ok": len(mart) == len(exp) and not len(only_mart) and not len(only_src),
                 "mart_rows": len(mart), "source_rows": len(exp),
                 "keys_only_in_mart": len(only_mart), "keys_only_in_source": len(only_src)}

    shared = mart.index.intersection(exp.index)
    measures = {}
    for m in rep.measures:
        a, b = mart[m].fillna(0.0).astype(float), exp[m].astype(float)
        off = int(((a.loc[shared] - b.loc[shared]).abs() > TOLERANCE).sum())
        measures[m] = {"mart": round(float(a.sum()), 2), "source": round(float(b.sum()), 2),
                       "keys_differing": off}
    totals = {"ok": all(abs(v["mart"] - v["source"]) <= TOLERANCE and not v["keys_differing"]
                        for v in measures.values()), "measures": measures}

    log = dict(con.execute("select table_name, extracted_at from source.extract_log").fetchall())
    ages = {t: round((now - log[t]) / timedelta(hours=1), 1) for t in rep.inputs}
    built_from = mart["source_extracted_at"].min().to_pydatetime()
    stale = [t for t, h in ages.items() if h > rep.refresh_sla_hours]
    built_at = mart["built_at"].min().to_pydatetime()
    refresh = {"ok": not stale and built_from == min(log[t] for t in rep.inputs)
               and built_at >= max(log[t] for t in rep.inputs),
               "sla_hours": rep.refresh_sla_hours, "input_age_hours": ages, "stale_inputs": stale}

    mart_cols = columns(con, *rep.mart.split("."))
    undocumented = [c for c in mart_cols if c not in rep.lineage and c not in BOOKKEEPING]
    missing_in_mart = [c for c in rep.lineage if c not in mart_cols]
    refs = sorted({r.strip() for v in rep.lineage.values() for r in v.split(",")})
    bad_refs = [r for r in refs if r.split(".")[1] not in columns(con, "source", r.split(".")[0])]
    lineage = {"ok": not undocumented and not missing_in_mart and not bad_refs,
               "columns": len(mart_cols), "source_columns": len(refs), "undocumented": undocumented,
               "missing_in_mart": missing_in_mart, "unknown_source_columns": bad_refs}

    checks = {"row_count": row_count, "totals": totals, "refresh_age": refresh, "lineage": lineage}
    return {"report": rep.name, "title": rep.title, "mart": rep.mart,
            "ok": all(c["ok"] for c in checks.values()), "checks": checks}


def check_all(con: duckdb.DuckDBPyConnection, now: datetime) -> list[dict]:
    src = source_frames(con)
    return [check_report(con, rep, src, now) for rep in REPORTS]


def samples(con: duckdb.DuckDBPyConnection, rep: Report, n: int = 3) -> list[dict]:
    """Rows for the report owner to trace back to the source by hand: the largest by the report's last measure."""
    m = rep.measures[-1]
    keys = ", ".join(rep.grain)
    df = con.execute(f"select {keys}, {m} from {rep.mart} order by {m} desc, {keys} limit {n}").df()
    return [{**{g: str(r[g])[:10] for g in rep.grain}, m: round(float(r[m]), 2)} for _, r in df.iterrows()]
