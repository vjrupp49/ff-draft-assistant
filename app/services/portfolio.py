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
roster into starters vs. bench, then applying a discount (see
BENCH_DISCOUNT_BASE/BENCH_DISCOUNT_DECAY below) to bench players'
contribution rather than dropping them to zero.

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
above.

CHUNK 10 FIX -- RANK-AWARE (DECAYING) BENCH DISCOUNT, NOT FLAT: Chunk 9's
full-draft simulation found a real problem with the flat version above --
QB rosters ended up glutted (5-8 of 15 spots at QB, in a league where only
2 can ever start). Root cause, confirmed directly rather than inferred: at
a real draft state (2 QBs already rostered), the 3rd QB candidate (Bo Nix,
raw 316.9 simulated points) survived its 0.35 discount (contributed 110.9)
and STILL beat the best non-QB alternative (George Kittle, raw 248.9,
discount 0.25, contributed 62.2). This isn't a mechanism bug -- the
discount fired exactly as designed -- it's that this league's scoring
gives even a mediocre backup-tier QB a raw point floor so far above
comparable WR/RB/TE bench options (an NFL-usage-pattern effect: a starting
QB touches the ball on ~100% of his team's offensive snaps, where even a
true WR1 shares targets with three or four teammates) that a single flat
haircut can't close the gap no matter how it's tuned -- lowering it enough
to stop the 3rd QB would only shift the exact same problem to the 4th,
5th, 6th QB, since the remaining alternatives get weaker at the same pace
QBs stay strong.

