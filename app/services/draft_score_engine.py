"""
Core Draft Score + explanation computation, extracted from
app/routers/draft_score.py so app/services/draft_live.py (the tiered
live-draft recompute manager, Chunk 11) can call the exact same logic
directly -- without going through HTTP, and without duplicating it. The
router is now a thin wrapper over `compute_draft_score`; this module has
no FastAPI dependency so it's equally callable from a background asyncio
task (which is what draft_live.py needs).
"""

from __future__ import annotations

from typing import Any, Optional

from app.services import mcts as mcts_service
from app.services import portfolio as portfolio_service
from app.services import shapley as shapley_service
from app.services.draft_state import DraftState


class DraftScoreError(RuntimeError):
    """No candidates to evaluate, or an explicitly-requested candidate wasn't among them."""


def compute_draft_score(
    draft_state: DraftState,
    players_by_id: dict[str, dict[str, Any]],
    candidate_player_id: Optional[str] = None,
    iterations: int = mcts_service.ITERATIONS,
    candidate_breadth: int = mcts_service.CANDIDATE_BREADTH,
    tree_depth: int = mcts_service.TREE_DEPTH,
    rollout_extra_picks: int = mcts_service.ROLLOUT_EXTRA_PICKS,
    rollout_sim_count: int = mcts_service.ROLLOUT_SIM_COUNT,
    risk_aversion: float = mcts_service.DEFAULT_RISK_AVERSION,
    seed: Optional[int] = None,
    shapley_num_permutations: int = shapley_service.NUM_PERMUTATIONS,
    shapley_num_sims: int = shapley_service.SHAPLEY_NUM_SIMS,
    shapley_seed: Optional[int] = 42,
) -> dict[str, Any]:
    """
    Returns {draft_score, explanation, alternatives_considered} -- see
    app/routers/draft_score.py's module docstring for the design
    (headline MCTS score + Shapley/lineup-awareness explanation, no
    blended number). Synchronous and CPU-bound (MCTS + Shapley); callers
    on an asyncio event loop should run this via `asyncio.to_thread` if
    they can't afford to block (draft_live.py does).
    """
    mcts_result = mcts_service.recommend(
        draft_state,
        players_by_id,
        top_n=candidate_breadth,
        iterations=iterations,
        candidate_breadth=candidate_breadth,
        tree_depth=tree_depth,
        rollout_extra_picks=rollout_extra_picks,
        rollout_sim_count=rollout_sim_count,
        risk_aversion=risk_aversion,
        seed=seed,
    )
    recommendations = mcts_result["recommendations"]
    if not recommendations:
        raise DraftScoreError("MCTS found no candidate players to evaluate for this draft state.")

    if candidate_player_id:
        focus = next((r for r in recommendations if r["player_id"] == candidate_player_id), None)
        if focus is None:
            raise DraftScoreError(
                f"player_id '{candidate_player_id}' was not among the {len(recommendations)} candidates "
                f"MCTS evaluated this run (the top {candidate_breadth} available players by VBD). Raise "
                "candidate_breadth to include it, or omit candidate_player_id to use MCTS's own top pick."
            )
    else:
        focus = max(recommendations, key=lambda r: r["mcts_score"])

    focus_player = players_by_id[focus["player_id"]]
    my_roster_ids = draft_state.roster_player_ids()
    my_roster_players = [players_by_id[pid] for pid in my_roster_ids if pid in players_by_id]
    roster_with_focus = my_roster_players + [focus_player]

    shapley_result = shapley_service.evaluate_shapley(
        roster_with_focus,
        risk_aversion=risk_aversion,
        num_permutations=shapley_num_permutations,
        num_sims=shapley_num_sims,
        seed=shapley_seed,
    )
    focus_shapley = next(p for p in shapley_result["players"] if p["player_id"] == focus_player["player_id"])

    # Starter/bench status + the (rank-decayed, Chunk 10) discount actually
    # applied -- pulled from portfolio.py's own authoritative computation
    # rather than re-deriving it here, so this can never drift from what
    # the Draft Score itself is built on.
    portfolio_result = portfolio_service.evaluate_roster(
        roster_with_focus, risk_aversion=risk_aversion, num_sims=shapley_num_sims, seed=shapley_seed
    )
    focus_portfolio = next(p for p in portfolio_result["players"] if p["player_id"] == focus_player["player_id"])
    is_starter = focus_portfolio["is_starter"]
    bench_discount = focus_portfolio["bench_discount_applied"]
    bench_rank = focus_portfolio["bench_rank"]

    if is_starter:
        note = "Projected to occupy a starting lineup slot on your current roster."
    else:
        note = (
            f"Projected to sit on your bench given your current roster (rank #{bench_rank} bench "
            f"{focus_player.get('position')} on this roster) -- discounted to {bench_discount:.0%} value "
            "in the Draft Score above (see app/services/portfolio.py)."
        )

    return {
        "draft_score": {
            "player_id": focus["player_id"],
            "name": focus["name"],
            "position": focus["position"],
            "team": focus["team"],
            "score": focus["mcts_score"],
            "score_stderr": focus["mcts_score_stderr"],
            "vbd_score": focus["vbd_score"],
            "statistically_tied_with_top_pick": focus.get("within_noise_of_leader"),
        },
        "explanation": {
            "marginal_value": focus_shapley["shapley_value"],
            "marginal_value_stderr": focus_shapley["stderr"],
            "projected_role": "starter" if is_starter else "bench",
            "bench_rank": bench_rank,
            "bench_discount_applied": bench_discount,
            "roster_evaluated": [p["player_id"] for p in roster_with_focus],
            "note": note,
        },
        "alternatives_considered": [
            {
                "player_id": r["player_id"],
                "name": r["name"],
                "position": r["position"],
                "score": r["mcts_score"],
            }
            for r in sorted(recommendations, key=lambda r: -r["mcts_score"])
            if r["player_id"] != focus["player_id"]
        ][:5],
    }
