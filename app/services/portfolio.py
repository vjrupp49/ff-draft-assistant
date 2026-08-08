"""
Markowitz-style risk-adjusted roster valuation.

This is the value function later components (Shapley, a future chunk)
attribute credit against -- built here, not there, so Shapley has
something stable to work with instead of being redone once risk-
adjustment lands. app/services/mcts.py's rollout reward now calls this
module instead of simulation.py's raw mean (see mcts.py's REWARD SIGNAL
note).

WHY THIS MATTERS FOR THIS LEAGUE: 6 of this league's 10 teams make the
playoffs (app/config.py NUM_TEAMS). That's a meaningfully risk-sensitive
format -- a boom/bust roster that maximizes mean points isn't obviously
better than a more consistent roster with a slightly lower mean, and
nothing upstream of this module (simulation.py's raw mean, vbd.py's point
estimates) can tell the two apart. This module is what makes that
distinction possible.

OBJECTIVE: risk_adjusted_score = E[roster points] - RISK_AVERSION * Var[roster points]
-- the standard Markowitz (1952) mean-variance utility, using the FULL
roster covariance matrix (not each player's variance in isolation),
computed directly from simulation.py's correlated Monte Carlo draws. A
roster stacked with same-team players (Chunk 3's team-correlation
modeling) is correctly penalized for its ADDED covariance-driven risk, not
just the sum of each player's own individual spread.

WHY EMPIRICAL COVARIANCE FROM SIMULATED DRAWS, NOT AN ANALYTICAL FORMULA:
simulation.py already draws every player in a roster within ONE shared rng
context per call, with same-team players sharing a correlated "game
script" shock (see that module's CORRELATION SIMPLIFICATION note). Rather
than re-deriving a covariance matrix analytically from that model (risking
drift from what simulation.py actually implements), this module computes
the empirical covariance matrix directly from the simulated season-total
arrays via numpy.cov -- whatever correlation structure simulation.py
produces is exactly what gets priced here, by construction, with no
duplicated logic to keep in sync.

RISK_AVERSION DEFAULT -- flat and moderate, NOT adjusted by projected
league standings position (an idea worth naming: a team projected to
finish outside the top 6 arguably wants MORE variance, since consistency
only helps a team that's already going to make the cut, while a projected
top-3 team might rationally want to minimize variance and protect its
position). That standings-aware version isn't built here because acting on
it requires knowing where a roster is LIKELY to finish relative to the
other 9 teams -- which needs full-league standings simulation (schedule +
all 10 rosters + matchup resolution). That's explicitly Phase 2 scope (the
"playoff odds simulator" -- see simulation.py's SCOPE note, which
deliberately excludes schedule/matchup modeling from Phase 1). Building a
standings-position proxy here with no real standings data behind it would
mean faking a number now and redoing this once Phase 2 actually exists to
justify one. Shipping a flat default and exposing `risk_aversion` as a
parameter lets a future Phase 2 component pass in a higher/lower value
once it can actually compute "am I a bubble team or a top seed" -- this
module doesn't need to change when that happens.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.services.simulation import DEFAULT_NUM_SIMS, simulate_players

# Calibrated against this project's own observed roster variances (Chunk 3
# verification: a 3-player same-team-stacked roster had simulated variance
# ~5,900 vs. ~5,400 for a diversified roster of comparable mean -- see this
# chunk's own re-verification below for full-roster-scale numbers). At
# RISK_AVERSION=0.004, a ~5,000-point^2 variance gap between two
# comparable-mean rosters moves the risk-adjusted score by ~20 points --
# noticeable, comparable to a real difference in value between two
# draft-worthy players, without swamping mean differences outright.
# Recalibrate this constant if real roster sizes/variances in practice
# turn out very different from what was tested here.
DEFAULT_RISK_AVERSION = 0.004


def evaluate_roster(
    roster_players: list[dict[str, Any]],
    risk_aversion: float = DEFAULT_RISK_AVERSION,
    num_sims: int = DEFAULT_NUM_SIMS,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """
    Risk-adjusted value of a candidate roster: mean simulated season
    points minus `risk_aversion` * simulated season-point VARIANCE, using
    the full covariance structure across the roster (not each player's
    variance treated in isolation).

    Returns the risk-adjusted score plus the full mean/variance/covariance
    breakdown, so a caller (or a person debugging) can see WHY a roster
    scored the way it did, not just the final number.
    """
    if not roster_players:
        return {
            "risk_adjusted_score": 0.0,
            "mean": 0.0,
            "variance": 0.0,
            "stddev": 0.0,
            "naive_independent_variance": 0.0,
            "correlation_inflation": None,
            "risk_aversion": risk_aversion,
            "num_sims": num_sims,
            "players": [],
            "covariance_matrix": {"player_ids": [], "matrix": []},
        }

    per_player_totals = simulate_players(roster_players, num_sims=num_sims, seed=seed)
    player_ids = [p["player_id"] for p in roster_players]
    matrix = np.array([per_player_totals[pid] for pid in player_ids])  # shape (num_players, num_sims)

    means = matrix.mean(axis=1)
    if len(player_ids) > 1:
        # rowvar=True (default): each ROW is one player's simulated draws.
        # ddof=1 for the unbiased sample covariance estimator.
        cov = np.cov(matrix, rowvar=True, ddof=1)
    else:
        cov = np.array([[matrix.var(ddof=1)]])

    roster_mean = float(means.sum())
    roster_variance = float(cov.sum())  # variance of the SUM = 1^T * Cov * 1 -- covariance terms included
    roster_stddev = roster_variance**0.5
    naive_independent_variance = float(np.diag(cov).sum())  # variance if every player were uncorrelated
    correlation_inflation = (
        roster_stddev / (naive_independent_variance**0.5) if naive_independent_variance > 0 else None
    )

    risk_adjusted_score = roster_mean - risk_aversion * roster_variance

    return {
        "risk_adjusted_score": round(risk_adjusted_score, 1),
        "mean": round(roster_mean, 1),
        "variance": round(roster_variance, 1),
        "stddev": round(roster_stddev, 1),
        "naive_independent_variance": round(naive_independent_variance, 1),
        "correlation_inflation": round(correlation_inflation, 3) if correlation_inflation is not None else None,
        "risk_aversion": risk_aversion,
        "num_sims": num_sims,
        "players": [
            {
                "player_id": pid,
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "mean": round(float(means[i]), 1),
                "variance": round(float(cov[i, i]), 1),
            }
            for i, (pid, p) in enumerate(zip(player_ids, roster_players))
        ],
        "covariance_matrix": {
            "player_ids": player_ids,  # row/column order for `matrix` below
            "matrix": [[round(float(v), 1) for v in row] for row in cov],
        },
    }
