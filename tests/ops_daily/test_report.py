"""The ops-daily dashboard: the new results file is what the marts give, the reporting tables agree with each other
and with summary.json (flags with the metric table, the watchlist with today's note, false flags with the
back-check), every query on the page runs against the exported tables for every team, and the page's fixed words
match the data."""
import json
import re
from datetime import timedelta

import duckdb
import pandas as pd
import pytest

from ops_daily.report import EVENT_LABELS, min_change_text, so_what_rows, tables
from ops_daily.run import FLAGS, METRIC_DAY, METRICS, SUMMARY, TODAY, definitions, metric_day_csv
from ops_daily.simulate import AS_OF, EVENTS

ROOT = SUMMARY.parents[2]
PAGE = ROOT / "reports" / "pages" / "ops-daily.md"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
EXPORT = ROOT / "scripts" / "export_reporting.py"
SOURCES = ROOT / "reports" / "sources" / "ridgeline"
NAMES = {"ops_summary", "ops_today", "ops_metric_day", "ops_flags", "ops_backcheck", "ops_false_flags",
         "ops_so_what", "ops_definitions"}
TEAMS = 6


@pytest.fixture(scope="module")
def t():
    return tables()


@pytest.fixture(scope="module")
def s():
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page():
    return PAGE.read_text(encoding="utf-8")


def test_metric_day_file_is_what_the_marts_give(ops_db):
    assert METRIC_DAY.read_text() == metric_day_csv(ops_db)


def test_export_writes_eight_tables(t, s):
    assert set(t) == NAMES
    days = (AS_OF - pd.Timestamp(s["first_day"]).date()).days + 1
    assert len(t["ops_metric_day"]) == days * TEAMS * len(METRICS) == 7602
    assert len(t["ops_summary"]) == 1 and len(t["ops_today"]) == 3
    assert len(t["ops_so_what"]) == len(t["ops_definitions"]) == len(t["ops_false_flags"]) == len(METRICS)
    assert len(t["ops_backcheck"]) == len(EVENTS)
    assert "ops_tables()" in EXPORT.read_text()
    for name in t:
        assert (SOURCES / f"{name}.sql").read_text().strip() == f"select * from reporting.{name}"


def test_flags_are_the_flagged_rows_of_the_metric_table(t, s):
    md, flags = t["ops_metric_day"], t["ops_flags"]
    flagged = md[md["flagged"]]
    key = ["day", "site", "line", "metric"]
    assert len(flagged) == len(flags) == len(pd.read_csv(FLAGS)) == t["ops_summary"].iloc[0]["flags"] == 130
    assert flagged[key].sort_values(key).values.tolist() == flags[key].sort_values(key).values.tolist()
    assert (flagged["flagged_value"] == flagged["value"]).all() and md.loc[~md["flagged"], "flagged_value"].isna().all()
    # only full-baseline values are scored, and only those can be flagged
    assert (md["baseline_days"] == 6).sum() == s["flag_rule"]["scored_values"] == 5838
    assert (flagged["baseline_days"] == 6).all()


def test_false_flags_agree_with_the_backcheck(t, s):
    fr, flags, ff = s["flag_rule"], t["ops_flags"], t["ops_false_flags"]
    assert (flags["planted_event"] == "nothing planted").sum() == ff["false_flags"].sum() == fr["false_flags"] == 47
    assert dict(zip(ff["metric"], ff["false_flags"], strict=True)) == fr["false_flags_by_metric"]
    assert set(flags["planted_event"]) == {*EVENT_LABELS.values(), "nothing planted"}
    # a flag is labelled with an event only on its team, from the day the event starts
    for name, site, line, start, _ in EVENTS:
        mine = flags[flags["planted_event"] == EVENT_LABELS[name]]
        assert (mine["site"] == site).all() and (mine["line"] == line).all() and (mine["day"] >= start).all()


def test_backcheck_rows_are_the_planted_events(t):
    bc = t["ops_backcheck"].set_index("event")
    for name, site, line, start, cause in EVENTS:
        row = bc.loc[EVENT_LABELS[name]]
        assert row["team"] == f"{site.capitalize()} {line}" and row["from_day"] == start.isoformat()
        assert row["cause"] == definitions()[cause]["label"]
        assert 0 < row["days_on_watchlist"] <= row["days_since_start"] == (AS_OF - start).days + 1


def test_today_is_the_watchlist_in_todays_note(t, s):
    today, note = t["ops_today"], TODAY.read_text(encoding="utf-8")
    assert today["rank"].tolist() == [1, 2, 3]
    for w, r in zip(s["watchlist_as_of"], today.itertuples(), strict=True):
        assert (r.site, r.line, r.metric, r.value) == (w["site"], w["line"], w["metric"], w["value"])
        assert f"**{r.team}: {r.metric_label.lower()} {r.value_text}**, usually {r.baseline_text}" in note
    assert today.loc[1, "also_flagged"] == "service level" and today.loc[0, "also_flagged"] == ""


