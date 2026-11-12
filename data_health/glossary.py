"""Plain-language glossary for the Data health page, for people who use the numbers but did not build them.

Every number in a definition is read from the code that applies it (scorecard.py and the dbt source
freshness config), so the glossary cannot drift from the rules. `shown_as` lists the page labels a term
explains; a test checks that every column title on the page is covered.

    python -m data_health.glossary      # print the glossary
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from data_health.scorecard import AMBER, RED, STALE_RED, WINDOW_DAYS

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "dbt" / "models" / "staging"
PAGE = ROOT / "reports" / "pages" / "data-health.md"


def source_freshness_hours() -> tuple[int, int]:
    """(warn, error) hours from the dbt source configs. Every source must use the same pair."""
    pairs = set()
    for path in sorted(SOURCES.glob("*/_*__sources.yml")):
        for src in yaml.safe_load(path.read_text())["sources"]:
            f = src["config"]["freshness"]
            for key in ("warn_after", "error_after"):
                assert f[key]["period"] == "hour", f"{path.name}: {key} is not in hours"
            pairs.add((f["warn_after"]["count"], f["error_after"]["count"]))
    if len(pairs) != 1:
        raise ValueError(f"sources disagree on freshness thresholds: {sorted(pairs)}")
    return pairs.pop()


def _n(x: float) -> str:
    return f"{x:g}"


def terms() -> list[dict]:
    warn, error = source_freshness_hours()
    a, r, w = _n(AMBER), _n(RED), WINDOW_DAYS
    return [
        {"term": "Source system", "shown_as": ["Source system"],
         "meaning": "One simulated system the warehouse loads from (app database, CRM, support desk, "
                    "contractor operations, product events). Each one is loaded by its own dlt pipeline."},
        {"term": "Last successful load", "shown_as": ["Last successful load (UTC)", "Loads"],
         "meaning": "When that system's pipeline last finished without an error, in UTC. Loads is how many "
                    "successful loads the warehouse has recorded for it."},
        {"term": "Hours before build", "shown_as": ["Hours before build"],
         "meaning": "Hours between that last successful load and the moment this site was built."},
        {"term": "Pipeline freshness", "shown_as": ["Freshness"],
         "meaning": f"Fresh up to {warn} hours since the last successful load, warn after {warn}, error "
                    f"after {error}. It says whether the pipeline ran, not whether the business was busy: "
                    "a quiet CRM day is still fresh.",
         "what_to_do": "warn or error: every number from that system may be out of date. Check the date "
                       "on the page you are reading before you quote it."},
        {"term": "Batch", "shown_as": [],
         "meaning": "What an incremental load picks up on one day: the rows whose updated_at falls on that "
                    "day. A ticket that opens, gets a reply and is solved shows up in three batches."},
        {"term": "Table", "shown_as": ["Table"],
         "meaning": "One source table as it lands in the warehouse, before any modelling."},
        {"term": "Usual day", "shown_as": ["Usual a day"],
         "meaning": f"The table's own last {w} days. Each table is held to its own normal, so a CRM table "
                    "with a few rows a day and an event feed with thousands are judged fairly."},
        {"term": "Rows", "shown_as": ["Rows"],
         "meaning": "Rows in the day's batch. Usual a day is the average over the last "
                    f"{w} days."},
        {"term": "Spread", "shown_as": [],
         "meaning": f"How far a usual day strays from the average: the standard deviation of the last {w} "
                    "days, but never smaller than random noise allows for a table of that size. '4 spreads "
                    "below' means much further from normal than ordinary days go."},
        {"term": "Table freshness", "shown_as": ["Freshness"],
         "meaning": f"Hours from the table's last row to the end of the day, against the longest gap between "
                    f"its rows in the last {w} days (never less than 24 hours). Amber past that gap, red past "
                    f"{STALE_RED} times it."},
        {"term": "Volume", "shown_as": ["Volume"],
         "meaning": f"Rows in the day's batch against the usual day. Amber more than {a} spreads away "
                    f"(too few or too many), red more than {r}. Too many usually means a batch loaded twice."},
        {"term": "Null rate", "shown_as": ["Null rate"],
         "meaning": f"For each column, the share of the day's rows left empty, against that column's usual "
                    f"share. Amber more than {a} spreads emptier than usual, red more than {r}. The table's "
                    "id and updated_at are not checked."},
        {"term": "Grade", "shown_as": ["Grade", "Green", "Amber", "Red"],
         "meaning": "The worst of the table's three checks: green, amber or red.",
         "what_to_do": "green: use the numbers. amber: usable, but read the reason before quoting anything "
                       "from that table. red: do not use numbers built on that table for this day until it "
                       "is fixed; CI fails on a red table."},
        {"term": "Reason", "shown_as": ["Reason"],
         "meaning": "One sentence from the check that set the grade, with its own numbers, e.g. '199 rows, "
                    "9.8 spreads below the usual 412 a day'. On a green table it summarises all three checks."},
        {"term": "Last dbt build", "shown_as": ["Passing", "Models, tests and snapshots", "Type", "Status",
                                                 "Count"],
         "meaning": "The dbt run that built this site: how many models, tests and snapshots ran, by type "
                    "and status. Every test passing means keys are unique, values are allowed, and totals "
                    "reconcile between tables."},
        {"term": "Governed metric", "shown_as": [],
         "meaning": "A business number (MRR, signups, close rate and the rest) defined once in the semantic "
                    "layer. Their definitions and independent checks are on the Metric glossary page."},
    ]


def glossary() -> pd.DataFrame:
    """One row per term, for reporting.data_health_glossary."""
    rows = [{"term": t["term"], "shown_as": ", ".join(t["shown_as"]), "meaning": t["meaning"],
             "what_to_do": t.get("what_to_do", "")} for t in terms()]
    return pd.DataFrame(rows)


def page_labels(text: str) -> set[str]:
    """Column titles and BigValue titles used on an Evidence page."""
    return set(re.findall(r'<(?:Column|BigValue)\b[^>]*\btitle="([^"]+)"', text))


def main() -> None:
    for t in terms():
        print(f"{t['term']}: {t['meaning']}")
        if t.get("what_to_do"):
            print(f"  What to do: {t['what_to_do']}")


if __name__ == "__main__":
    main()
