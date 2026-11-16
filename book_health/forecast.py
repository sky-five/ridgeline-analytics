"""Three simple rules for next months' retention (renewed over renewals due) per province, back-tested month by
month on the book's own history.

At every forecast origin (the last month whose renewals are known) each rule forecasts the next 3 months using only
months up to the origin:

- last_month: the origin month's retention.
- trailing_3: renewals-weighted retention over the 3 months to the origin.
- trailing_12: renewals-weighted retention over the 12 months to the origin.

Origins run monthly from 12 months after the first month to the month before the last one. Each forecast is
scored against the retention that happened. Scores are weighted by renewals due: mean absolute error and bias in
percentage points (bias above zero means the rule expected more customers to stay than did).
"""
import pandas as pd

RULES = ("last_month", "trailing_3", "trailing_12")
HORIZONS = range(1, 4)
WINDOW = {"last_month": 1, "trailing_3": 3, "trailing_12": 12}


def forecast(due: pd.Series, renewed: pd.Series, origin: pd.Period, rule: str) -> float:
    """One rule's forecast (the same for every horizon) from months up to the origin; series indexed by Period."""
    months = [origin - k for k in range(WINDOW[rule])]
    return float(renewed[months].sum() / due[months].sum())


def backtest(pm: pd.DataFrame) -> pd.DataFrame:
    """pm: province_month (month_start, province, renewals_due, renewed). Adds the whole book as province 'all'.
    One row per province, origin, horizon and rule with forecast, actual and renewals due in the target month."""
    df = pm.assign(month=pd.PeriodIndex(pd.to_datetime(pm["month_start"]), freq="M"))[
        ["province", "month", "renewals_due", "renewed"]]
    book = df.groupby("month", as_index=False)[["renewals_due", "renewed"]].sum().assign(province="all")
    rows = []
    for prov, g in pd.concat([df, book]).groupby("province", sort=True):
        g = g.set_index("month").sort_index()
        due, renewed = g["renewals_due"].astype(float), g["renewed"].astype(float)
        first, last = g.index.min(), g.index.max()
        origin = first + 11
        while origin < last:
            for rule in RULES:
                f = forecast(due, renewed, origin, rule)
                for h in HORIZONS:
                    target = origin + h
                    if target > last:
                        break
                    rows.append({"province": prov, "origin": origin, "horizon": h, "target": target, "rule": rule,
                                 "forecast": f, "actual": renewed[target] / due[target], "due": due[target]})
            origin += 1
    return pd.DataFrame(rows)


def score(bt: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Renewals-weighted mean absolute error and bias, in percentage points, for each group of back-test rows."""
    bt = bt.assign(w_err=(bt["forecast"] - bt["actual"]) * bt["due"],
                   w_abs=(bt["forecast"] - bt["actual"]).abs() * bt["due"])
    out = bt.groupby(by, sort=False).agg(forecasts=("due", "size"), due=("due", "sum"), w_abs=("w_abs", "sum"),
                                         w_err=("w_err", "sum"))
    out["mae_points"] = (100 * out["w_abs"] / out["due"]).round(2)
    out["bias_points"] = (100 * out["w_err"] / out["due"]).round(2)
    return out[["forecasts", "mae_points", "bias_points"]].reset_index()


def best_rule(bt: pd.DataFrame) -> str:
    """The rule with the lowest error over every province (not 'all'), origin and horizon."""
    s = score(bt[bt["province"] != "all"], ["rule"])
    return str(s.sort_values(["mae_points", "rule"]).iloc[0]["rule"])


def next_months(pm: pd.DataFrame, upcoming: pd.DataFrame, rule: str) -> pd.DataFrame:
    """The chosen rule's retention for the 3 months after the last one, per province, with the renewals already
    due then (terms ending in those months) and the customers expected to stay.
    upcoming: province, renewal_month, renewals_due."""
    df = pm.assign(month=pd.PeriodIndex(pd.to_datetime(pm["month_start"]), freq="M"))
    last = df["month"].max()
    rows = []
    for prov, g in df.groupby("province", sort=True):
        g = g.set_index("month").sort_index()
        f = forecast(g["renewals_due"].astype(float), g["renewed"].astype(float), last, rule)
        for h in HORIZONS:
            target = last + h
            due = upcoming[(upcoming["province"] == prov)
                           & (pd.PeriodIndex(pd.to_datetime(upcoming["renewal_month"]), freq="M") == target)]
            n = int(due["renewals_due"].sum())
            rows.append({"province": prov, "month": str(target), "rule": rule, "retention": round(f, 4),
                         "renewals_due": n, "expected_renewed": round(n * f, 1)})
    return pd.DataFrame(rows)
