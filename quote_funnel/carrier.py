"""Size the impact of adding a carrier to the panel, before it goes live.

What the analyst has: the half's history (sessions, every price shown, clicks, binds) and a rating sample, where
the candidate priced a random sample of past auto sessions (a price or a decline for each). What the analyst does
not have: how shoppers would react. Three small models fitted on the history fill that gap:

  click   logistic: did a quoted session click through, given its segment, quote count and best price
  choice  conditional logit: which of the shown carriers got the click, given price vs the session's best
  bind    logistic: did a click bind, given segment and the chosen price

Each sampled session is scored with and without the candidate's price; the difference, scaled from the sample to
all auto sessions, is the estimate. `truth()` replays the same simulated shoppers with the candidate on the
panel; the estimate never reads it.
"""
import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression

from quote_funnel import simulate

SAMPLE_SIZE = 3000
SAMPLE_SEED = 21
BOOTSTRAP = 400  # resamples of the rating sample; the fitted models are held fixed


def rating_sample(con: duckdb.DuckDBPyConnection, d: dict) -> pd.DataFrame:
    """The candidate's price (or a decline) on a random sample of past auto sessions."""
    auto = con.execute("select session_id from mart.session_funnel where line = 'auto' order by session_id").df()
    rng = np.random.default_rng(SAMPLE_SEED)
    picked = set(rng.choice(auto.session_id, SAMPLE_SIZE, replace=False))
    replay = simulate.simulate(d, [simulate.CANDIDATE])["carrier_quotes"]  # the candidate's rating engine only
    sample = pd.DataFrame({"session_id": sorted(picked)})
    return sample.merge(replay[["session_id", "premium"]], how="left", on="session_id")


def _segment_matrix(segments: pd.Series) -> np.ndarray:
    return np.column_stack([(segments == s).to_numpy(float) for s in simulate.SEGMENTS[1:]])


class FunnelModel:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        s = con.execute("select * from mart.session_funnel").df()
        q = con.execute("select session_id, carrier_id, premium from source.carrier_quotes").df()
        q = q.merge(s[["session_id", "segment"]], on="session_id")
        # Each carrier's usual price level in a segment; a session's prices above or below those levels say how
        # risky the shopper is. Prices are then read against that, so a risky shopper's high quote is not
        # mistaken for a bad price.
        self.level = q.assign(lp=np.log(q.premium)).groupby(["carrier_id", "segment"]).lp.mean().to_dict()
        self.carriers = sorted(q.carrier_id.unique())
        risk = self.risk_index(q)
        quoted = s[s.quoted].merge(risk, on="session_id")
        self.click = LogisticRegression(C=1e6, max_iter=1000).fit(
            self._click_x(quoted.segment, quoted.n_quotes, quoted.best_premium, quoted.risk), quoted.clicked)

        clicked = s[s.clicked][["session_id", "clicked_carrier", "bound"]]
        shown = q.merge(clicked, on="session_id").merge(risk, on="session_id")
        shown["best"] = shown.groupby("session_id").premium.transform("min")
        shown["rel"] = np.log(shown.premium / shown.best)
        shown["chosen"] = shown.carrier_id == shown.clicked_carrier
        self.beta, self.alpha = self._fit_choice(shown)
        chosen = shown[shown.chosen]
        self.bind = LogisticRegression(C=1e6, max_iter=1000).fit(
            self._bind_x(chosen.segment, chosen.premium, chosen.risk), chosen.bound)

    def risk_index(self, quotes: pd.DataFrame) -> pd.DataFrame:
        """Mean log price gap to each panel carrier's usual level, per session. Panel prices only."""
        keys = list(zip(quotes.carrier_id, quotes.segment, strict=True))
        gap = np.log(quotes.premium.to_numpy()) - np.array([self.level.get(k, np.nan) for k in keys])
        out = quotes.assign(gap=gap).dropna(subset=["gap"]).groupby("session_id").gap.mean()
        return out.rename("risk").reset_index()

    def _click_x(self, segment, n_quotes, best, risk):
        return np.column_stack([_segment_matrix(segment), np.minimum(n_quotes, 4),
                                np.log(np.asarray(best, float)) - np.asarray(risk, float)])

    def _bind_x(self, segment, premium, risk):
        return np.column_stack([_segment_matrix(segment), np.log(np.asarray(premium, float)) - np.asarray(risk, float)])

    def _fit_choice(self, shown: pd.DataFrame):
        cidx = shown.carrier_id.map({c: i for i, c in enumerate(self.carriers)}).to_numpy()
        groups = shown.session_id.factorize()[0]
        rel, chosen = shown.rel.to_numpy(), shown.chosen.to_numpy()
        k = len(self.carriers)

        def nll(theta):
            alpha = np.concatenate([[0.0], theta[1:]])  # first carrier is the reference
            u = theta[0] * rel + alpha[cidx]
            m = np.zeros(groups.max() + 1)
            np.maximum.at(m, groups, u)
            denom = np.bincount(groups, np.exp(u - m[groups]))
            return -(u[chosen] - m[groups[chosen]] - np.log(denom[groups[chosen]])).sum()

        theta = minimize(nll, np.zeros(k), method="BFGS").x
        alpha = dict(zip(self.carriers, np.concatenate([[0.0], theta[1:]]), strict=True))
        return float(theta[0]), alpha

    def expected(self, sessions: pd.DataFrame, quotes: pd.DataFrame, commission: dict) -> pd.DataFrame:
        """Expected binds and commission per carrier over `sessions`, given the prices in `quotes`."""
        neutral = float(np.mean(list(self.alpha.values())))  # a newcomer gets the panel's average pull
        q = quotes.merge(sessions[["session_id", "segment"]], on="session_id")
        q = q.merge(self.risk_index(q), on="session_id")
        agg = q.groupby("session_id").agg(n_quotes=("premium", "size"), best=("premium", "min"),
                                          segment=("segment", "first"), risk=("risk", "first")).reset_index()
        agg["p_click"] = self.click.predict_proba(
            self._click_x(agg.segment, agg.n_quotes, agg.best, agg.risk))[:, 1]
        q = q.merge(agg[["session_id", "best", "p_click"]], on="session_id")
        q["u"] = np.exp(self.beta * np.log(q.premium / q.best) + q.carrier_id.map(self.alpha).fillna(neutral))
        q["p_choose"] = q.u / q.groupby("session_id").u.transform("sum")
        q["p_bind"] = self.bind.predict_proba(self._bind_x(q.segment, q.premium, q.risk))[:, 1]
        q["binds"] = q.p_click * q.p_choose * q.p_bind
        q["commission"] = q.binds * q.carrier_id.map(commission)
        return q[["session_id", "carrier_id", "binds", "commission"]]