The fix: BENCH_DISCOUNT_DECAY. A bench player's discount is now
BASE[position] * DECAY[position]^(rank-1), where rank=1 is that roster's
single MOST valuable bench player at that position (by simulated mean),
rank=2 the next, etc. -- so it's not "how good is a bench QB" (a fixed
question with a fixed answer regardless of how many you already have),
it's "how good is THIS TEAM's Nth bench QB," which should fall fast past
the first realistic injury-replacement slot. Rank 1 covers the genuine
"one QB got hurt or is on bye" case; a 2nd, 3rd, 4th bench QB has
vanishingly small realistic season value (this team would need to lose
BOTH starters AND its first backup in short order), and the discount now
reflects that directly instead of asking a single constant to do
impossible double duty.
  - QB: BASE dropped 0.35 -> 0.15 (comfortably below the ~0.196 threshold
    that would have been needed just to flip the one exact case above,
    leaving margin for estimation noise) with DECAY=0.5 -- each
    additional bench QB is worth roughly half the previous one
    (0.15, 0.075, 0.0375, ...), converging toward negligible fast.
  - RB: checked directly, not assumed fine -- comparing raw simulated
    points at the SAME "still pretty good, not deep bench" tier (rank
    6-15 within position) that produced the QB problem: QB averages
    ~280pts there, RB ~227, WR ~253, TE ~171. RB sits meaningfully below
    QB but not close to TE, AND Chunk 9's actual roster outcomes never
    showed an RB glut (counts ranged 1, 4, 6, 7 across seeds/strategies,
    nothing like QB's consistent 5-8) -- because RB, unlike QB, has real
    STARTER capacity beyond its 2 dedicated slots (FLEX + SUPER_FLEX can
    absorb several more RBs as actual starters, not bench, before the
    discount is even reached; QB's hard cap is 2 slots total, full stop).
    So RB's BASE stays at 0.35 (the classic handcuff value is real and
    already reasonably priced), but gets a mild DECAY=0.7 added as a
    defensive measure for the genuinely-excess case (a 6th/7th+ RB beyond
    what any realistic flex rotation would use) -- precautionary, not a
    response to an observed failure the way QB's fix is.
  - WR: DECAY=1.0 (unchanged, flat) -- no evidence from Chunk 9 of a
    problem at this position, so no speculative change; only touch a
    constant when a real failure or a directly-confirmed risk motivates
    it, consistent with how every other calibration in this project has
    been handled.
  - TE: DECAY=1.0 at the time of Chunk 9 (unchanged, flat) for the exact
    same "no evidence, don't touch it" reason WR was left alone -- SEE
    CHUNK 33 FIX BELOW for why that stopped being true.

CHUNK 33 FIX -- TE'S FLAT BENCH DECAY STOPPED BEING SAFE POST-CHUNK-30:
Chunk 31/32 confirmed a real, reproducible TE glut (5-seed sweep: TE
median 4 vs league median 2; a real live mock draft: 5 TE/2 WR final
roster) that Chunk 20's FLEX_CONCENTRATION_DISCOUNT (below) does NOT
explain -- diagnosed directly (not assumed) by inspecting actual drafted
rosters via `evaluate_roster`'s own per-player breakdown: in 4 of 5 Chunk
31 sweep seeds, only ONE TE per roster ever reaches flex-pool-STARTER
status (flex_rank=1, which FLEX_CONCENTRATION_DISCOUNT never touches --
it only discounts flex_rank>=2). The other 2-4 "extra" TEs per roster are
BENCH players, and TE's BENCH_DISCOUNT_DECAY was still 1.0 (flat) --
exactly the QB-glut failure mode Chunk 10 already fixed once, just at a
different position: real 2025 elite-TE production (Chunk 30's migration
making Trey McBride et al. visible for the first time, confirmed a
genuine tier effect in Chunk 31 task 4, not McBride-specific) now gives a
BENCH TE's raw points a high enough floor that even a flat 0.25 haircut
doesn't stop MCTS from stockpiling a 2nd/3rd/4th one -- the same
"no realistic season value past the first bench slot" argument Chunk 10
made for QB applies here now too.

FIX, CALIBRATED (5-seed sweep, slot 7, draft_score strategy, same
methodology as Chunk 6's risk_aversion sweep -- see this chunk's report
for the full table): BASE stays 0.25 (the first bench TE is a real,
legitimately-priced hedge, same reasoning as RB keeping its base) --
DECAY swept 1.0/0.7/0.5/0.3/0.15: TE median only reaches league parity
(2, matching the other 9 teams) at DECAY<=0.3, with 0.3 and 0.15
producing identical results (diminishing returns below 0.3, so 0.3 was
kept rather than going further with no additional benefit). Explicitly
checked (Chunk 20 precedent -- a flat all-position version of the FLEX
discount once caused a NEW WR shortage) for a new regression elsewhere:
RB stayed at deviation +1.0 (never flagged) across the entire sweep;
FLEX_CONCENTRATION_DISCOUNT_BASE/DECAY (TE) deliberately left UNTOUCHED
at their Chunk 20 values -- tightening them further, tested directly
alongside this fix, pushed RB to a NEW +2.0 deviation (the same
overcorrection failure mode, confirmed empirically, not assumed) for no
additional TE benefit once the bench-decay fix is in place. The
pre-existing WR shortage (present before this fix too, per Chunk 30/31)
improved (-3.0 -> -2.0 deviation) but was not fully resolved by this
fix -- left open, flagged for a future chunk, not force-fit here.
`bench_discount_base`/`bench_discount_decay` are exposed as parameters so
a future Phase 2 component can replace these with calibrated numbers
without this module's interface changing.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.services.simulation import DEFAULT_NUM_SIMS, simulate_players
from app.services.vbd import allocate_roster_starters, allocate_roster_starters_with_flex_ranks

# BASE: fraction of a BENCH player's simulated points that count toward
# roster value for that position's SINGLE most valuable bench player
# (starters always count at 100%, rank irrelevant). DECAY: how much that
# fraction shrinks for each additional bench player at the same position
# beyond the first (rank 2, 3, ...) -- see the CHUNK 10 FIX section above
# for the full reasoning behind each value.
BENCH_DISCOUNT_BASE: dict[str, float] = {
    "QB": 0.15,
    "RB": 0.35,
    "WR": 0.20,
    "TE": 0.25,
}
BENCH_DISCOUNT_DECAY: dict[str, float] = {
    "QB": 0.5,
    "RB": 0.7,
    "WR": 1.0,
    "TE": 0.3,  # CHUNK 33: was 1.0 (flat) -- see CHUNK 33 FIX note above
}
DEFAULT_BENCH_DISCOUNT_BASE = 0.25  # fallback base for any position missing from the dict above
DEFAULT_BENCH_DISCOUNT_DECAY = 1.0  # fallback decay (flat, no rank-based reduction)

# CHUNK 20 FIX -- FLEX-SLOT CONCENTRATION DISCOUNT: found via a real live
# draft (Chunk 19) that this project's own recommendations produced a
# QB=1/TE=8 final roster -- worse than the original Chunk 12/13 bug, via a
# genuinely different mechanism. Root-caused, not assumed (see Chunk 20's
# report for the full trace): every individual TE pick was a real,
# defensible near-tie at the time -- the pre-fix Chunk 13 bug (blind
# context-free rollout confidently, wrongly dismissing a clearly-better
# QB) was NOT reproducing. Confirmed directly instead: nothing penalized
# a STARTER-classified player for sharing the SAME small FLEX+SUPER_FLEX
# pool with same-position teammates -- a roster with 4 TEs each
# individually "starting" via that shared pool was valued identically to
# one with 4 different positions each holding one slot, even though the
# former is a far less diversified, riskier construction (in a real
# season, at most 1-2 of those 4 TEs can start in any given week; the
# other 2-3 are functionally bench that week despite being nominally
# "starters" here). This is DIFFERENT from the CHUNK 10 FIX above (that's
# about BENCH players, players who mathematically CAN'T start at all);
# this is about STARTER-classified players competing for the same pool.
#
# Confirmed via direct A/B (Chunk 20 Task 3, replaying Chunk 19's real
# pick 71): the best available QB's own one-step marginal value (301.65)
# clearly beat the eventually-picked TE's (247.73) by 54 points -- a
# decisive gap, not a real near-tie -- yet the full MCTS lookahead
# (mcts.py) washed this into a near-exact statistical tie (2606.7 vs
# 2606.1), because its own roster-aware rollout continuation
# (_roster_aware_pick) shares this SAME blind spot and kept assuming
# "I'll fix the QB situation on a later simulated pick" -- an assumption
# that, in the REAL draft that actually unfolded, never once came true.
#
# NOT applied to compute_replacement_levels' league-wide math (vbd.py) --
# Chunk 20 Task 1 found that calculation is working as designed (this
# league's real TE-premium scoring legitimately lets top TEs earn a
# larger-than-naive share of league-wide FLEX demand; QB's own
# SUPER_FLEX-driven ~20-startable-QBs scarcity is ALSO already correctly
# reflected there). This is specifically a ROSTER-level portfolio-
# construction gap, priced here, not a projection or league-wide-scarcity
# error.
#
# CALIBRATION (a documented judgment call, not fit to data -- same
# project convention as BENCH_DISCOUNT_BASE/DECAY above): the FIRST
# same-position player seated via the shared FLEX+SUPER_FLEX pool gets NO
# discount (1.0) -- that's completely normal, often optimal, roster
# construction (e.g. one elite pass-catching TE legitimately holding a
# flex slot). The SECOND+ same-position occupant of that SAME shared pool
# is what this fix prices.
#
# POSITION-SPECIFIC, NOT ONE FLAT SCHEDULE -- found the hard way, not
# assumed: the first version of this fix used one generic schedule
# (0.5/0.6) for every position. Re-validating against the Chunk 9 harness
# (Chunk 20 Task 5) surfaced a NEW regression that flat version caused --
# WR ended up under league median (-2.0 deviation, crossing this
# project's own >1 threshold) that hadn't existed before. Root cause:
# Tasks 1-3's entire investigation found and confirmed a TE-SPECIFIC
# problem (TE-premium scoring inflating raw points enough to win the
# shared pool repeatedly) -- applying the same aggressive discount to
# every position was untested overreach beyond what the evidence actually
# supported, the exact mistake Chunk 10's own precedent warns against
# ("only touch a constant when a real failure or a directly-confirmed
# risk motivates it" -- that chunk left WR/TE bench discount flat for
# lack of evidence; this fix now follows that same discipline). QB is
# structurally exempt regardless of its entry here: this league's
# SUPER_FLEX count is 1, so `_allocate_starters`'s own qb_seated cap
# means a QB's flex_rank can never exceed 1 in the first place -- a 2nd+
# QB simply can't enter the shared pool at all, so no QB entry is even
# needed. RB defaults to no discount (1.0) for the same reason as WR: no
# Task 1-3 evidence of an RB-specific version of this problem, so no
# speculative change -- revisit if a future chunk finds real evidence.
FLEX_CONCENTRATION_DISCOUNT_BASE: dict[str, float] = {
    "TE": 0.5,
}
FLEX_CONCENTRATION_DISCOUNT_DECAY: dict[str, float] = {
    "TE": 0.6,
}
DEFAULT_FLEX_CONCENTRATION_DISCOUNT_BASE = 1.0  # no discount for positions not listed above -- no evidence of a problem there
DEFAULT_FLEX_CONCENTRATION_DISCOUNT_DECAY = 1.0


def flex_concentration_discount_for(position: Optional[str], flex_rank: int) -> float:
    """
    The discount for a STARTER seated via the shared FLEX+SUPER_FLEX pool
    (see vbd.py's `allocate_roster_starters_with_flex_ranks`), holding
    `flex_rank` (1-indexed, 1 = best) among same-position teammates ALSO
    seated via that same shared pool. rank=1 -> 1.0 (no discount) for
    every position. rank=2+ only actually discounts positions listed in
    FLEX_CONCENTRATION_DISCOUNT_BASE (currently just TE -- see that
    dict's docstring for why the others default to no discount).
    """
    if flex_rank <= 1:
        return 1.0
    base = FLEX_CONCENTRATION_DISCOUNT_BASE.get(position, DEFAULT_FLEX_CONCENTRATION_DISCOUNT_BASE)
    decay = FLEX_CONCENTRATION_DISCOUNT_DECAY.get(position, DEFAULT_FLEX_CONCENTRATION_DISCOUNT_DECAY)
    return base * (decay ** (flex_rank - 2))


def compute_bench_ranks(
    roster_players: list[dict[str, Any]],
    starter_ids: set[str],
    per_player_totals: dict[str, np.ndarray],
) -> dict[str, int]:
    """
    Returns {player_id: rank} for every BENCH player in `roster_players`
    (starters are omitted -- they're never rank-discounted). rank=1 is
    that position's single most valuable bench player on THIS roster (by
    simulated mean), rank=2 the next-best, etc. -- feeds the decaying
    discount in `bench_discount_for` so a team's 2nd+ bench player at a
    position is worth less than its 1st, not a flat number regardless of
    how many are stashed.
    """
    bench_by_position: dict[str, list[str]] = {}
    for p in roster_players:
        pid = p["player_id"]
        if pid in starter_ids:
            continue
        bench_by_position.setdefault(p.get("position"), []).append(pid)

    ranks: dict[str, int] = {}
    for pids in bench_by_position.values():
        pids.sort(key=lambda pid: -float(per_player_totals[pid].mean()))
        for i, pid in enumerate(pids, start=1):
            ranks[pid] = i
    return ranks


def bench_discount_for(
    position: Optional[str],
    rank: int,
    base_by_position: Optional[dict[str, float]] = None,
    decay_by_position: Optional[dict[str, float]] = None,
) -> float:
    """The discount for a bench player at `position` holding rank `rank` (1-indexed, 1 = most valuable)."""
    base_by_position = base_by_position or BENCH_DISCOUNT_BASE
    decay_by_position = decay_by_position or BENCH_DISCOUNT_DECAY
    base = base_by_position.get(position, DEFAULT_BENCH_DISCOUNT_BASE)
    decay = decay_by_position.get(position, DEFAULT_BENCH_DISCOUNT_DECAY)
    return base * (decay ** (rank - 1))


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
    bench_discount_base: Optional[dict[str, float]] = None,
    bench_discount_decay: Optional[dict[str, float]] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """
    Risk-adjusted value of a candidate roster: mean simulated season
    points minus `risk_aversion` * simulated season-point VARIANCE, using
    the full covariance structure across the roster (not each player's
    variance treated in isolation) -- with BENCH players' contribution
    discounted (see module docstring) rather than counted equally with
    starters, and that discount decaying for a team's 2nd+ bench player at
    the same position (see CHUNK 10 FIX). Starters/bench are determined by
    app.services.vbd.allocate_roster_starters against this league's actual
    SUPER_FLEX/FLEX roster structure.

    Returns the risk-adjusted score plus the full mean/variance/covariance
    breakdown (including each player's starter/bench status, rank, and the
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

    base_by_position = bench_discount_base or BENCH_DISCOUNT_BASE
    decay_by_position = bench_discount_decay or BENCH_DISCOUNT_DECAY
    starter_ids, flex_ranks = allocate_roster_starters_with_flex_ranks(roster_players)

    per_player_totals = simulate_players(roster_players, num_sims=num_sims, seed=seed)
    player_ids = [p["player_id"] for p in roster_players]

    bench_ranks = compute_bench_ranks(roster_players, starter_ids, per_player_totals)

    # Bench players' simulated draws are scaled by their position's
    # rank-decayed discount BEFORE computing mean/covariance -- scaling a
    # random variable by a constant c scales its variance by c^2 and its
    # covariance with everyone else by c, so this discounts a bench
    # player's contribution to BOTH the roster's expected value AND its
    # risk consistently, not just the final point estimate. CHUNK 20 FIX:
    # a starter seated via the shared FLEX+SUPER_FLEX pool (not a
    # dedicated slot) gets the SAME treatment if a same-position teammate
    # also shares that pool -- see FLEX_CONCENTRATION_DISCOUNT_BASE above.
    contributed_totals: dict[str, np.ndarray] = {}
    player_discounts: dict[str, float] = {}
    for p in roster_players:
        pid = p["player_id"]
        if pid in starter_ids:
            discount = flex_concentration_discount_for(p.get("position"), flex_ranks[pid]) if pid in flex_ranks else 1.0
        else:
            discount = bench_discount_for(p.get("position"), bench_ranks[pid], base_by_position, decay_by_position)
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
                "bench_rank": bench_ranks.get(pid),
                "bench_discount_applied": None if pid in starter_ids else round(player_discounts[pid], 4),
                "flex_position_rank": flex_ranks.get(pid),
                "flex_concentration_discount_applied": (
                    round(player_discounts[pid], 4) if pid in flex_ranks and flex_ranks[pid] > 1 else None
                ),
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
