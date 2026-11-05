import math

import pytest

from experiments.stats import power, sample_size_per_arm, srm_test, two_proportion_test


def test_sample_size_matches_the_formula_by_hand():
    # 10% -> 12%, alpha 0.05 two-sided, power 0.8: (1.95996 + 0.84162)^2 * (0.09 + 0.1056) / 0.02^2 = 3838.1
    assert sample_size_per_arm(0.10, 0.02) == 3839
    # the design used in the readout: 30% -> 34%
    assert sample_size_per_arm(0.30, 0.04) == 2131


def test_sample_size_grows_with_smaller_effects_and_more_power():
    assert sample_size_per_arm(0.30, 0.02) > 3.9 * sample_size_per_arm(0.30, 0.04)
    assert sample_size_per_arm(0.30, 0.04, power=0.9) > sample_size_per_arm(0.30, 0.04)
    assert sample_size_per_arm(0.30, 0.04, alpha=0.01) > sample_size_per_arm(0.30, 0.04)


def test_power_at_the_planned_size_is_the_target():
    n = sample_size_per_arm(0.30, 0.04, power=0.8)
    assert power(0.30, 0.04, n) == pytest.approx(0.8, abs=0.002)
    assert power(0.30, 0.04, n // 4) < 0.35


def test_sample_size_rejects_impossible_rates():
    with pytest.raises(ValueError):
        sample_size_per_arm(0.98, 0.04)
    with pytest.raises(ValueError):
        sample_size_per_arm(0.30, 0.0)


def test_two_proportion_test_known_values():
    # 200/1000 vs 250/1000: pooled p = 0.225, se = sqrt(0.225 * 0.775 * 0.002) = 0.018675, z = 2.6774
    r = two_proportion_test(200, 1000, 250, 1000)
    assert r.diff == pytest.approx(0.05)
    assert r.relative_lift == pytest.approx(0.25)
    assert r.z == pytest.approx(2.6774, abs=1e-3)
    assert r.p_value == pytest.approx(0.00742, abs=1e-4)
    assert r.significant
    # unpooled Wald interval: 0.05 +- 1.96 * sqrt(0.16/1000 + 0.1875/1000)
    half = 1.959964 * math.sqrt(0.16 / 1000 + 0.1875 / 1000)
    assert (r.ci_low, r.ci_high) == pytest.approx((0.05 - half, 0.05 + half))


def test_no_difference_is_not_significant():
    r = two_proportion_test(300, 1000, 300, 1000)
    assert r.z == 0 and r.p_value == pytest.approx(1.0)
    assert r.ci_low < 0 < r.ci_high and not r.significant


def test_srm_balanced_split_passes_and_skewed_split_alarms():
    assert srm_test(5000, 5000) == (0.0, pytest.approx(1.0))
    chi2, p = srm_test(5000, 4600)  # 8% fewer in treatment
    assert chi2 == pytest.approx(2 * 200**2 / 4800)
    assert p < 0.001
    # 3% fewer is suspicious but under the usual 0.001 alarm at this size
    assert 0.001 < srm_test(5000, 4700)[1] < 0.01
    # a deliberate 80/20 design is not a mismatch
    assert srm_test(2000, 8000, treatment_share=0.8)[1] == pytest.approx(1.0)
