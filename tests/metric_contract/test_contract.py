"""Metric contract rules, on small hand-made contracts (no warehouse needed), plus the committed contract."""
import json
import os
from pathlib import Path

import pytest

from metric_contract import (
    CONTRACT,
    SNAPSHOT_AS_OF,
    check,
    defined_versions,
    diff,
    load,
    save,
    update,
)

ROOT = Path(__file__).resolve().parents[2]
VALUES = {"mrr": {"2026-05": 181215.0, "2026-06": 183000.0}, "nrr_12m": {"total": 0.606066}}


def contract(**versions) -> dict:
    return {"snapshot_as_of": SNAPSHOT_AS_OF,
            "metrics": {n: {"version": v, "values": VALUES[n]} for n, v in versions.items()}}


def moved(name="mrr", period="2026-06", value=175000.0) -> dict:
    return {**VALUES, name: {**VALUES[name], period: value}}


def test_unchanged_values_pass():
    assert check({"mrr": 1, "nrr_12m": 1}, contract(mrr=1, nrr_12m=1), VALUES) == []


def test_silent_change_fails_and_names_the_period():
    [problem] = check({"mrr": 1, "nrr_12m": 1}, contract(mrr=1, nrr_12m=1), moved())
    assert problem.startswith("mrr: value changed on the 2026-06-30 snapshot without a version bump")
    assert "2026-06: 183,000 -> 175,000" in problem


def test_float_noise_is_not_a_change():
    noisy = moved("nrr_12m", "total", 0.606066 * (1 + 1e-12))
    assert check({"mrr": 1, "nrr_12m": 1}, contract(mrr=1, nrr_12m=1), noisy) == []


def test_period_appearing_or_disappearing_is_a_change():
    assert diff({"2026-05": 1.0}, {"2026-05": 1.0, "2026-06": 2.0}) == ["2026-06: missing -> 2"]
    assert diff({"2026-05": 1.0, "2026-06": 2.0}, {"2026-05": 1.0}) == ["2026-06: 2 -> missing"]
    assert diff({"x": None}, {"x": 0.0}) == ["x: null -> 0"]


def test_long_diffs_are_shortened():
    old = {f"2025-{m:02d}": float(m) for m in range(1, 13)}
    [problem] = check({"mrr": 1}, {"metrics": {"mrr": {"version": 1, "values": old}}},
                      {"mrr": {k: v + 1 for k, v in old.items()}})
    assert problem.endswith("(+9 more)")


def test_bump_without_update_fails_until_recorded():
    [problem] = check({"mrr": 2, "nrr_12m": 1}, contract(mrr=1, nrr_12m=1), moved())
    assert "bumped to v2 but the contract still has v1" in problem
    new, refused = update({"mrr": 2, "nrr_12m": 1}, contract(mrr=1, nrr_12m=1), moved())
    assert refused == []
    assert new["metrics"]["mrr"] == {"version": 2, "values": moved()["mrr"]}
    assert check({"mrr": 2, "nrr_12m": 1}, new, moved(), base=contract(mrr=1, nrr_12m=1)) == []


def test_update_refuses_a_silent_change():
    old = contract(mrr=1, nrr_12m=1)
    new, refused = update({"mrr": 1, "nrr_12m": 1}, old, moved())
    assert refused == ["mrr: value changed without a version bump; bump config.meta.version to 2"]
    assert new["metrics"]["mrr"] == old["metrics"]["mrr"]  # the old values stay, so the check keeps failing


def test_version_going_down_fails():
    [problem] = check({"mrr": 1, "nrr_12m": 1}, contract(mrr=2, nrr_12m=1), VALUES)
    assert "version went down" in problem


def test_new_and_removed_metrics_must_be_recorded():
    problems = check({"mrr": 1, "nrr_12m": 1}, contract(mrr=1), VALUES)
    assert problems == ["nrr_12m: new metric not in the contract; run `python -m metric_contract --update`"]
    problems = check({"mrr": 1}, contract(mrr=1, nrr_12m=1), VALUES)
    assert problems == ["nrr_12m: in the contract but no longer defined; run `python -m metric_contract --update`"]
    new, refused = update({"mrr": 1}, contract(mrr=1, nrr_12m=1), VALUES)
    assert refused == [] and list(new["metrics"]) == ["mrr"]


def test_hand_edited_contract_is_caught_against_the_base_branch():
    # Someone edits contract.json to match the new numbers but leaves the version alone.
    edited = contract(mrr=1, nrr_12m=1)
    edited["metrics"]["mrr"]["values"] = moved()["mrr"]
    problems = check({"mrr": 1, "nrr_12m": 1}, edited, moved(), base=contract(mrr=1, nrr_12m=1))
    assert problems == ["mrr: contract values edited without a version bump (base v1)"]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "contract.json"
    assert load(path) == {"snapshot_as_of": SNAPSHOT_AS_OF, "metrics": {}}
    save(contract(mrr=1, nrr_12m=1), path)
    assert load(path) == contract(mrr=1, nrr_12m=1)


def test_every_metric_needs_a_version(tmp_path):
    (tmp_path / "m.yml").write_text("metrics:\n  - name: mrr\n    type: simple\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mrr"):
        defined_versions(tmp_path)


def test_committed_contract_covers_every_defined_metric():
    versions = defined_versions()
    recorded = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert recorded["snapshot_as_of"] == SNAPSHOT_AS_OF
    assert len(versions) == 27
    assert {n: r["version"] for n, r in recorded["metrics"].items()} == versions


@pytest.mark.warehouse
@pytest.mark.skipif(os.environ.get("RIDGELINE_AS_OF") != SNAPSHOT_AS_OF,
                    reason=f"needs the warehouse built as of {SNAPSHOT_AS_OF} (RIDGELINE_AS_OF)")
def test_built_snapshot_matches_the_contract():
    from metric_contract import snapshot_values

    versions = defined_versions()
    assert check(versions, load(), snapshot_values(sorted(versions))) == []
