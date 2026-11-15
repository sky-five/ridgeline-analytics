"""Score the marts against what the simulator planted: does the reconciliation flag exactly the account-days
where a feed was wrong, does staging keep one copy of the repeated positions file, and which days leave P&L
unexplained."""
from pathlib import Path

import duckdb

from margin_risk.simulate import DUPLICATE_FILE_DATE


def reconciliation(con) -> dict:
    flagged = set(con.sql("select as_of_date, account_id from reconciliation_account_day where is_break").fetchall())
    out = {"account_days_flagged": len(flagged), "faults": {}}
    for fault in [r[0] for r in con.sql("select distinct fault from labels.feed_faults order by 1").fetchall()]:
        planted = set(con.sql(f"select as_of_date, account_id from labels.feed_faults where fault = '{fault}'")
                      .fetchall())
        out["faults"][fault] = {"planted": len(planted), "flagged": len(planted & flagged),
                                "days": sorted({d.isoformat() for d, _ in planted})}
    planted = set(con.sql("select as_of_date, account_id from labels.feed_faults").fetchall())
    out["missed"] = len(planted - flagged)
    out["false_alarms"] = len(flagged - planted)
    return out


def repeated_file(con) -> dict:
    d = DUPLICATE_FILE_DATE.isoformat()
    raw, staged, loads = con.sql(f"""
        select count(*), count(distinct (account_id, symbol)), count(distinct loaded_at)
        from raw_margin.positions where as_of_date = '{d}'""").fetchone()
    raw_mv = con.sql(f"""
        select sum(round(p.quantity * px.close, 2)) from raw_margin.positions as p
        join raw_margin.prices as px on p.symbol = px.symbol and p.as_of_date = px.price_date
        where p.as_of_date = '{d}'""").fetchone()[0]
    ledger_mv = con.sql(f"select sum(market_value) from raw_margin.ledger where as_of_date = '{d}'").fetchone()[0]
    return {"date": d, "loads": loads, "raw_rows": raw, "rows_kept": staged,
            "drift_if_counted_twice": round(raw_mv - ledger_mv, 2)}


def unexplained_pnl(con) -> list[dict]:
    rows = con.sql("""
        select as_of_date, count(*) as accounts, round(sum(unexplained), 2) as unexplained
        from fct_account_pnl_day where abs(unexplained) > 0.05 group by as_of_date order by as_of_date""").df()
    return [{"date": r.as_of_date.date().isoformat(), "accounts": int(r.accounts), "unexplained": r.unexplained}
            for r in rows.itertuples()]


def run(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        return {"checks": {"reconciliation": reconciliation(con), "repeated_positions_file": repeated_file(con),
                           "unexplained_pnl_days": unexplained_pnl(con)}}
