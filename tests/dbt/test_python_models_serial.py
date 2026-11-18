"""No two dbt Python models may run at the same time.

dbt-duckdb runs Python models as threads inside one process. When two of them import scikit-learn for the
first time at once, scipy can be caught half-imported ("cannot import name 'minkowski' from partially
initialized module 'scipy.spatial.distance'"). The fix is ordering: every pair of Python models in a dbt
project must be linked by refs, so dbt builds them one after the other whatever the thread count.

The graph is read from the model files (ref() in SQL, dbt.ref() in Python), so this runs without dbt.
"""
import re
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SQL_REF = re.compile(r"""\bref\(\s*['"](\w+)['"]\s*\)""")
PY_REF = re.compile(r"""\bdbt\.ref\(\s*['"](\w+)['"]\s*\)""")


def dbt_projects() -> list[Path]:
    return sorted(p.parent for p in ROOT.glob("**/dbt_project.yml")
                  if "dbt_packages" not in p.parts and "node_modules" not in p.parts)


def ref_graph(models_dir: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Model name -> the names it refs, and the set of Python model names."""
    graph, python = {}, set()
    for path in sorted(models_dir.glob("**/*")):
        if path.suffix == ".sql":
            graph[path.stem] = set(SQL_REF.findall(path.read_text()))
        elif path.suffix == ".py":
            graph[path.stem] = set(PY_REF.findall(path.read_text()))
            python.add(path.stem)
    return graph, python


def upstream(graph: dict[str, set[str]], name: str) -> set[str]:
    seen, todo = set(), list(graph.get(name, ()))
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(graph.get(n, ()))
    return seen


def concurrent_pairs(graph: dict[str, set[str]], python: set[str]) -> list[tuple[str, str]]:
    """Pairs of Python models with no ref path between them: dbt may run those at the same time."""
    return [(a, b) for a, b in combinations(sorted(python), 2)
            if a not in upstream(graph, b) and b not in upstream(graph, a)]


def test_finds_the_python_models_in_the_main_project():
    graph, python = ref_graph(ROOT / "dbt" / "models")
    assert python == {"fct_pqa_scores", "fct_ticket_themes"}
    assert "fct_account_funnel" in graph["fct_pqa_scores"]
    assert "stg_support__tickets" in graph["fct_ticket_themes"]


def test_ticket_themes_waits_for_the_pqa_scores():
    graph, _ = ref_graph(ROOT / "dbt" / "models")
    assert "fct_pqa_scores" in upstream(graph, "fct_ticket_themes")
    assert "fct_ticket_themes" not in upstream(graph, "fct_pqa_scores")  # no cycle


@pytest.mark.parametrize("project", dbt_projects(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_two_python_models_can_run_at_once(project):
    graph, python = ref_graph(project / "models")
    assert concurrent_pairs(graph, python) == []


def test_flags_two_unlinked_python_models():
    graph = {"a": {"src"}, "b": {"src"}, "c": {"b"}, "src": set()}
    assert concurrent_pairs(graph, {"a", "b"}) == [("a", "b")]
    assert concurrent_pairs(graph, {"b", "c"}) == []
