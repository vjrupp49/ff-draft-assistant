"""
Shared numerically-stable running statistics, for anywhere in this app
that accumulates a mean/variance estimate over many stochastic samples
(mcts.py's rollout rewards, shapley.py's permutation-sampled marginal
contributions).

Extracted here after mcts.py's Chunk 4.5 stability pass found that a
naive `sum(x^2)/n - mean^2` variance formula catastrophically cancels
when sample values sit far from zero (season-point-scale rewards, mean
~1000+) -- it reported a standard error ~15x too large. Welford's
algorithm only ever works with small deviations from the running mean, so
it doesn't have that cancellation problem, regardless of the samples'
absolute scale. Anything computing a standard error in this app should
use this, not re-derive its own -- see shapley.py for the second use.
"""

from __future__ import annotations

from typing import Optional


class WelfordAccumulator:
    """Online mean/variance tracker, numerically stable regardless of the recorded values' absolute scale."""

    __slots__ = ("visits", "_mean", "_m2")

    def __init__(self) -> None:
        self.visits = 0
        self._mean = 0.0
        self._m2 = 0.0

    def record(self, x: float) -> None:
        self.visits += 1
        delta = x - self._mean
        self._mean += delta / self.visits
        delta2 = x - self._mean
        self._m2 += delta * delta2

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def variance(self) -> Optional[float]:
        """Population variance of the recorded samples. None with 0 visits."""
        if self.visits == 0:
            return None
        return self._m2 / self.visits

    @property
    def stderr(self) -> Optional[float]:
        """Standard error of `mean`. None with fewer than 2 visits (undefined)."""
        if self.visits < 2:
            return None
        return (self._m2 / self.visits / self.visits) ** 0.5
