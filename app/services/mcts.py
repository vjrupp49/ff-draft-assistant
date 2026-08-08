"""
Simplified Monte Carlo Tree Search (MCTS) over draft picks -- treats "which
player do I take now" as a sequential decision whose value depends on what
will realistically still be available at my NEXT turn, not just this
pick's isolated VBD (Chunk 2).

SCOPE (v1, per the project roadmap's "shallow depth acceptable" target): a
full-depth, fully-solved tree across all 15 rounds x 10 teams is
computationally infeasible for live-draft pace and isn't attempted here.
This bounds BOTH tree depth and branching factor, and uses a cheap
non-tree rollout policy (plus a small number of Monte Carlo season sims,
not thousands) beyond the tree horizon. Concretely:

  - Tree nodes exist ONLY at "my turn" decision points (my own candidate
    picks). Opponent picks happening between my turns are NOT tree nodes
    -- they're resolved by one stochastic sample per visit from
    opponent_model.py. This keeps branching to "my candidate players"
    only, not "every team's every option," which is what makes a couple
    hundred iterations tractable in a few seconds.
  - TREE_DEPTH (default 2): how many of my own future picks get real
    UCB1-guided tree search (this pick + 1 more). Beyond that,
    ROLLOUT_EXTRA_PICKS (default 1) more of my picks are filled with a
    cheap greedy policy (best available VBD) instead of further branching
    -- a 3rd-pick-out tree level would multiply node count by another
    CANDIDATE_BREADTH for a decision that's dominated by "who's even still
    there," which the opponent model already accounts for stochastically.
  - CANDIDATE_BREADTH (default 8): only the top-N available players by VBD
    are considered as actions at any node. Nobody is seriously choosing
    between a top-8 value player and a replacement-level bench arm on the
    same pick -- the interesting decisions live in a narrow band at the
    top of the board.
  - Each rollout's value comes from ONE call to
    app.services.simulation.simulate_roster_summary with a reduced
    ROLLOUT_SIM_COUNT (300, vs. that module's default 1000) -- enough for
    a stable-enough mean for RANKING candidates against each other within
    one MCTS run, not a publishable point estimate on its own. (Tuned up
    from Chunk 4's initial 150 during the stability pass -- see the
    STABILITY NOTE by the ITERATIONS constant below.)

Measured runtime with these defaults is reported per-call by the API layer
(see app/routers/mcts.py's `runtime_seconds`) -- see the chunk's
verification notes for real numbers; tune ITERATIONS down first if a
recommendation call needs to get faster, since it's the single biggest
lever on total work done.

REWARD SIGNAL: app.services.portfolio.evaluate_roster's RISK-ADJUSTED score
(mean simulated season points minus a variance penalty, using the full
roster covariance -- see that module) for "my roster so far" at the end of
a rollout (my pre-existing roster + every pick made along that rollout's
path, tree picks and greedy-continuation picks alike). Prior to this
(Chunk 5), the reward was portfolio.py's precursor -- simulation.py's raw
mean points, with no risk-awareness at all; see portfolio.py's own
docstring for why that mattered enough to fix (this league's 6-of-10
playoff format is meaningfully risk-sensitive). Comparing rewards across
root candidates is apples-to-apples because every rollout adds exactly the
same NUMBER of picks to my roster (TREE_DEPTH + ROLLOUT_EXTRA_PICKS)
regardless of which candidate started it off -- so a candidate slightly
behind on raw VBD right now can still win if opponent behavior (modeled
via opponent_model.py) is likely to strip out the alternative position
entirely before my next turn, leaving my downstream picks worse off. That
scarcity effect is exactly what plain VBD cannot see on its own, and was
the point of Chunk 4; risk-awareness on top of it is the point of Chunk 5.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np

from app.services._stats import WelfordAccumulator
from app.services.draft_state import DraftState
from app.services.opponent_model import build_adp_proxy_ranks, sample_pick
from app.services.portfolio import DEFAULT_RISK_AVERSION, evaluate_roster
from app.services.vbd import calculate_vbd

logger = logging.getLogger("ff_draft_assistant.mcts")

TREE_DEPTH = 2
CANDIDATE_BREADTH = 8
ROLLOUT_EXTRA_PICKS = 1

# Bumped from the Chunk 4 defaults (60 / 150) after a stability pass found
# the #1 recommendation could flip between identical back-to-back calls --
# see STABILITY NOTE below. These values roughly halve run-to-run score
# noise for a ~2x runtime cost (~0.7s -> ~1.4s in testing), still
# comfortably inside the "a few seconds" budget.
ITERATIONS = 150
ROLLOUT_SIM_COUNT = 300

# STABILITY NOTE (post-Chunk-4 verification pass): re-running an identical
# scenario 5x at the Chunk 4 defaults flipped the #1 recommendation
# 4-out-of-5 vs 1-out-of-5 between two candidates whose scores sat well
# within one standard deviation of each other. Raising iterations to 200
# and separately to (150 iters, 400 rollout sims) both roughly halved the
# noise but did NOT eliminate the flip -- the two candidates' mean scores
# stayed a fraction of a point apart even with ~2.5x the compute, which is
# the signature of a genuine near-tie in estimated value, not insufficient
# sampling. Throwing more iterations at a true tie forever chases noise
# that never fully resolves. The actual fix is below: `recommend()` now
# tracks each candidate's standard error and flags when the leaders are
# statistically indistinguishable, so a near-tie gets reported as a STABLE
# "these are roughly interchangeable" finding every run, instead of an
# unstable single "winner" that silently coin-flips between calls. The
# iteration/sim bump above is a complementary, real improvement (less
# noise for the candidates that AREN'T close), not a claim that it makes
# every ranking deterministic.

# Standard UCB1 exploration constant for REWARDS NORMALIZED TO [0, 1] (see
# _RewardStats below) -- sqrt(2) is the textbook value; nudged up slightly
# since our iteration budget is small (a few dozen, not thousands) and
# under-exploring is the costlier mistake here: a first-look reward from a
# single noisy ~150-sim rollout is a weak signal to commit to early.
UCB_EXPLORATION = 1.8

# How many combined standard errors apart two candidates' scores need to be
# before we call one a clear leader over the other, rather than flagging
# them as statistically indistinguishable (see STABILITY NOTE above). A
# judgment-call threshold, not a formal hypothesis test -- no
# multiple-comparison correction -- but enough to stop presenting sampling
# noise as a confident single "#1 pick."
NEAR_TIE_Z = 1.5


class _RewardStats:
    """
    Tracks the running min/max reward seen across a search so UCB1's
    exploration term can be computed on a normalized [0, 1] scale.

    Rewards here are mean simulated SEASON POINT TOTALS (hundreds to low
    thousands, growing as more players accumulate on a roster) -- using a
    fixed exploration constant directly against that raw scale silently
    turns into almost-pure exploitation (the constant is negligible next to
    reward-scale noise) or almost-pure exploration (if set too high),
    depending on how deep into a draft the state is. Normalizing first is
    what makes a single textbook-ish constant (see UCB_EXPLORATION) do the
    right thing regardless of how many points are already on the board.
    """

    __slots__ = ("min_r", "max_r")

    def __init__(self) -> None:
        self.min_r = float("inf")
        self.max_r = float("-inf")

    def observe(self, reward: float) -> None:
        self.min_r = min(self.min_r, reward)
        self.max_r = max(self.max_r, reward)

    def normalize(self, reward: float) -> float:
        if self.max_r <= self.min_r:
            return 0.5  # no spread observed yet -- neutral, doesn't bias early exploration
        return (reward - self.min_r) / (self.max_r - self.min_r)


class _Node:
    __slots__ = ("draft_state", "depth", "player_id", "parent", "children", "untried", "_stats")

    def __init__(
        self,
        draft_state: DraftState,
        depth: int,
        player_id: Optional[str],
        parent: Optional["_Node"],
        untried: list[str],
    ):
        self.draft_state = draft_state
        self.depth = depth  # tree levels ("my picks") deep this node is; root = 0
        self.player_id = player_id  # the pick that led to this node (None for root)
        self.parent = parent
        self.children: dict[str, "_Node"] = {}
        self.untried = untried
        self._stats = WelfordAccumulator()  # see app/services/_stats.py -- numerically stable at this reward scale

    @property
    def visits(self) -> int:
        return self._stats.visits

    @property
    def mean_value(self) -> float:
        return self._stats.mean

    @property
    def stderr(self) -> Optional[float]:
        """
        Standard error of `mean_value`. None with fewer than 2 visits
        (variance undefined). Used to flag near-ties between top
        candidates -- see the STABILITY NOTE above `ITERATIONS`.
        """
        return self._stats.stderr

    def record(self, reward: float) -> None:
        self._stats.record(reward)

    def ucb1(self, c: float, stats: _RewardStats) -> float:
        if self.visits == 0:
            return float("inf")
        assert self.parent is not None
        exploit = stats.normalize(self.mean_value)
        explore = c * math.sqrt(math.log(max(self.parent.visits, 1)) / self.visits)
        return exploit + explore


def _available_players(state: DraftState, players_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    drafted = state.drafted_player_ids
    return [p for pid, p in players_by_id.items() if pid not in drafted]


def _top_available_by_vbd(state: DraftState, players_by_id: dict[str, dict[str, Any]], k: int) -> list[dict[str, Any]]:
    ranked = calculate_vbd(list(players_by_id.values()), drafted_player_ids=state.drafted_player_ids)
    return ranked[:k]


def _advance_opponents(
    state: DraftState,
    players_by_id: dict[str, dict[str, Any]],
    adp_ranks: dict[str, int],
    rng: np.random.Generator,
) -> None:
    """Mutates `state` in place, sampling opponent picks (opponent_model.py) until it's my turn again."""
    guard = 0
    while not state.is_my_turn:
        guard += 1
        if guard > state.num_teams * 3:  # safety valve, shouldn't trigger
            logger.warning("Opponent advance loop did not converge, stopping early")
            break
        available = _available_players(state, players_by_id)
        if not available:
            break
        team_counts = state.position_counts(state.slot_on_the_clock_now, players_by_id)
        pick = sample_pick(rng, team_counts, available, state.current_pick_no, adp_ranks)
        if pick is None:
            break
        state.add_pick(pick)


