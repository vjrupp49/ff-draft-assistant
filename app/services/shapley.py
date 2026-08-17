"""
Shapley value attribution: how much does adding player X to THIS SPECIFIC
roster actually change its risk-adjusted value (app.services.portfolio),
holding everyone else fixed -- the rigorous version of "positional need"
from the project's original vision. This answers a genuinely different
question than VBD (context-free player value, ignores the rest of the
roster entirely) or portfolio.py's roster-level score (one number for the
whole roster, no per-player attribution): a same-quality player can have a
HIGHER or LOWER Shapley value depending on what's ALREADY on the roster
(see this chunk's verification for a concrete "joining a deep position vs.
a thin position" demonstration).

EXACT SHAPLEY IS INFEASIBLE HERE: the exact formula requires evaluating
the value function on every one of a roster's 2^n subsets (n=15 for a
full roster -> 32,768 evaluations, each a Monte-Carlo-based covariance
computation) -- not viable at any reasonable request latency. This uses
the standard practical alternative: Monte Carlo approximation via random
permutation sampling (ApproShapley). For each of NUM_PERMUTATIONS sampled
random orderings of the roster, every player's marginal contribution is
`value(players before them in this ordering, plus them) - value(players
before them)`; averaging a player's marginal across permutations converges
to their true Shapley value as the sample count grows.

EFFICIENCY -- ONE JOINT SIMULATION, NOT ONE PER SUBSET: naively this would
call portfolio.evaluate_roster() once per subset (NUM_PERMUTATIONS *
(n+1) calls), each independently re-simulating every player in that
subset from scratch -- hugely redundant, and each fresh re-simulation
would also inject its own independent sampling noise between adjacent
subsets, muddying the marginal-contribution signal. Instead, this module
draws each player's simulated season ONCE per roster (one
app.services.simulation.simulate_players call, reused across every
permutation and every prefix within them) and, for each prefix within a
permutation, re-sums the ALREADY-DRAWN per-player arrays for that prefix
(see `_weighted_value` -- as of Chunk 7, this also re-derives which of
the prefix's OWN players are starters vs. bench each time, since that's a
property of the subset, not a fixed label; see the CHUNK 7 note below)
and applies portfolio.py's exact objective directly to that sum. Every
subset evaluation within a run is still drawn from the SAME
internally-consistent model of how these specific players' outcomes
co-vary -- the efficiency win is "one simulation batch instead of
thousands of independent re-simulations," not "O(1) work per prefix"
(re-summing a prefix from scratch is O(n) in the prefix size, so O(n^2)
per permutation overall -- negligible at roster-sized n, see this
chunk's measured runtime).

A useful side effect of this construction: for ANY single permutation, its
players' marginal contributions telescope EXACTLY to value(full roster) -
value(empty roster) = value(full roster) (value(empty) = 0 by
construction), regardless of the ordering. Since summing-then-averaging
and averaging-then-summing commute, the SUM of the NUM_PERMUTATIONS-
averaged per-player Shapley estimates equals value(full roster) with NO
Monte Carlo error at all (see `efficiency_check_diff` in
`evaluate_shapley`'s output, and this chunk's verification) -- a genuine
correctness check, not an approximate one, and a direct benefit of
computing every subset from one shared simulation instead of independent
per-subset draws.

SAMPLE COUNT: NUM_PERMUTATIONS trades runtime against the standard error
on each player's estimate -- the same trade-off mcts.py's ITERATIONS
makes, reported the same way (standard error per player, not just a point
estimate -- see `evaluate_shapley`). Unlike mcts.py, where each iteration
IS a fresh simulation call, a permutation here only costs O(n) cheap array
sums (the expensive part -- drawing each player's simulated season --
happens once, up front, regardless of NUM_PERMUTATIONS), so this default
can afford to be generous.

STABILITY (per the Chunk 4.5 lesson on mcts.py, applied here from the
start rather than rediscovered): per-player running mean/variance uses
app.services._stats.WelfordAccumulator (numerically stable regardless of
reward scale), and two players whose Shapley estimates are statistically
indistinguishable are flagged rather than presented as a confident
ranking, mirroring mcts.py's near-tie handling.

CHUNK 7 -- STARTER/BENCH AWARENESS, RECOMPUTED PER PREFIX: portfolio.py
gained starter/bench-aware valuation in Chunk 7 (bench players' simulated
points are discounted, not counted equally with starters -- see that
module). This module's inline `_prefix_value` re-derivation of
portfolio.py's objective (see the EFFICIENCY section above for why it's
inlined rather than calling evaluate_roster()) has to apply that same
discount to stay consistent -- and critically, a player's starter/bench
status must be recomputed FOR EACH PREFIX, not fixed once for the final
roster. Whether a player is a "starter" is a property of a SPECIFIC
subset (it depends on who else is in that subset competing for the same
FLEX/SUPER_FLEX slots), not a fixed label -- the same player can be a
starter in a small early prefix and get bumped to bench once a
permutation adds someone better later, which is exactly the scarcity
signal Shapley is supposed to capture. The efficiency property (Shapley
values sum to the roster's total value) still holds EXACTLY under this --
it's a generic property of summing a telescoping chain of value
differences along one ordering, true for ANY consistently-evaluated value
function, discount-aware or not.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.services._stats import WelfordAccumulator
from app.services.portfolio import (
    BENCH_DISCOUNT_BASE,
    BENCH_DISCOUNT_DECAY,
    DEFAULT_RISK_AVERSION,
    bench_discount_for,
    compute_bench_ranks,
    flex_concentration_discount_for,
)
from app.services.simulation import DEFAULT_NUM_SIMS, simulate_players
from app.services.vbd import allocate_roster_starters_with_flex_ranks

NUM_PERMUTATIONS = 200

# Same threshold/reasoning as mcts.py's NEAR_TIE_Z -- a judgment-call
# multiple of combined standard error, not a formal hypothesis test (no
# multiple-comparison correction).
NEAR_TIE_Z = 1.5

SHAPLEY_NUM_SIMS = DEFAULT_NUM_SIMS  # the one shared simulation batch every permutation reuses


def _weighted_value(
    prefix_players: list[dict[str, Any]],
    per_player_totals: dict[str, np.ndarray],
    risk_aversion: float,
    base_by_position: dict[str, float],
    decay_by_position: dict[str, float],
    num_sims: int,
) -> float:
    """
    portfolio.py's mean-minus-variance-penalty objective, applied to a
    specific subset of the roster -- determines THIS subset's own
    starters/bench (see module docstring on why that must be re-derived
    per subset, not inherited from the full roster) AND this subset's own
    bench ranks (Chunk 10 -- a player's rank among same-position bench
    players is also a property of the subset, same reasoning as
    starter/bench itself), then sums each player's simulated draws at full
    value (starter, unless it's sharing the FLEX+SUPER_FLEX pool with a
    same-position teammate within THIS subset -- Chunk 20, same re-derive-
    per-subset reasoning as bench rank) or rank-decayed discounted value
    (bench) before computing mean/variance, exactly mirroring
    portfolio.evaluate_roster's math.
    """
    starter_ids, flex_ranks = allocate_roster_starters_with_flex_ranks(prefix_players)
    bench_ranks = compute_bench_ranks(prefix_players, starter_ids, per_player_totals)
    weighted_sum = np.zeros(num_sims)
    for p in prefix_players:
        pid = p["player_id"]
        if pid in starter_ids:
            discount = flex_concentration_discount_for(p.get("position"), flex_ranks[pid]) if pid in flex_ranks else 1.0
            weighted_sum += per_player_totals[pid] * discount
        else:
            discount = bench_discount_for(p.get("position"), bench_ranks[pid], base_by_position, decay_by_position)
            weighted_sum += per_player_totals[pid] * discount

    mean = float(weighted_sum.mean())
    variance = float(weighted_sum.var(ddof=1)) if weighted_sum.size > 1 else 0.0
    return mean - risk_aversion * variance


def evaluate_shapley(
    roster_players: list[dict[str, Any]],
    risk_aversion: float = DEFAULT_RISK_AVERSION,
    num_permutations: int = NUM_PERMUTATIONS,
    num_sims: int = SHAPLEY_NUM_SIMS,
    bench_discount_base: Optional[dict[str, float]] = None,
    bench_discount_decay: Optional[dict[str, float]] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """
    Per-player approximate Shapley value against portfolio.py's
    risk-adjusted, starter/bench-aware objective, for THIS specific
    roster. Returns each player's estimate, standard error, and whether
    it's statistically indistinguishable from the top-ranked player --
    plus the roster's actual total risk-adjusted value, so a caller can
    check the Shapley values against the "efficiency" property (they
    should sum to it -- see the module docstring for why that's exact
    here, not approximate).
    """
    if not roster_players:
        return {
            "players": [],
            "sum_of_shapley_values": 0.0,
            "roster_value": 0.0,
            "efficiency_check_diff": 0.0,
            "num_permutations": 0,
            "num_sims": num_sims,
            "risk_aversion": risk_aversion,
        }

    base_by_position = bench_discount_base or BENCH_DISCOUNT_BASE
    decay_by_position = bench_discount_decay or BENCH_DISCOUNT_DECAY
    rng = np.random.default_rng(seed)

    player_ids = [p["player_id"] for p in roster_players]
    n = len(player_ids)
    per_player_totals = simulate_players(roster_players, num_sims=num_sims, seed=seed)

    accumulators = {pid: WelfordAccumulator() for pid in player_ids}

    order_indices = np.arange(n)
    for _ in range(num_permutations):
        rng.shuffle(order_indices)
        prev_value = 0.0  # value of the empty set is 0 by construction
        for k in range(1, n + 1):
            prefix_players = [roster_players[i] for i in order_indices[:k]]
            value = _weighted_value(
                prefix_players, per_player_totals, risk_aversion, base_by_position, decay_by_position, num_sims
            )
            newest_pid = player_ids[order_indices[k - 1]]
            accumulators[newest_pid].record(value - prev_value)
            prev_value = value

    results = []
    for p in roster_players:
        pid = p["player_id"]
        acc = accumulators[pid]
        results.append(
            {
                "player_id": pid,
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "shapley_value": round(acc.mean, 2),
                "stderr": round(acc.stderr, 3) if acc.stderr is not None else None,
            }
        )

    results.sort(key=lambda r: r["shapley_value"], reverse=True)

    # Flag players statistically indistinguishable from the top-ranked
    # player -- mirrors mcts.py's near-tie handling, same NEAR_TIE_Z spirit.
    leader = results[0]
    leader_se = leader["stderr"] or 0.0
    for r in results:
        r_se = r["stderr"] or 0.0
        combined_se = (leader_se**2 + r_se**2) ** 0.5
        margin = leader["shapley_value"] - r["shapley_value"]
        r["within_noise_of_leader"] = r is leader or (combined_se > 0 and margin <= NEAR_TIE_Z * combined_se)

    sum_of_shapley = sum(r["shapley_value"] for r in results)
    roster_value = _weighted_value(
        roster_players, per_player_totals, risk_aversion, base_by_position, decay_by_position, num_sims
    )

    return {
        "players": results,
        "sum_of_shapley_values": round(sum_of_shapley, 2),
        "roster_value": round(roster_value, 2),
        "efficiency_check_diff": round(sum_of_shapley - roster_value, 2),
        "num_permutations": num_permutations,
        "num_sims": num_sims,
        "risk_aversion": risk_aversion,
    }
