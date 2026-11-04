"""The record workflow must resume cleanly: a fixed as-of date, one results file per model and date."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "record-eval.yml"


def load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps():
    return {s.get("name", s.get("uses")): s for s in load()["jobs"]["record"]["steps"]}


def test_runs_only_on_demand_with_fixed_inputs():
    wf = load()
    on = wf[True] if True in wf else wf["on"]  # YAML 1.1 reads the key `on` as True
    assert set(on) == {"workflow_dispatch"}
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["model"]["default"] == "gemini-3.5-flash-lite"
    assert inputs["as_of"]["default"] == "2026-11-02"  # same as-of date as the committed Claude Code run
    assert wf["permissions"] == {"contents": "write"}


def test_fails_fast_without_the_key_and_keeps_it_out_of_other_steps():
    s = steps()
    first = load()["jobs"]["record"]["steps"][0]
    assert first["name"] == "Check the key" and "GEMINI_API_KEY" in first["run"]
    with_key = [n for n, st in s.items() if "GEMINI_API_KEY" in str(st.get("env", {}))]
    assert with_key == ["Check the key", "Record"]


def test_builds_the_as_of_date_and_records_into_one_resumable_file():
    s = steps()
    build = s["Load + dbt build (DuckDB)"]["run"]
    assert '--as-of "$AS_OF"' in build and "--fresh" in build
    assert "OUT=semantic_eval/results/raw-vs-governed-gemini-$MODEL-as-of-$AS_OF.json" in build
    rec = s["Record"]["run"]
    for flag in ('--backend api', '--provider gemini', '--model "$MODEL"', '--limit "$LIMIT"', '--pace "$PACE"',
                 '--out "$OUT"'):
        assert flag in rec
    assert "git add semantic_eval/results" in s["Commit the recording"]["run"]
