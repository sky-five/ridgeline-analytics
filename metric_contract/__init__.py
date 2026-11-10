"""Metric contract: a governed metric may not change its value on a fixed snapshot unless its version goes up.

Every metric in dbt/models/semantic/_metrics.yml carries `config: {meta: {version: N}}`. contract.json records,
for each metric, the version and its values on one fixed snapshot (the warehouse built as of SNAPSHOT_AS_OF),
by month where the metric has a time dimension, else one total.

    python -m metric_contract              # compare the built snapshot with contract.json; exit 1 on a problem
    python -m metric_contract --update     # record new or version-bumped metrics in contract.json

A change to a metric's SQL, a dbt model under it or the source data that moves a number on the snapshot
fails the check until the metric's version is bumped and the contract updated, so the change is on purpose
and shows up in review.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTRACT = HERE / "contract.json"
METRICS_DIR = ROOT / "dbt" / "models"
SNAPSHOT_AS_OF = "2026-06-30"
REL_TOL = 1e-9
ABS_TOL = 1e-6
SHOWN = 3  # changed periods quoted per metric


def defined_versions(models_dir: Path = METRICS_DIR) -> dict[str, int]:
    """Metric name -> version, read from every dbt YAML file that defines metrics."""
    versions: dict[str, int] = {}
    for path in sorted(models_dir.rglob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for m in doc.get("metrics") or []:
            version = ((m.get("config") or {}).get("meta") or {}).get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ValueError(f"{path.name}: metric {m.get('name')!r} needs config.meta.version >= 1")
            versions[m["name"]] = version
    return versions


def snapshot_values(metric_names: list[str]) -> dict[str, dict[str, float]]:
    """Each metric's values on the built warehouse: {'YYYY-MM': value} by month, or {'total': value}."""
    from semantic import list_metrics, query

    has_time = {m.name: "metric_time__day" in m.dimensions for m in list_metrics()}
    out = {}
    for name in metric_names:
        if has_time.get(name):
            df = query([name], ["metric_time__month"])
            pairs = ((str(r["metric_time__month"])[:7], r[name]) for r in df.to_dict("records"))
        else:
            df = query([name])
            pairs = (("total", r[name]) for r in df.to_dict("records"))
        out[name] = {k: _num(v) for k, v in sorted(pairs)}
    return out


def _num(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) else round(f, 6)


def same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def diff(old: dict[str, float], new: dict[str, float]) -> list[str]:
    """Periods whose value changed, as 'period: old -> new'."""
    out = []
    for period in sorted(set(old) | set(new)):
        a, b = old.get(period), new.get(period)
        if period not in old or period not in new or not same(a, b):
            out.append(f"{period}: {_fmt(a, period in old)} -> {_fmt(b, period in new)}")
    return out


def _fmt(v, present: bool) -> str:
    if not present:
        return "missing"
    if v is None:
        return "null"
    return f"{v:,.6g}" if abs(v) < 1000 else f"{v:,.2f}".rstrip("0").rstrip(".")


def _quote(changes: list[str]) -> str:
    more = f" (+{len(changes) - SHOWN} more)" if len(changes) > SHOWN else ""
    return "; ".join(changes[:SHOWN]) + more


def check(versions: dict[str, int], contract: dict, values: dict[str, dict[str, float]],
          base: dict | None = None) -> list[str]:
    """Problems that should fail the check. `contract` is contract.json; `base` is the base branch's copy."""
    problems = []
    recorded = contract.get("metrics", {})
    snap = contract.get("snapshot_as_of", SNAPSHOT_AS_OF)
    for name in sorted(set(versions) | set(recorded)):
        if name not in recorded:
            problems.append(f"{name}: new metric not in the contract; run `python -m metric_contract --update`")
            continue
        if name not in versions:
            problems.append(f"{name}: in the contract but no longer defined; run `python -m metric_contract --update`")
            continue
        v, rec = versions[name], recorded[name]
        if v < rec["version"]:
            problems.append(f"{name}: version went down (contract v{rec['version']}, definition v{v})")
        elif v > rec["version"]:
            problems.append(f"{name}: bumped to v{v} but the contract still has v{rec['version']}; "
                            "run `python -m metric_contract --update`")
        elif changes := diff(rec["values"], values.get(name, {})):
            problems.append(f"{name}: value changed on the {snap} snapshot without a version bump "
                            f"(still v{v}): {_quote(changes)}")
    problems += check_against_base(contract, base)
    return problems


def check_against_base(contract: dict, base: dict | None) -> list[str]:
    """The contract file itself: recorded values may change only together with a higher version."""
    if not base:
        return []
    problems = []
    if contract.get("snapshot_as_of") != base.get("snapshot_as_of"):
        return problems  # moving the snapshot re-records every metric; review it as a whole
    old = base.get("metrics", {})
    for name, rec in sorted(contract.get("metrics", {}).items()):
        if name in old and diff(old[name]["values"], rec["values"]) and rec["version"] <= old[name]["version"]:
            problems.append(f"{name}: contract values edited without a version bump (base v{old[name]['version']})")
    return problems


def update(versions: dict[str, int], contract: dict, values: dict[str, dict[str, float]]) -> tuple[dict, list[str]]:
    """New contract with new and bumped metrics recorded and removed ones dropped.

    Returns (contract, refused): a metric whose values moved without a version bump is never re-recorded.
    """
    recorded = contract.get("metrics", {})
    out, refused = {}, []
    for name in sorted(versions):
        rec, v = recorded.get(name), versions[name]
        if rec is None or v > rec["version"]:
            out[name] = {"version": v, "values": values[name]}
            continue
        out[name] = rec
        if v == rec["version"] and diff(rec["values"], values.get(name, {})):
            refused.append(f"{name}: value changed without a version bump; bump config.meta.version to {v + 1}")
        elif v < rec["version"]:
            refused.append(f"{name}: version went down (contract v{rec['version']}, definition v{v})")
    return {"snapshot_as_of": contract.get("snapshot_as_of", SNAPSHOT_AS_OF), "metrics": out}, refused


def load(path: Path = CONTRACT) -> dict:
    if not path.exists():
        return {"snapshot_as_of": SNAPSHOT_AS_OF, "metrics": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save(contract: dict, path: Path = CONTRACT) -> None:
    path.write_text(json.dumps(contract, indent=1, sort_keys=False) + "\n", encoding="utf-8")