def _run_iteration(
    root: _Node,
    reward_stats: _RewardStats,
    players_by_id: dict[str, dict[str, Any]],
    adp_ranks: dict[str, int],
    rng: np.random.Generator,
    tree_depth: int,
    candidate_breadth: int,
    rollout_extra_picks: int,
    rollout_sim_count: int,
    risk_aversion: float,
) -> None:
    # SELECTION: descend via UCB1 (normalized, see _RewardStats) while fully expanded.
    node = root
    path = [root]
    while not node.untried and node.children and node.depth < tree_depth:
        node = max(node.children.values(), key=lambda n: n.ucb1(UCB_EXPLORATION, reward_stats))
        path.append(node)

    # EXPANSION: add one new child if this node still has untried actions.
    if node.untried and node.depth < tree_depth:
        action = node.untried.pop()
        child_state = node.draft_state.clone()
        child_state.add_pick(action)
        _advance_opponents(child_state, players_by_id, adp_ranks, rng)

        child_depth = node.depth + 1
        untried_for_child = (
            [p["player_id"] for p in _top_available_by_vbd(child_state, players_by_id, candidate_breadth)]
            if child_depth < tree_depth
            else []
        )
        child = _Node(child_state, child_depth, action, node, untried_for_child)
        node.children[action] = child
        path.append(child)
        node = child

    # ROLLOUT: beyond the tree horizon, continue with a cheap greedy policy
    # (best available VBD) for `rollout_extra_picks` more of my picks,
    # advancing opponents between each -- on a clone so this randomness
    # doesn't get baked into the tree itself.
    rollout_state = node.draft_state.clone()
    for _ in range(rollout_extra_picks):
        if not rollout_state.is_my_turn:
            break
        candidates = _top_available_by_vbd(rollout_state, players_by_id, 1)
        if not candidates:
            break
        rollout_state.add_pick(candidates[0]["player_id"])
        _advance_opponents(rollout_state, players_by_id, adp_ranks, rng)

    # EVALUATE: risk-adjusted value of my accumulated roster (portfolio.py).
    my_roster_ids = rollout_state.roster_player_ids()
    my_roster_players = [players_by_id[pid] for pid in my_roster_ids if pid in players_by_id]
    reward = evaluate_roster(
        my_roster_players, risk_aversion=risk_aversion, num_sims=rollout_sim_count, seed=None
    )["risk_adjusted_score"]

    # BACKPROPAGATION
    reward_stats.observe(reward)
    for n in path:
        n.record(reward)


