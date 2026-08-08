"""
POST /api/draft-score -- the single, consolidated Draft Score for a
candidate pick, plus a Shapley-based explanation of WHY it scores that
way.

DESIGN (per the project's founding "no weighted averages" principle):
this does NOT invent a new blended number. The Draft Score IS
app.services.mcts's value estimate -- which already incorporates
simulation, risk-adjustment, and starting-lineup-awareness in its reward
function (see mcts.py's REWARD SIGNAL note and portfolio.py). Shapley
(app.services.shapley) is not a second score to average against it --
it's the EXPLANATION layer: given the roster this candidate would join,
how much does adding them actually change its risk-adjusted value, and
would they project as a starter or a discounted bench contributor. This
route is a thin orchestration layer over those two already-verified
engines (one MCTS run + one Shapley run on "my roster + this candidate"),
not a new modeling component -- it duplicates no scoring logic of its
own.

A statistical tie (Chunk 4.5) is surfaced as part of the honest single
score, not hidden -- see `statistically_tied_with_top_pick` below.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.routers._shared import DraftStateRequest, resolve_draft_state
from app.services import mcts as mcts_service
from app.services import shapley as shapley_service
from app.services.portfolio import BENCH_VALUE_DISCOUNT, DEFAULT_BENCH_DISCOUNT
from app.services.projections import build_baseline_projections
from app.services.vbd import allocate_roster_starters

router = APIRouter()


class DraftScoreRequest(DraftStateRequest):
    candidate_player_id: Optional[str] = Field(
        default=None,
        description="Which available player to score/explain. Omit to use MCTS's own top-ranked recommendation.",
    )
    # MCTS tuning -- same defaults/meaning as /api/mcts/recommend.
    iterations: int = Field(default=mcts_service.ITERATIONS, ge=1, le=1000)
    candidate_breadth: int = Field(default=mcts_service.CANDIDATE_BREADTH, ge=2, le=30)
    tree_depth: int = Field(default=mcts_service.TREE_DEPTH, ge=1, le=4)
    rollout_extra_picks: int = Field(default=mcts_service.ROLLOUT_EXTRA_PICKS, ge=0, le=5)
    rollout_sim_count: int = Field(default=mcts_service.ROLLOUT_SIM_COUNT, ge=20, le=2000)
    risk_aversion: float = Field(default=mcts_service.DEFAULT_RISK_AVERSION, ge=0)
    seed: Optional[int] = Field(default=None)
    # Shapley (explanation-layer) tuning -- separate from the MCTS seed since
    # it's a different, much cheaper computation (see shapley.py).
    shapley_num_permutations: int = Field(default=shapley_service.NUM_PERMUTATIONS, ge=10, le=5000)
    shapley_num_sims: int = Field(default=shapley_service.SHAPLEY_NUM_SIMS, ge=100, le=20000)
    shapley_seed: Optional[int] = Field(default=42)


@router.post("/api/draft-score")
async def draft_score(request: DraftScoreRequest) -> dict[str, Any]:
    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    draft_state = await resolve_draft_state(request)

    t0 = time.perf_counter()

    # 1) The Draft Score itself -- MCTS's value estimate. top_n=candidate_breadth
    # so every candidate MCTS actually evaluated comes back (it never
    # evaluates more than candidate_breadth candidates), not just a
    # truncated top-N.
    mcts_result = mcts_service.recommend(
        draft_state,
        players_by_id,
        top_n=request.candidate_breadth,
        iterations=request.iterations,
        candidate_breadth=request.candidate_breadth,
        tree_depth=request.tree_depth,
        rollout_extra_picks=request.rollout_extra_picks,
        rollout_sim_count=request.rollout_sim_count,
        risk_aversion=request.risk_aversion,
        seed=request.seed,
    )
    recommendations = mcts_result["recommendations"]
    if not recommendations:
        raise HTTPException(
            status_code=404, detail="MCTS found no candidate players to evaluate for this draft state."
        )

    if request.candidate_player_id:
        focus = next((r for r in recommendations if r["player_id"] == request.candidate_player_id), None)
        if focus is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"player_id '{request.candidate_player_id}' was not among the "
                    f"{len(recommendations)} candidates MCTS evaluated this run (the top "
                    f"{request.candidate_breadth} available players by VBD). Raise candidate_breadth "
                    "to include it, or omit candidate_player_id to use MCTS's own top pick."
                ),
            )
    else:
        focus = max(recommendations, key=lambda r: r["mcts_score"])

    # 2) The explanation layer -- Shapley marginal contribution of adding
    # the focus candidate to MY roster as it stands right now.
    focus_player = players_by_id[focus["player_id"]]
    my_roster_ids = draft_state.roster_player_ids()
    my_roster_players = [players_by_id[pid] for pid in my_roster_ids if pid in players_by_id]
    roster_with_focus = my_roster_players + [focus_player]

    shapley_result = shapley_service.evaluate_shapley(
        roster_with_focus,
        risk_aversion=request.risk_aversion,
        num_permutations=request.shapley_num_permutations,
        num_sims=request.shapley_num_sims,
        seed=request.shapley_seed,
    )
    focus_shapley = next(p for p in shapley_result["players"] if p["player_id"] == focus_player["player_id"])

    starter_ids = allocate_roster_starters(roster_with_focus)
    is_starter = focus_player["player_id"] in starter_ids
    bench_discount = None if is_starter else BENCH_VALUE_DISCOUNT.get(focus_player.get("position"), DEFAULT_BENCH_DISCOUNT)

    if is_starter:
        note = "Projected to occupy a starting lineup slot on your current roster."
    else:
        note = (
            f"Projected to sit on your bench given your current roster -- discounted to "
            f"{bench_discount:.0%} value in the Draft Score above (see app/services/portfolio.py)."
        )

    runtime_seconds = round(time.perf_counter() - t0, 3)

    return {
        "my_slot": draft_state.my_slot,
        "current_pick_no": draft_state.current_pick_no,
        "current_round": draft_state.current_round,
        "runtime_seconds": runtime_seconds,
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
