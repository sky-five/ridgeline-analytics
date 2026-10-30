"""Scoring one answer against the truth. Kept free of I/O so it can be unit-tested."""
import re

RATIO_TOL = 0.005  # half a percentage point
NUMBER_TOL = 0.005  # 0.5% relative


def _num(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, int | float):
        return float(x)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(x))
    return float(m.group().replace(",", "")) if m else None


def _norm(x) -> str:
    return re.sub(r"[^a-z0-9.]+", "_", str(x).lower()).strip("_")


def correct(qtype: str, answer, truth, tolerance: float | None = None) -> bool:
    if qtype == "unanswerable":
        return answer is None or (isinstance(answer, str) and _num(answer) is None)
    if answer is None or truth is None:
        return False
    if qtype == "number":
        a, t = _num(answer), float(truth)
        tol = tolerance if tolerance is not None else NUMBER_TOL
        return a is not None and abs(a - t) <= max(abs(t) * tol, 0.5 if abs(t) >= 50 else 0.01)
    if qtype == "ratio":
        a, t = _num(answer), float(truth)
        if a is None:
            return False
        if abs(a) > 1.0 or (isinstance(answer, str) and "%" in answer):
            a /= 100.0  # answered in percent
        return abs(a - t) <= (tolerance if tolerance is not None else RATIO_TOL)
    if qtype == "text":
        return _norm(truth) == _norm(answer) or _norm(truth) in _norm(answer).split("_")
    if qtype == "set":
        items = answer if isinstance(answer, list) else re.split(r"[,\n;]+", str(answer))
        return {_norm(i) for i in items if str(i).strip()} == {_norm(t) for t in truth}
    raise ValueError(f"unknown question type {qtype!r}")


def grounded(expected_models: list[str], cited: list[str] | None) -> bool:
    """Did the agent cite at least one of the models the answer should come from?"""
    if not expected_models:
        return True
    names = {_norm(str(c).split(".")[-1]) for c in (cited or [])}
    return any(_norm(m) in names for m in expected_models)
