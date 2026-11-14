"""Read metric_spec.yml and evaluate a metric from minute sums (any row of the marts)."""
from functools import cache
from pathlib import Path

import yaml

SPEC = Path(__file__).resolve().parent / "metric_spec.yml"


@cache
def metrics() -> dict[str, dict]:
    return {m["name"]: m for m in yaml.safe_load(SPEC.read_text())["metrics"]}


def _expr(expr: str, row) -> float:
    """'a + b' or 'a - b' over column names: the only shapes the spec uses."""
    total, sign = 0.0, 1
    for token in expr.split():
        if token in "+-":
            sign = 1 if token == "+" else -1
        else:
            total += sign * float(row[token])
    return total


def numerator(name: str, row) -> float:
    return _expr(metrics()[name]["numerator"], row)


def denominator(name: str, row) -> float:
    return _expr(metrics()[name]["denominator"], row)


def value(name: str, row) -> float:
    return numerator(name, row) / denominator(name, row)
