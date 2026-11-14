"""Write the funnel results: results/summary.json, results/funnel_weekly.csv and the findings note
results/findings.md. Every number comes from the dbt marts or check.py."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from onboarding_funnel import check
from onboarding_funnel.simulate import AS_OF, FIRST_DAY

RESULTS = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS / "summary.json"
WEEKLY = RESULTS / "funnel_weekly.csv"
FINDINGS = RESULTS / "findings.md"


def _records(df: pd.DataFrame, digits: int = 4) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        out.append({k: (round(float(v), digits) if isinstance(v, float) else v) for k, v in r.items()})
    return out


def summary(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        funnel = _records(con.sql("select * from funnel_by_program order by program").df())
        ttft = _records(con.sql("select * from time_to_first_transaction order by program").df(), 2)
        reasons = _records(con.sql("select * from drop_off_reasons order by program, applicants desc").df())
        mature = con.sql("select max(cohort_week) from fct_applications where is_mature").fetchone()[0]
    return {"as_of": AS_OF.isoformat(), "first_week": FIRST_DAY.isoformat(), "last_mature_week": mature.isoformat(),
            "funnel": funnel, "time_to_first_transaction": ttft, "drop_off_reasons": reasons, **check.run(db)}


def weekly_csv(db: Path) -> str:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.sql("select * from funnel_weekly order by program, cohort_week").df()
    rates = [c for c in df.columns if c.endswith("_rate") or c.endswith("_per_id") or c.endswith("_applicant")]
    df[rates] = df[rates].round(4)
    return df.to_csv(index=False, lineterminator="\n")


def to_json(s: dict) -> str:
    return json.dumps(s, indent=2, default=str) + "\n"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def findings(s: dict) -> str:
    """A short note: what the funnel shows, what moved, and which move is not real."""
    f = {r["program"]: r for r in s["funnel"]}
    t = {r["program"]: r for r in s["time_to_first_transaction"]}
    top = {}
    for r in s["drop_off_reasons"]:
        top.setdefault(r["program"], r)
    kyc_reasons = {}
    for r in s["drop_off_reasons"]:
        if r["drop_off_step"] == "kyc":
            kyc_reasons.setdefault(r["program"], r)
    c = s["checks"]
    lines = [
        "# Onboarding funnel: findings",
        "",
        f"Simulated data. People who started from {s['first_week']} to {s['last_mature_week']} (weeks with the "
        f"full 30-day activation window by {s['as_of']}). Activated = first transaction within 30 days of starting.",
        "",
        "## The funnel",
        "",
        "| program | started | KYC pass (of submitted) | activated | median days to first transaction | "
        "biggest drop-off | biggest KYC fail reason |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for p in sorted(f, key=lambda p: -f[p]["activation_rate"]):
        lines.append(
            f"| {p} | {f[p]['started']:,} | {_pct(f[p]['kyc_pass_rate'])} | {_pct(f[p]['activation_rate'])} | "
            f"{t[p]['median_days']:.1f} | {top[p]['drop_off_reason']} ({_pct(top[p]['share_of_drop_offs'])}) | "
            f"{kyc_reasons[p]['drop_off_reason']} |")
    lines += ["", "## What moved", ""]
    for st in s["steps"]:
        if st["shift"]:
            lines.append(f"- {st['program']} {st['rate']}: {_pct(st['before'])} -> {_pct(st['after'])} from the week "
                         f"of {st['week']} (t = {st['t']}), read as **{st['reading']}**.")
    for g in s["counting_breaks"]:
        i, p = g["per_application_id"], g["per_person"]
        lines += [
            "",
            f"## Not a real drop: {g['program']} from {g['from_week']}",
            "",
            f"Counted per application id, activation fell from {_pct(i['before'])} to {_pct(i['after'])} "
            f"({i['change_pp']:+.1f} pp, 95% CI {i['ci_pp'][0]:+.1f} to {i['ci_pp'][1]:+.1f}). Counted per person it "
            f"went from {_pct(p['before'])} to {_pct(p['after'])} ({p['change_pp']:+.1f} pp, 95% CI "
            f"{p['ci_pp'][0]:+.1f} to {p['ci_pp'][1]:+.1f}): about {100 * g['share_of_drop_from_counting']:.0f}% "
            "of the drop is people counted twice. Application ids per person went above "
            f"{c['ids_per_person']['limit']} that week and stayed "
            f"there (up to {c['ids_per_person']['programs'][g['program']]['max']}).",
        ]
    k = c["person_key"]
    lines += [
        "",
        "## Can the counts be trusted",
        "",
        f"- {c['redelivery']['redelivered']:,} of {c['redelivery']['delivered_rows']:,} delivered events were "
        "redeliveries; each is counted once.",
        f"- {k['application_ids']:,} application ids belong to {k['applications']:,} people-in-a-program; the key "
        f"(trimmed lower-case email + date of birth) splits {k['normalised_key']['people_split']} and merges "
        f"{k['normalised_key']['people_merged']} against the simulator's labels. Keyed on the raw email it would "
        f"split {k['raw_email_key']['people_split']}.",
        "",
        "## What to look at",
        "",
    ]
    for g in s["counting_breaks"]:
        lines.append(f"- {g['program']}: find what opens a second application id from {g['from_week']}, and report "
                     "activation per person, not per application id.")
    for r in s["kyc_reason_shifts"]:
        lines.append(f"- {r['program']}: the KYC pass rate drop is real. {r['reason']} grew the most, from "
                     f"{_pct(r['before'])} to {_pct(r['after'])} of people submitted, from {r['from_week']}; look at "
                     "what changed in that check that week.")
    unfunded = [p for p in sorted(top) if top[p]["drop_off_reason"] == "not_funded"]
    if unfunded:
        lines.append(f"- {' and '.join(unfunded)}: the largest loss is people who pass KYC and never fund the "
                     "account, not KYC itself.")
    lines.append("")
    return "\n".join(lines)
