import math
import random

import pytest

from evals.stats import (
    bootstrap_ci,
    hit_at_k,
    mcnemar_exact,
    ndcg_at_k,
    paired_bootstrap,
    recall_at_k,
    reciprocal_rank,
    wilson_interval,
)


def test_wilson_known_values():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.404, abs=0.002) and hi == pytest.approx(0.596, abs=0.002)
    lo, hi = wilson_interval(10, 10)  # all hits: not a zero-width interval at 1.0
    assert lo == pytest.approx(0.722, abs=0.002) and hi == 1.0
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.278, abs=0.002)


def test_wilson_shrinks_with_n_and_handles_empty():
    w_small = wilson_interval(9, 10)
    w_big = wilson_interval(90, 100)
    assert (w_big[1] - w_big[0]) < (w_small[1] - w_small[0])
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_bootstrap_ci_covers_the_true_mean_and_is_deterministic():
    rng = random.Random(1)
    data = [rng.gauss(0.8, 0.1) for _ in range(200)]
    lo, hi = bootstrap_ci(data, n_boot=2000)
    assert lo < 0.8 < hi and hi - lo < 0.05
    assert bootstrap_ci(data, n_boot=2000) == (lo, hi)  # fixed seed
    assert all(math.isnan(x) for x in bootstrap_ci([]))


def test_bootstrap_coverage_is_roughly_nominal():
    rng = random.Random(7)
    covered = 0
    trials = 150
    for t in range(trials):
        sample = [rng.gauss(0, 1) for _ in range(40)]
        lo, hi = bootstrap_ci(sample, n_boot=400, seed=t)
        covered += lo <= 0 <= hi
    assert 0.88 <= covered / trials <= 0.99  # nominal 95%


def test_paired_bootstrap_detects_a_real_shift_and_not_noise():
    rng = random.Random(3)
    base = [rng.random() for _ in range(100)]
    better = [x + 0.1 for x in base]  # consistently better on the same items
    r = paired_bootstrap(base, better)
    assert r["significant"] and r["mean_diff"] == pytest.approx(0.1) and r["ci"][0] > 0
    noise = [x + rng.gauss(0, 0.2) for x in base]
    assert not paired_bootstrap(base, noise)["significant"]
    with pytest.raises(ValueError):
        paired_bootstrap([1.0], [1.0, 2.0])


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(10, 2) == pytest.approx(0.0386, abs=0.0005)
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 10) == pytest.approx(0.00195, abs=0.0001)


def test_rank_metrics():
    ranked = ["a", "b", "c", "d"]
    assert reciprocal_rank(ranked, {"c"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(ranked, {"z"}) == 0.0
    assert hit_at_k(ranked, {"c"}, 2) == 0.0 and hit_at_k(ranked, {"c"}, 3) == 1.0
    assert recall_at_k(ranked, {"a", "z"}, 4) == 0.5
    # nDCG: relevant at rank 1 is perfect, at rank 3 is discounted, absent is zero
    assert ndcg_at_k(["a", "b"], {"a"}, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "y", "a"], {"a"}, 3) == pytest.approx(0.5)  # 1/log2(4)
    assert ndcg_at_k(["x", "y"], {"a"}, 3) == 0.0
    # a duplicate of the same relevant doc must not inflate the score above 1
    assert ndcg_at_k(["a", "a", "a"], {"a"}, 3) == pytest.approx(1.0)
