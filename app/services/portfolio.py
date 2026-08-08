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

CHUNK 6 FIX -- STARTER/BENCH LINEUP AWARENESS: this module originally
summed EVERY given player's simulated points equally, with no concept of
a starting lineup -- it couldn't distinguish a player who starts every
week from pure bench depth. That silently broke Shapley attribution (a
same-value player joining an already-deep position scored the same as one
filling a real starting gap, since the value function had no way to see
the difference) and was equally present in MCTS's reward, which uses this
same function. Fixed by reusing app.services.vbd's already-solved
SUPER_FLEX/FLEX starter-allocation logic (`allocate_roster_starters` --
the exact same algorithm that correctly solved the SUPERFLEX QB
replacement-level problem in Chunk 2, not reimplemented here) to split a
roster into starters vs. bench, then applying BENCH_VALUE_DISCOUNT (see
below) to bench players' contribution rather than dropping them to zero.

WHY NOT ZERO FOR BENCH: a bench RB2 handcuff or backup QB in a SUPER_FLEX
league has real injury-replacement and bye-week flexibility value even
though it isn't in this week's starting lineup. Valuing bench at exactly
zero would create the opposite distortion -- the system would then
undervalue reasonable bench-building entirely. Discounting (not zeroing)
bench contribution is a deliberate middle ground.

WHY THE DISCOUNT VARIES BY POSITION, NOT ONE FLAT NUMBER: how likely a
bench player is to actually matter in a real season differs a lot by
position in THIS league's specific format --
  - QB: this league's heavy SUPER_FLEX usage means a large share of teams
    are already starting 2 QBs (see vbd.py's QB replacement-level finding
    -- demand lands around ~2 QBs/team). A benched 3rd QB has a real
    chance of being needed on a bye week or after an injury to either
    starter. Higher discount.
  - RB: the classic "handcuff" position -- backup RBs are notoriously
    likely to be forced into must-start value after an injury to the
    starter ahead of them, more so than any other position. Higher
    discount.
  - WR: this league's deepest position (2 dedicated + the largest natural
    share of 3 FLEX slots) -- a benched WR is the LEAST likely bench
    asset to be forced into the lineup, since there's already the most
    competition/depth at the position. Lower discount.
  - TE: this league has ZERO dedicated TE slot at all (TE only reaches a
    lineup via FLEX/SUPER_FLEX, competing directly with RB/WR there) --
    real bye-week/matchup flexibility value exists, but less structural
    "forced into the lineup" pressure than RB/QB. Moderate discount.
This is a placeholder heuristic (values are a documented judgment call,
not fit to any real injury/bye-week data), explicitly NOT a real
season-long injury/bye model -- that level of realism needs actual season
data and is Phase 2 scope, same as the standings-aware risk_aversion idea
above. `bench_value_discount` is exposed as a parameter so a future
Phase 2 component can replace these numbers with calibrated ones without
this module's interface changing.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.services.simulation import DEFAULT_NUM_SIMS, simulate_players
from app.services.vbd import allocate_roster_starters

# Fraction of a BENCH player's simulated points that count toward roster
# value (starters always count at 100%). See the module docstring's WHY
# THE DISCOUNT VARIES BY POSITION section for the per-position reasoning
# -- QB/RB higher (SUPER_FLEX depth demand / classic handcuff value), WR
# lower (deepest position, least likely to be forced into a lineup), TE
# moderate (no dedicated slot, but real flex value). All four sit in the
# suggested 0.2-0.4 "meaningful partial credit, not near-zero, not
# near-full" band -- a documented placeholder judgment call, not fit to
# real injury/bye-week data (see docstring).
BENCH_VALUE_DISCOUNT: dict[str, float] = {
    "QB": 0.35,
    "RB": 0.35,
    "WR": 0.20,
    "TE": 0.25,
}
DEFAULT_BENCH_DISCOUNT = 0.25  # fallback for any position missing from the dict above

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
#
# CHUNK 6 SENSITIVITY CHECK (kept as-is; documenting the check rather than
# the constant, since it didn't change): Chunk 5 found a REALISTIC partial
# stack (2-of-3 shared team, e.g. a QB + one of his own pass-catchers) only
# moves the score by ~1 point at 0.004 -- small next to MCTS's own ~10-14
# point sampling noise. Swept 0.004/0.01/0.02/0.05/0.08 against both that
# partial-stack case and the EXTREME 5-of-5-same-team case: raising
# RISK_AVERSION enough to make a partial stack's penalty compete with
# MCTS's noise floor (~0.05-0.08) inflates the extreme case's penalty from
# -11 points to -288 to -468 points -- wildly disproportionate to the ~13
# point raw mean gap driving that comparison, and a parallel check (a
# modestly-wider-variance "unknown" player vs. a similar-mean steadier
# veteran) confirmed the same setting starts inverting variance-driven
# value ordering hard enough to bury a legitimately higher-mean pick under
# a lower-mean "safer" one. A partial stack genuinely doesn't carry much
# absolute risk at this scale -- that's a real finding, not a
# miscalibration -- and the fix for it not visibly moving MCTS's ranking
# belongs in reducing MCTS's OWN estimation noise (more iterations/sims),
# not in distorting this coefficient past what's defensible for pricing
# risk on its own terms. Left at 0.004.
DEFAULT_RISK_AVERSION = 0.004


