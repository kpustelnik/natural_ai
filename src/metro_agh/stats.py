"""Comparing two algorithms' runs: rank-sum test, Holm correction, Vargha–Delaney A₁₂.

Runs of two algorithms are independent samples: the same seed gives each algorithm its own,
unrelated random stream, so nothing pairs a run of one with a run of the other. The test is
therefore the two-sided Wilcoxon rank-sum / Mann–Whitney U test, the p-values of the
comparisons against one reference are corrected with Holm's step-down method, and A₁₂ says
how large the difference is (Vargha and Delaney 2000; Derrac et al. 2011 for the practice).
Used by ``scripts/plot_experiments.py`` (algorithm tables) and ``scripts/plot_extra.py``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import mannwhitneyu


def a12(x, y) -> float:
    """P(X > Y) + ½ P(X = Y) for higher-is-better values (savings): the chance that a random
    run of X beats a random run of Y. 0.5 = no difference; ≥ 0.71 (or ≤ 0.29) a large effect,
    ≥ 0.64 medium, ≥ 0.56 small."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if not len(x) or not len(y):
        return math.nan
    greater = (x[:, None] > y[None, :]).sum()
    ties = (x[:, None] == y[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(x) * len(y)))


def effect(a: float) -> str:
    """Vargha–Delaney's words for |A₁₂ − 0.5|."""
    if math.isnan(a):
        return ""
    d = abs(a - 0.5)
    return "large" if d >= 0.21 else "medium" if d >= 0.14 else "small" if d >= 0.06 else "none"


def rank_sum(x, y) -> float:
    """Two-sided Mann–Whitney U p-value; NaN when a side has one run or both are constant
    and equal (deterministic algorithms: compare by A₁₂ only)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2 or len(y) < 2:
        return math.nan
    if np.ptp(np.concatenate([x, y])) == 0:
        return 1.0
    return float(mannwhitneyu(x, y, alternative="two-sided").pvalue)


def holm(p: list[float]) -> list[float]:
    """Holm–Bonferroni step-down adjusted p-values; NaN stays NaN and is not counted."""
    idx = sorted((i for i, v in enumerate(p) if not math.isnan(v)), key=lambda i: p[i])
    out = [math.nan] * len(p)
    running = 0.0
    for rank, i in enumerate(idx):
        running = max(running, min(1.0, (len(idx) - rank) * p[i]))
        out[i] = running
    return out
