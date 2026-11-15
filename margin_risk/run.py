"""Write the margin book results: results/summary.json, results/firm_daily.csv and the findings note
results/findings.md. Every number comes from the dbt marts or check.py."""
import json
from pathlib import Path

import duckdb

from margin_risk import check
from margin_risk.simulate import AS_OF, FIRST_DAY, SHOCK_DAYS, SHOCK_SECTOR

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
FIRM_DAILY = RESULTS / "firm_daily.csv"
FINDINGS = RESULTS / "findings.md"
SHOCK_FROM, SHOCK_TO = SHOCK_DAYS[0].date(), SHOCK_DAYS[-1].date()


def _one(con, sql: str) -> dict:
    df = con.sql(sql).df()
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in df.to_dict("records")[0].items()}


def summary(db: Path) -> dict:
    a = AS_OF.isoformat()
    with duckdb.connect(str(db), read_only=True) as con:
        book = _one(con, """
            select (select count(*) from raw_margin.accounts) as accounts,
                   (select count(*) filter (where margin_enabled) from raw_margin.accounts) as margin_accounts,
                   (select count(*) from fct_position_day) as position_rows,
                   (select count(*) from daily_firm_summary) as weekdays""")
        last = _one(con, f"""
            select borrowers, round(market_value, 2) as market_value, round(loan, 2) as loan,
                   round(equity, 2) as equity, collateral_coverage, margin_utilisation, concentrated_borrowers,
                   accounts_in_call
            from daily_firm_summary where as_of_date = '{a}'""")
        top = _one(con, f"""
            select symbol, sector, share_of_borrower_value, borrowers_holding, borrowers_concentrated
            from concentration_by_symbol where as_of_date = '{a}' order by share_of_borrower_value desc limit 1""")
        sector = _one(con, f"""
            select sum(share_of_borrower_value) as share, sum(borrowers_concentrated) as concentrated
            from concentration_by_symbol where as_of_date = '{a}' and sector = '{SHOCK_SECTOR}'""")
        shock = _one(con, f"""
            with p as (
                select symbol,
                       arg_max(close, price_date) filter (where price_date < '{SHOCK_FROM}') as before,
                       arg_max(close, price_date) filter (where price_date <= '{SHOCK_TO}') as after
                from stg_margin__prices where symbol in (select symbol from raw_margin.securities
                                                         where sector = '{SHOCK_SECTOR}') group by symbol)
            select round(min(after / before - 1), 4) as worst_drop, round(max(after / before - 1), 4) as mildest_drop,
                   (select round(sum(market_pnl), 2) from daily_firm_summary
                    where as_of_date between '{SHOCK_FROM}' and '{SHOCK_TO}') as market_pnl_week
            from p""")
        calls = con.sql("""
            select count(*) as calls,
                   count(*) filter (where starts_on_break) as on_a_break,
                   count(*) filter (where not starts_on_break and was_concentrated) as concentrated,
                   count(*) filter (where not starts_on_break and top_symbol like 'SEM%') as top_in_semiconductors,
                   round(sum(deficit_at_call) filter (where not starts_on_break), 2) as deficit_at_call,
                   round(median(weekdays_in_call) filter (where not starts_on_break), 1) as median_weekdays
            from margin_calls""").df().iloc[0].to_dict()
        resolution = dict(con.sql("""select resolution, count(*) from margin_calls where not starts_on_break
                                     group by 1 order by 1""").fetchall())
        shock_calls = con.sql(f"""select count(*) from margin_calls where not starts_on_break
                                  and call_date between '{SHOCK_FROM}' and date '{SHOCK_TO}' + 7""").fetchone()[0]
        worst_day = _one(con, """select as_of_date, round(market_pnl, 2) as market_pnl from daily_firm_summary
                                 where market_pnl is not null order by market_pnl limit 1""")
        pnl = _one(con, """select round(sum(market_pnl), 2) as market_pnl, round(sum(interest_income), 2) as
                           interest_income, round(sum(deposits), 2) as deposits from daily_firm_summary""")
        flagged = [{"date": r[0].isoformat(), "market_value_drift": r[1], "cash_drift": r[2], "accounts_broken": r[3]}
                   for r in con.sql("""select as_of_date, market_value_drift, cash_drift, accounts_broken
                                       from reconciliation_daily where is_flagged order by 1""").fetchall()]
    calls = {k: (int(v) if k not in ("deficit_at_call", "median_weekdays") else float(v)) for k, v in calls.items()}
    return {"first_day": FIRST_DAY.isoformat(), "as_of": a, "book": book, "last_day": last,
            "largest_holding": top, "shock_sector": {"sector": SHOCK_SECTOR, **sector},
            "shock": {"from": SHOCK_FROM.isoformat(), "to": SHOCK_TO.isoformat(), **shock,
                      "real_calls_within_a_week": int(shock_calls)},
            "margin_calls": {**calls, "resolution": resolution}, "worst_day": worst_day, "pnl": pnl,
            "flagged_days": flagged, **check.run(db)}