def test_so_what_rows_are_the_note_paragraphs(t):
    sw = t["ops_so_what"]
    assert sw["label"].tolist() == [definitions()[m]["label"] for m in METRICS]
    assert not sw["body"].str.contains(r"\*\*").any()
    assert so_what_rows("# x\n\n**Calls** (calls in): 5 today.\n\n1. **Not** a paragraph\n").to_dict("records") == [
        {"metric_sort": 0, "label": "Calls", "definition": "calls in", "body": "5 today."}]


def test_definitions_print_the_minimum_move(t):
    d = t["ops_definitions"].set_index("metric")["min_change"]
    assert d["service_level"] == "10 points" and d["abandon_rate"] == "4 points"
    assert d["avg_handle_minutes"] == "0.5 minutes" and d["open_backlog"] == "40% of the usual"
    assert min_change_text({"min_change_abs": "0.05", "min_change_rel": "0.2", "unit": "share"}) == \
        "5 points and 20% of the usual"


def _queries(page: str) -> dict[str, str]:
    return dict(re.findall(r"```sql (\w+)\n(.*?)```", page, flags=re.S))


def _fill(sql: str, team: str = "Central home") -> str:
    return sql.replace("${inputs.team.value}", team)


@pytest.fixture(scope="module")
def site(t):
    """The exported tables in a DuckDB schema named like the page's source."""
    with duckdb.connect() as con:
        con.execute("create schema ridgeline")
        for name, df in t.items():
            con.register("_df", df)
            con.execute(f"create table ridgeline.{name} as select * from _df")
            con.unregister("_df")
        yield con


def test_every_page_query_runs_on_the_exported_tables(page, site, t):
    queries = _queries(page)
    assert set(re.findall(r"ridgeline\.(\w+)", page)) == NAMES
    teams = sorted(t["ops_metric_day"]["team"].unique())
    assert len(teams) == TEAMS
    for name, sql in queries.items():
        if "${inputs.team.value}" in sql:
            for team in teams:
                rows = site.sql(_fill(sql, team)).fetchall()
                # flag queries may be empty for a quiet team and metric; the page skips those dots
                assert rows or name.startswith("f_"), (name, team)
        else:
            assert site.sql(sql).fetchall(), name
    # one chart per metric, each with its flag dots
    for m in METRICS:
        assert f"m_{m}" in queries and f"f_{m}" in queries
        assert f"{{#if f_{m}.length > 0}}" in page


def test_page_components_use_existing_columns(t, page, site):
    queries = _queries(page)
    summary_cols = set(t["ops_summary"].columns)
    for comp in re.findall(r"<(?:BigValue|Value) data=\{summary\}[^>]*>", page):
        for col in re.findall(r"\b(?:value|column)=(\w+)", comp):
            assert col in summary_cols, col

    def columns(name: str) -> set[str]:
        return {c[0] for c in site.sql(_fill(queries[name])).description}

    for name, attrs in re.findall(r"<(?:BarChart|LineChart|ReferencePoint|Dropdown) data=\{(\w+)\}(.*?)/?>", page,
                                  flags=re.S):
        cols = columns(name)
        for col in re.findall(r"\b(?:x|y|value|series)=(\w+)", attrs):
            assert col in cols, (name, col)
    for name, body in re.findall(r"<DataTable data=\{(\w+)\}[^>]*>(.*?)</DataTable>", page, flags=re.S):
        cols = columns(name)
        for col in re.findall(r"<Column id=(\w+)", body):
            assert col in cols, (name, col)
    for name, var, body in re.findall(r"\{#each (\w+) as (\w)\}(.*?)\{/each\}", page, flags=re.S):
        for field in re.findall(rf"\b{var}\.(\w+)", body):
            assert field in columns(name), (name, field)


def test_page_words_match_the_data(page, t):
    flat = " ".join(page.split())
    assert 'defaultValue="Central home"' in page and t["ops_today"].iloc[0]["team"] == "Central home"
    assert "three sites (east, central, west) and two lines (home, auto), so six teams" in flat
    # "by the last day three of the six Tuesdays behind it were already raised, so its handle time was no longer
    # flagged and only its abandon rate kept the team on the list"
    name, site, line, start, cause = next(e for e in EVENTS if e[0] == "handle_time_creep")
    md = t["ops_metric_day"]
    east = md[(md["site"] == site) & (md["line"] == line) & (md["metric"] == cause)].set_index("day")
    behind = [AS_OF - timedelta(weeks=k) for k in range(1, 7)]
    assert AS_OF.strftime("%A") == "Tuesday" and sum(d >= start for d in behind) == 3
    assert not east.loc[AS_OF, "flagged"]
    today = t["ops_today"].set_index("team").loc[f"{site.capitalize()} {line}"]
    assert today["metric"] == "abandon_rate" and today["also_flagged"] == ""


def test_nightly_smoke_test_opens_the_page():
    assert re.search(r"for page in .* ops-daily/", NIGHTLY.read_text())