def estimate(con: duckdb.DuckDBPyConnection, d: dict) -> dict:
    model = FunnelModel(con)
    sample = rating_sample(con, d)
    sessions = con.execute("select session_id, segment from mart.session_funnel").df()
    sessions = sessions[sessions.session_id.isin(sample.session_id)]
    shown = con.execute("select session_id, carrier_id, premium from source.carrier_quotes").df()
    shown = shown[shown.session_id.isin(sample.session_id)]
    offered = sample.dropna(subset=["premium"]).assign(carrier_id=simulate.CANDIDATE.carrier_id)
    commission = {c.carrier_id: c.commission for c in simulate.PANEL + [simulate.CANDIDATE]}

    before = model.expected(sessions, shown, commission)
    after = model.expected(sessions, pd.concat([shown, offered[shown.columns]]), commission)
    delta = (after.groupby("session_id")[["binds", "commission"]].sum()
             .sub(before.groupby("session_id")[["binds", "commission"]].sum(), fill_value=0)
             .reindex(sample.session_id, fill_value=0))
    n_auto = con.execute("select count(*) from mart.session_funnel where line = 'auto'").fetchone()[0]
    scale = n_auto / len(sample)
    new = simulate.CANDIDATE.carrier_id
    rng = np.random.default_rng(SAMPLE_SEED)
    boot = np.array([delta.iloc[rng.integers(0, len(delta), len(delta))].sum().to_numpy() * scale
                     for _ in range(BOOTSTRAP)])
    before, after = before.groupby("carrier_id")[["binds", "commission"]].sum(), \
        after.groupby("carrier_id")[["binds", "commission"]].sum()
    return {
        "sample_sessions": len(sample),
        "sample_quoted_by_candidate": int(sample.premium.notna().sum()),
        "auto_sessions": int(n_auto),
        "choice_price_coefficient": model.beta,
        "candidate_binds": float(after.binds[new] * scale),
        "added_binds": float((after.binds.sum() - before.binds.sum()) * scale),
        "added_commission": float((after.commission.sum() - before.commission.sum()) * scale),
        "added_binds_ci": np.percentile(boot[:, 0], [2.5, 97.5]).tolist(),
        "added_commission_ci": np.percentile(boot[:, 1], [2.5, 97.5]).tolist(),
        "lost_by_panel": {c: float((before.binds[c] - after.binds[c]) * scale) for c in before.index},
    }


def truth(d: dict) -> dict:
    """Replay the same shoppers with the candidate on the panel."""
    base, with_new = simulate.simulate(d), simulate.simulate(d, simulate.PANEL + [simulate.CANDIDATE])
    commission = {c.carrier_id: c.commission for c in simulate.PANEL + [simulate.CANDIDATE]}

    def per_carrier(binds):
        return binds.carrier_id.value_counts()

    def money(binds):
        return float(binds.carrier_id.map(commission).sum())

    b0, b1 = per_carrier(base["binds"]), per_carrier(with_new["binds"])
    return {
        "candidate_binds": int(b1.get(simulate.CANDIDATE.carrier_id, 0)),
        "added_binds": int(len(with_new["binds"]) - len(base["binds"])),
        "added_commission": money(with_new["binds"]) - money(base["binds"]),
        "lost_by_panel": {c: int(b0[c] - b1.get(c, 0)) for c in b0.index},
    }
