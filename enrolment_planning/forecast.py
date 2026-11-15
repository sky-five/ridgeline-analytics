"""Three simple rules for next year's monthly intake of new post-secondary study permits, back-tested month by
month on IRCC's public series.

At every forecast origin (the last month whose count is known) each rule forecasts the next 12 months, using only
months up to the origin:

- same_month_last_year: the count for the same month a year earlier.
- last_year_with_trend: the same month a year earlier, times the last 12 months over the 12 before them.
- three_year_mean: the mean of the same month in the last three years.

Origins run monthly from 2017-12 (three full years of history) to the month before the last published one, and
each forecast is scored against what IRCC later published. Scores are WAPE (sum of absolute errors over sum of
actuals) and bias (sum of errors over sum of actuals; above zero means the rule forecast too many), per series,
rule, horizon and period of the target month.
"""
import pandas as pd

RULES = ("same_month_last_year", "last_year_with_trend", "three_year_mean")
HORIZONS = range(1, 13)
FIRST_ORIGIN = pd.Period("2017-12", "M")
# Periods of the target month. The federal cap on study permit applications was announced on 2024-01-22.
PERIODS = {
    "2018-2019 steady growth": (2018, 2019),
    "2020-2021 pandemic": (2020, 2021),
    "2022-2023 fast growth": (2022, 2023),
    "2024-2026 after the cap": (2024, 2026),
}


def period_of(year: int) -> str:
    return next(name for name, (a, b) in PERIODS.items() if a <= year <= b)


def forecast(y: pd.Series, origin: pd.Period, rule: str, horizon: int) -> float:
    """One rule's forecast for origin + horizon months, from y (indexed by monthly Period) up to the origin."""
    target = origin + horizon
    known = y[y.index <= origin]
    if rule == "same_month_last_year":
        return float(known[target - 12])
    if rule == "last_year_with_trend":
        last = known[(known.index > origin - 12)].sum()
        before = known[(known.index > origin - 24) & (known.index <= origin - 12)].sum()
        return float(known[target - 12] * last / before)
    if rule == "three_year_mean":
        return float(sum(known[target - 12 * k] for k in (1, 2, 3)) / 3)
    raise ValueError(f"unknown rule {rule!r}")


def backtest(y: pd.Series, series: str) -> pd.DataFrame:
    """Every origin, rule and horizon whose target month is published: one row each with forecast and actual."""
    last = y.index.max()
    rows = []
    origin = FIRST_ORIGIN
    while origin < last:
        for h in HORIZONS:
            target = origin + h
            if target > last:
                break
            for rule in RULES:
                rows.append({"series": series, "origin": origin, "horizon": h, "target": target, "rule": rule,
                             "forecast": forecast(y, origin, rule, h), "actual": float(y[target])})
        origin += 1
    df = pd.DataFrame(rows)
    df["period"] = [period_of(t.year) for t in df["target"]]
    return df


def score(bt: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """WAPE and bias for each group of back-test rows."""
    bt = bt.assign(err=bt["forecast"] - bt["actual"], abs_err=(bt["forecast"] - bt["actual"]).abs())
    g = bt.groupby(by, sort=False)
    out = g.agg(forecasts=("err", "size"), actual=("actual", "sum"), abs_err=("abs_err", "sum"), err=("err", "sum"))
    out["wape"] = out["abs_err"] / out["actual"]
    out["bias"] = out["err"] / out["actual"]
    return out[["forecasts", "wape", "bias"]].reset_index()


def next_12_months(bt: pd.DataFrame) -> pd.DataFrame:
    """Each origin's 12 monthly forecasts added up against the 12 actuals: the yearly intake a plan works from.
    Only origins with all 12 target months published. period is that of the window's last month."""
    full = bt.groupby(["series", "rule", "origin"]).filter(lambda g: len(g) == len(HORIZONS))
    out = full.groupby(["series", "rule", "origin"], sort=False).agg(
        forecast=("forecast", "sum"), actual=("actual", "sum")).reset_index()
    out["horizon"] = 12
    out["target"] = out["origin"] + 12
    out["period"] = [period_of(t.year) for t in out["target"]]
    return out
