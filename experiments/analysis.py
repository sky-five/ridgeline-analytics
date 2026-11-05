"""Analyse the simulated onboarding experiment end to end and write the results file.

    python -m experiments            # print the readout and write experiments/results/onboarding-checklist.json
    python -m experiments --check    # fail if the committed results file is out of date
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from experiments.peeking import aa_tests
from experiments.simulate import DEFAULT, SEED, STEPS, Design, daily_cumulative, simulate
from experiments.stats import power, sample_size_per_arm, srm_test, two_proportion_test

RESULTS = Path(__file__).resolve().parent / "results" / "onboarding-checklist.json"
SRM_ALARM = 0.001  # p-value below which the split is treated as broken
LOST_SHARE = 0.20  # the tracking-bug scenario fails to log 20% of non-activating treatment accounts


def _test(df) -> dict:
    c, t = df[df.arm == "control"], df[df.arm == "treatment"]
    return two_proportion_test(int(c.activated.sum()), len(c), int(t.activated.sum()), len(t)).as_dict()


def replays(design: Design = DEFAULT, n_runs: int = 1000, seed: int = 11) -> dict:
    """Run the same experiment design many times: how often is the planted effect found and covered?"""
    rng = np.random.default_rng(seed)
    total = design.days * design.arrivals_per_day
    n_t = rng.binomial(total, design.treatment_share, n_runs)
    n_c = total - n_t
    x_c = rng.binomial(n_c, design.p_control)
    x_t = rng.binomial(n_t, design.p_treatment)
    tests = [two_proportion_test(int(a), int(b), int(c), int(d), design.alpha)
             for a, b, c, d in zip(x_c, n_c, x_t, n_t, strict=True)]
    return {"runs": n_runs,
            "significant": sum(t.significant and t.diff > 0 for t in tests) / n_runs,
            "ci_covers_planted": sum(t.ci_low <= design.lift <= t.ci_high for t in tests) / n_runs,
            "median_diff": float(np.median([t.diff for t in tests]))}


def analyse(design: Design = DEFAULT, seed: int = SEED) -> dict:
    n_needed = sample_size_per_arm(design.p_control, design.lift, design.alpha, design.power)
    per_arm_per_day = design.arrivals_per_day * design.treatment_share
    df = simulate(design, seed)

    n_c, n_t = int((df.arm == "control").sum()), int((df.arm == "treatment").sum())
    chi2, srm_p = srm_test(n_c, n_t, design.treatment_share)
    buggy = simulate(design, seed, lost_share=LOST_SHARE)
    b_c, b_t = int((buggy.arm == "control").sum()), int((buggy.arm == "treatment").sum())
    b_chi2, b_p = srm_test(b_c, b_t, design.treatment_share)

    funnel = (df.groupby("arm")[list(STEPS)].mean().T.reset_index(names="step")
              .rename(columns={"control": "rate_control", "treatment": "rate_treatment"}))

    daily = daily_cumulative(df)
    looks = []
    for r in daily.itertuples(index=False):
        res = two_proportion_test(r.x_control, r.n_control, r.x_treatment, r.n_treatment, design.alpha)
        looks.append({"day": int(r.day), "n_control": int(r.n_control), "n_treatment": int(r.n_treatment),
                      "diff": res.diff, "ci_low": res.ci_low, "ci_high": res.ci_high, "p_value": res.p_value})

    return {
        "note": "Learning project on simulated data. The true effect is planted, so the analysis can be checked.",
        "seed": seed,
        "design": {"metric": "activation: first proposal sent within 14 days of signup",
                   "p_control": design.p_control, "planted_lift": design.lift, "alpha": design.alpha,
                   "power": design.power, "days": design.days, "arrivals_per_day": design.arrivals_per_day,
                   "treatment_share": design.treatment_share,
                   "sample_size_per_arm": n_needed,
                   "days_needed": math.ceil(n_needed / per_arm_per_day),
                   "power_at_planned_size": power(design.p_control, design.lift,
                                                  int(design.days * per_arm_per_day), design.alpha)},
        "result": _test(df),
        "srm": {"n_control": n_c, "n_treatment": n_t, "chi2": chi2, "p_value": srm_p, "alarm": srm_p < SRM_ALARM},
        "srm_tracking_bug": {"lost_share_of_non_activated": LOST_SHARE, "n_control": b_c, "n_treatment": b_t,
                             "chi2": b_chi2, "p_value": b_p, "alarm": b_p < SRM_ALARM,
                             "biased_result": _test(buggy)},
        "funnel": funnel.to_dict(orient="records"),
        "daily_looks": looks,
        "replays": replays(design),
        "peeking": aa_tests(design).as_dict(),
    }


def _round(obj, digits: int = 6):
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {k: _round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, digits) for v in obj]
    return obj


def write(path: Path = RESULTS) -> dict:
    out = _round(analyse())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def readout(r: dict) -> str:
    d, res, s, b, pk = r["design"], r["result"], r["srm"], r["srm_tracking_bug"], r["peeking"]
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    pp = lambda x: f"{100 * x:+.1f} pp"  # noqa: E731
    return "\n".join([
        f"Design   {d['sample_size_per_arm']:,} accounts per arm to detect {pp(d['planted_lift'])} on "
        f"{pct(d['p_control'])} at alpha {d['alpha']}, power {d['power']} ({d['days_needed']} days; "
        f"planned {d['days']} days, power {pct(d['power_at_planned_size'])})",
        f"Result   control {pct(res['rate_control'])} (n={res['n_control']:,}), treatment "
        f"{pct(res['rate_treatment'])} (n={res['n_treatment']:,}): {pp(res['diff'])}, 95% CI "
        f"{pp(res['ci_low'])} to {pp(res['ci_high'])}, p = {res['p_value']:.4f}  [planted {pp(d['planted_lift'])}]",
        f"Replays  same design run {r['replays']['runs']:,} times: significant in {pct(r['replays']['significant'])}, "
        f"95% CI covers the planted effect in {pct(r['replays']['ci_covers_planted'])}",
        f"SRM      split {s['n_control']:,} / {s['n_treatment']:,}, p = {s['p_value']:.3f} -> "
        f"{'ALARM' if s['alarm'] else 'ok'}",
        f"SRM bug  {pct(b['lost_share_of_non_activated'])} of non-activating treatment accounts unlogged: split "
        f"{b['n_control']:,} / {b['n_treatment']:,}, p = {b['p_value']:.2g} -> {'ALARM' if b['alarm'] else 'missed'}; "
        f"the biased readout would claim {pp(b['biased_result']['diff'])}",
        f"Peeking  {pk['n_tests']:,} A/A tests: false positives {pct(pk['false_positive_fixed'])} testing once, "
        f"{pct(pk['false_positive_peeking'])} testing daily and stopping at the first p < {pk['alpha']}",
    ])