def recommend(
    draft_state: DraftState,
    players_by_id: dict[str, dict[str, Any]],
    top_n: int = 8,
    iterations: int = ITERATIONS,
    candidate_breadth: int = CANDIDATE_BREADTH,
    tree_depth: int = TREE_DEPTH,
    rollout_extra_picks: int = ROLLOUT_EXTRA_PICKS,
    rollout_sim_count: int = ROLLOUT_SIM_COUNT,
    risk_aversion: float = DEFAULT_RISK_AVERSION,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """
    Runs MCTS from `draft_state` (must be at my_slot's turn) and returns the
    top `top_n` candidate picks ranked by MCTS-estimated value, alongside
    their plain VBD score for the same state, so a caller can see where the
    two disagree.
    """
    if not draft_state.is_my_turn:
        raise ValueError(
            f"draft_state is not at my_slot's turn (on the clock: slot "
            f"{draft_state.slot_on_the_clock_now}, my_slot: {draft_state.my_slot})"
        )

    rng = np.random.default_rng(seed)

    all_players = list(players_by_id.values())
    vbd_full = calculate_vbd(all_players, drafted_player_ids=draft_state.drafted_player_ids)
    vbd_by_player = {p["player_id"]: p for p in vbd_full}
    adp_ranks = build_adp_proxy_ranks(vbd_full)

    root_candidates = [p["player_id"] for p in vbd_full[:candidate_breadth]]
    if not root_candidates:
        return {"recommendations": [], "candidates_considered": [], "iterations_run": 0}

    root = _Node(draft_state, depth=0, player_id=None, parent=None, untried=list(root_candidates))
    reward_stats = _RewardStats()

    for _ in range(iterations):
        _run_iteration(
            root,
            reward_stats,
            players_by_id,
            adp_ranks,
            rng,
            tree_depth,
            candidate_breadth,
            rollout_extra_picks,
            rollout_sim_count,
            risk_aversion,
        )

    results = []
    for pid, child in root.children.items():
        vbd_info = vbd_by_player.get(pid, {})
        results.append(
            {
                "player_id": pid,
                "name": vbd_info.get("name"),
                "position": vbd_info.get("position"),
                "team": vbd_info.get("team"),
                "vbd_score": vbd_info.get("vbd"),
                "projected_points": vbd_info.get("projected_points"),
                "mcts_score": round(child.mean_value, 1),
                "mcts_score_stderr": round(child.stderr, 2) if child.stderr is not None else None,
                "mcts_visits": child.visits,
            }
        )

    results.sort(key=lambda r: r["mcts_score"], reverse=True)
    top_results = results[:top_n]

    # Flag candidates statistically indistinguishable from the leader (see
    # STABILITY NOTE above ITERATIONS) instead of silently presenting
    # sampling noise as a confident single "#1 pick."
    tied_with_leader: list[str] = []
    if top_results:
        leader = top_results[0]
        leader_se = leader["mcts_score_stderr"] or 0.0
        for r in top_results:
            r_se = r["mcts_score_stderr"] or 0.0
            combined_se = (leader_se**2 + r_se**2) ** 0.5
            margin = leader["mcts_score"] - r["mcts_score"]
            r["within_noise_of_leader"] = r is leader or (combined_se > 0 and margin <= NEAR_TIE_Z * combined_se)
        tied_with_leader = [r["name"] for r in top_results if r["within_noise_of_leader"] and r is not leader]

    return {
        "recommendations": top_results,
        "top_pick_statistically_tied_with": tied_with_leader,
        "candidates_considered": root_candidates,
        "iterations_run": iterations,
        "params": {
            "tree_depth": tree_depth,
            "candidate_breadth": candidate_breadth,
            "rollout_extra_picks": rollout_extra_picks,
            "rollout_sim_count": rollout_sim_count,
            "risk_aversion": risk_aversion,
        },
    }