def firm_daily_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("""
            select f.*, r.is_flagged as reconciliation_flagged
            from daily_firm_summary as f join reconciliation_daily as r using (as_of_date)
            order by as_of_date""").df()
    money = ["market_value", "loan", "equity", "requirement", "total_deficit", "market_pnl", "deposits",
             "interest_income", "unexplained"]
    df[money] = df[money].round(2)
    df[["collateral_coverage", "margin_utilisation"]] = df[["collateral_coverage", "margin_utilisation"]].round(4)
    return df.to_csv(index=False, lineterminator="\n")


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def findings(s: dict) -> str:
    b, last, c, sh, top = s["book"], s["last_day"], s["margin_calls"], s["shock"], s["largest_holding"]
    rec, dup = s["checks"]["reconciliation"], s["checks"]["repeated_positions_file"]
    r = c["resolution"]
    lines = [
        "# Margin book: findings",
        "",
        f"Simulated data. {b['accounts']} accounts ({b['margin_accounts']} allowed to borrow), {b['weekdays']} "
        f"weekdays from {s['first_day']} to {s['as_of']}.",
        "",
        f"## The book on {s['as_of']}",
        "",
        f"- {last['borrowers']} borrowers owe {_usd(last['loan'])} against {_usd(last['market_value'])} of "
        f"securities in the whole book; equity {_usd(last['equity'])}.",
        f"- Collateral coverage (market value less each holding's maintenance requirement, over the loan) is "
        f"{last['collateral_coverage']:.2f}; borrowers use {_pct(last['margin_utilisation'])} of what they could "
        "borrow at the 50% initial rate.",
        f"- {last['concentrated_borrowers']} borrowers hold over half their account in one security. The largest "
        f"single holding behind the loans is {top['symbol']} ({top['sector']}, "
        f"{_pct(top['share_of_borrower_value'])} of borrowers' securities); {s['shock_sector']['sector']} as a "
        f"sector is {_pct(s['shock_sector']['share'])}.",
        "",
        "## Margin calls",
        "",
        f"- {sh['from']} to {sh['to']}: {s['shock_sector']['sector']} fell {_pct(-sh['mildest_drop'])} to "
        f"{_pct(-sh['worst_drop'])}; market P&L for the week {_usd(sh['market_pnl_week'])}. "
        f"{sh['real_calls_within_a_week']} calls started that week or the next.",
        f"- {c['calls'] - c['on_a_break']} real calls over the period ({c['concentrated']} in concentrated "
        f"accounts, {c['top_in_semiconductors']} with a semiconductor as the largest holding), "
        f"{_usd(c['deficit_at_call'])} short on the day of the call, median {c['median_weekdays']:.0f} "
        f"weekday(s) in call. Ended by deposit {r.get('deposit', 0)}, liquidation {r.get('liquidated', 0)}, the "
        f"market {r.get('market', 0)}, still open {r.get('open', 0)}.",
        f"- {c['on_a_break']} more calls start on an account-day that does not reconcile to the ledger. They are "
        "not real (see below) and are left out of the numbers above.",
        "",
        "## Does the mart agree with the ledger",
        "",
        f"The reconciliation compares {b['weekdays'] * b['accounts']:,} account-days of mart market value and cash "
        f"with the books of record and flags {rec['account_days_flagged']} of them, on {len(s['flagged_days'])} "
        f"days. Against what was planted: {rec['missed']} missed, {rec['false_alarms']} false alarms.",
        "",
        "| day | market value drift | cash drift | accounts | cause |",
        "|---|---:|---:|---:|---|",
    ]
    cause = {d: f for f, v in rec["faults"].items() for d in v["days"]}
    words = {"split_applied_late": "positions file still has SEM03's pre-split quantity on its ex-date",
             "interest_missing_from_cash_file": "May's margin interest is in the ledger but not in the cash file"}
    for f in s["flagged_days"]:
        lines.append(f"| {f['date']} | {_usd(f['market_value_drift'])} | {_usd(f['cash_drift'])} | "
                     f"{f['accounts_broken']} | {words.get(cause.get(f['date']), 'unexplained')} |")
    unexpl = ", ".join(u["date"] for u in s["checks"]["unexplained_pnl_days"])
    lines += [
        "",
        f"- The positions file for {dup['date']} was loaded {dup['loads']} times ({dup['raw_rows']:,} rows for "
        f"{dup['rows_kept']:,} holdings). Staging keeps the latest load; counted twice the day would be "
        f"{_usd(dup['drift_if_counted_twice'])} over the ledger.",
        f"- Daily P&L leaves equity unexplained on {unexpl}: each fault shows on its own day and again, reversed, "
        "the next. The P&L check only says something moved; the ledger says which day is wrong.",
        "",
    ]
    return "\n".join(lines)
