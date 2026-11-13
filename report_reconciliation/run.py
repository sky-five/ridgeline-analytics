"""Build the reports from the simulated sources, check them, and plant each fault in turn."""
import duckdb

from report_reconciliation import simulate
from report_reconciliation.build import FAULTS, build
from report_reconciliation.checks import check_all, samples
from report_reconciliation.reports import REPORTS


def build_and_check(fault: str | None = None, con: duckdb.DuckDBPyConnection | None = None):
    con = con or duckdb.connect()
    simulate.load(con, simulate.frames())
    build(con, simulate.BUILT_AT, fault)
    return con, check_all(con, simulate.AS_OF)


def failed(results: list[dict]) -> dict[str, list[str]]:
    return {r["report"]: [k for k, c in r["checks"].items() if not c["ok"]] for r in results}


def run(con: duckdb.DuckDBPyConnection | None = None) -> dict:
    con, results = build_and_check(None, con)
    src = {n: con.execute(f"select count(*) from source.{n}").fetchone()[0] for n in simulate.SOURCE_TABLES}
    status = dict(con.execute("select status, count(*) from source.timesheets group by 1 order by 1").fetchall())
    return {
        "as_of": str(simulate.AS_OF), "built_at": str(simulate.BUILT_AT),
        "source_rows": src, "timesheet_status": status,
        "reports": results,
        "samples": {rep.name: samples(con, rep) for rep in REPORTS},
        "planted_faults": {f: failed(build_and_check(f)[1]) for f in FAULTS},
    }
