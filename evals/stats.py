"""Statistics for the evals: confidence intervals and significance tests.

An eval number without an interval is a guess dressed up as a measurement: 0.99 hit@3 over
110 questions and over 6 questions are very different claims. Everything here is stdlib only.

- wilson_interval: proportions (hit@k, attack-detection rate). Behaves at 0% and 100%,
  unlike the normal approximation, which gives zero-width intervals there.
- bootstrap_ci: any statistic of per-question scores (MRR, nDCG, a RAGAS metric).
- paired_bootstrap: the difference between two configurations scored on the SAME questions.
  Pairing matters: the questions are the same, so most of the variance cancels.
- mcnemar_exact: paired pass/fail comparison, exact binomial (no large-sample assumption).
"""
import math
import random
from collections.abc import Callable, Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = _mean,
                 n_boot: int = 5000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap interval. NaNs must be removed by the caller (and counted)."""
    if not values:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return (stats[int(n_boot * alpha / 2)], stats[min(n_boot - 1, int(n_boot * (1 - alpha / 2)))])


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_boot: int = 5000,
                     alpha: float = 0.05, seed: int = 0) -> dict:
    """Mean of (b - a) over the same items, its bootstrap interval, and whether the interval
    excludes zero. 'significant' is only a statement about THESE questions: it can't say a
    difference would hold on questions from a different distribution."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    diffs = [y - x for x, y in zip(a, b, strict=True)]
    lo, hi = bootstrap_ci(diffs, n_boot=n_boot, alpha=alpha, seed=seed)
    return {"mean_diff": _mean(diffs) if diffs else math.nan, "ci": (lo, hi),
            "significant": bool(diffs) and (lo > 0 or hi < 0)}


def mcnemar_exact(a_only: int, b_only: int) -> float:
    """Two-sided exact p-value for paired binary outcomes. a_only: items A got right and B
    got wrong; b_only: the reverse. Items both got right or both wrong carry no information."""
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


# ---------------------------------------------------------------- ranking metrics
def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, item in enumerate(ranked, 1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def hit_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(item in relevant for item in ranked[:k]) else 0.0


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG: rewards putting relevant documents earlier, and unlike
    hit@k distinguishes 'found at rank 1' from 'found at rank k'."""
    seen: set[str] = set()
    dcg = 0.0
    for i, item in enumerate(ranked[:k], 1):
        if item in relevant and item not in seen:  # a document counts once
            dcg += 1.0 / math.log2(i + 1)
            seen.add(item)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0