def evaluate_roster(
    roster_players: list[dict[str, Any]],
    risk_aversion: float = DEFAULT_RISK_AVERSION,
    num_sims: int = DEFAULT_NUM_SIMS,
    bench_value_discount: Optional[dict[str, float]] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """
    Risk-adjusted value of a candidate roster: mean simulated season
    points minus `risk_aversion` * simulated season-point VARIANCE, using
    the full covariance structure across the roster (not each player's
    variance treated in isolation) -- with BENCH players' contribution
    discounted (see module docstring) rather than counted equally with
    starters. Starters/bench are determined by
    app.services.vbd.allocate_roster_starters against this league's actual
    SUPER_FLEX/FLEX roster structure.

    Returns the risk-adjusted score plus the full mean/variance/covariance
    breakdown (including each player's starter/bench status and the
    discount applied), so a caller (or a person debugging) can see WHY a
    roster scored the way it did, not just the final number.
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
            "starters": [],
            "bench": [],
            "players": [],
            "covariance_matrix": {"player_ids": [], "matrix": []},
        }

    discount_by_position = bench_value_discount or BENCH_VALUE_DISCOUNT
    starter_ids = allocate_roster_starters(roster_players)

    per_player_totals = simulate_players(roster_players, num_sims=num_sims, seed=seed)
    player_ids = [p["player_id"] for p in roster_players]

    # Bench players' simulated draws are scaled by their position's
    # discount BEFORE computing mean/covariance -- scaling a random
    # variable by a constant c scales its variance by c^2 and its
    # covariance with everyone else by c, so this discounts a bench
    # player's contribution to BOTH the roster's expected value AND its
    # risk consistently, not just the final point estimate.
    contributed_totals: dict[str, np.ndarray] = {}
    player_discounts: dict[str, float] = {}
    for p in roster_players:
        pid = p["player_id"]
        if pid in starter_ids:
            discount = 1.0
        else:
            discount = discount_by_position.get(p.get("position"), DEFAULT_BENCH_DISCOUNT)
        player_discounts[pid] = discount
        contributed_totals[pid] = per_player_totals[pid] * discount

    matrix = np.array([contributed_totals[pid] for pid in player_ids])  # shape (num_players, num_sims)
    raw_matrix = np.array([per_player_totals[pid] for pid in player_ids])  # undiscounted, for the per-player breakdown

    means = matrix.mean(axis=1)
    raw_means = raw_matrix.mean(axis=1)
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
        "starters": [pid for pid in player_ids if pid in starter_ids],
        "bench": [pid for pid in player_ids if pid not in starter_ids],
        "players": [
            {
                "player_id": pid,
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "is_starter": pid in starter_ids,
                "bench_discount_applied": None if pid in starter_ids else player_discounts[pid],
                "raw_mean": round(float(raw_means[i]), 1),
                "contributed_mean": round(float(means[i]), 1),
                "contributed_variance": round(float(cov[i, i]), 1),
            }
            for i, (pid, p) in enumerate(zip(player_ids, roster_players))
        ],
        "covariance_matrix": {
            "player_ids": player_ids,  # row/column order for `matrix` below
            "note": "reflects DISCOUNTED (starter/bench-weighted) values -- cov.sum() == variance above",
            "matrix": [[round(float(v), 1) for v in row] for row in cov],
        },
    }
