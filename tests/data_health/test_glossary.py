"""The Data health glossary covers every label on the page, and its numbers come from the rules themselves."""
import re

import pytest

import data_health.glossary as g
from data_health.scorecard import AMBER, RED, STALE_RED, WINDOW_DAYS

PAGE = g.PAGE.read_text()
GLOSSARY_COLUMNS = {"Term", "Shown on the page as", "What it means", "What to do about it"}


def _by_term() -> dict[str, str]:
    return {t["term"]: t["meaning"] for t in g.terms()}


def test_every_label_on_the_page_is_in_the_glossary():
    covered = {label for t in g.terms() for label in t["shown_as"]}
    labels = g.page_labels(PAGE) - GLOSSARY_COLUMNS
    assert len(labels) >= 15
    assert labels - covered == set()


def test_page_labels_reads_column_and_bigvalue_titles():
    text = '<Column id=a title="Rows" fmt=num0/>\n<BigValue data={x} value=red title="Red"/>\n<Value column=x/>'
    assert g.page_labels(text) == {"Rows", "Red"}


def test_terms_are_unique_and_filled_in():
    df = g.glossary()
    assert df.term.is_unique
    assert (df.meaning.str.len() > 20).all()
    assert list(df.columns) == ["term", "shown_as", "meaning", "what_to_do"]
    assert set(df.loc[df.what_to_do != "", "term"]) == {"Pipeline freshness", "Grade"}


def test_freshness_thresholds_match_the_dbt_sources():
    warn, error = g.source_freshness_hours()
    assert (warn, error) == (36, 72)
    assert f"warn after {warn}, error after {error}" in _by_term()["Pipeline freshness"]
    assert f"warn after {warn} hours without a successful load, fail after {error}" in PAGE


def test_scorecard_thresholds_are_quoted_from_the_code():
    m = _by_term()
    assert f"more than {AMBER:g} spreads away" in m["Volume"] and f"red more than {RED:g}" in m["Volume"]
    assert f"more than {AMBER:g} spreads emptier" in m["Null rate"]
    assert f"red past {STALE_RED} times it" in m["Table freshness"]
    assert f"last {WINDOW_DAYS} days" in m["Usual day"]


def test_glossary_follows_a_changed_rule(monkeypatch):
    monkeypatch.setattr(g, "AMBER", 2.5)
    monkeypatch.setattr(g, "WINDOW_DAYS", 14)
    m = _by_term()
    assert "more than 2.5 spreads away" in m["Volume"]
    assert "last 14 days" in m["Usual day"] and "28" not in m["Usual day"]


def _write_source(folder, name, warn, error):
    (folder / name).mkdir()
    (folder / name / f"_{name}__sources.yml").write_text(
        f"version: 2\nsources:\n  - name: {name}\n    config:\n      freshness:\n"
        f"        warn_after: {{count: {warn}, period: hour}}\n        error_after: {{count: {error}, period: hour}}\n")


def test_sources_that_disagree_are_an_error(tmp_path, monkeypatch):
    _write_source(tmp_path, "crm", 36, 72)
    monkeypatch.setattr(g, "SOURCES", tmp_path)
    assert g.source_freshness_hours() == (36, 72)
    _write_source(tmp_path, "support", 24, 72)
    with pytest.raises(ValueError, match="disagree"):
        g.source_freshness_hours()


def test_walkthrough_comes_first_and_links_resolve():
    headings = re.findall(r"^## (.+)$", PAGE, flags=re.M)
    assert headings[0] == "How to read this page" and "Glossary" in headings
    assert "](#glossary)" in PAGE and "](/metrics/)" in PAGE
    assert (g.ROOT / "reports" / "sources" / "ridgeline" / "data_health_glossary.sql").exists()
    assert "from ridgeline.data_health_glossary" in PAGE


def test_example_row_is_the_scorecards_first_row():
    """The walkthrough quotes the table that needs the most attention: same order as the scorecard."""
    sql = re.search(r"```sql example\n(.*?)```", PAGE, flags=re.S).group(1)
    assert "when 'red' then 0 when 'amber' then 1" in sql and "limit 1" in sql
