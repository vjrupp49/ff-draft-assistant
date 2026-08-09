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
would they project as a starter or a discounted bench contributor.

The actual computation lives in app/services/draft_score_engine.py (Chunk
11 extracted it there so app/services/draft_live.py's tiered live-draft
recompute could call the identical logic without going through HTTP or
duplicating it) -- this router is now a thin request/response wrapper.

A statistical tie (Chunk 4.5) is surfaced as part of the honest single
score, not hidden -- see `statistically_tied_with_top_pick` below.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.routers._shared import DraftStateRequest, resolve_draft_state
from app.services import draft_score_engine
from app.services import mcts as mcts_service
from app.services import shapley as shapley_service
from app.services.projections import build_baseline_projections

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
    try:
        result = draft_score_engine.compute_draft_score(
            draft_state,
            players_by_id,
            candidate_player_id=request.candidate_player_id,
            iterations=request.iterations,
            candidate_breadth=request.candidate_breadth,
            tree_depth=request.tree_depth,
            rollout_extra_picks=request.rollout_extra_picks,
            rollout_sim_count=request.rollout_sim_count,
            risk_aversion=request.risk_aversion,
            seed=request.seed,
            shapley_num_permutations=request.shapley_num_permutations,
            shapley_num_sims=request.shapley_num_sims,
            shapley_seed=request.shapley_seed,
        )
    except draft_score_engine.DraftScoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runtime_seconds = round(time.perf_counter() - t0, 3)

    return {
        "my_slot": draft_state.my_slot,
        "current_pick_no": draft_state.current_pick_no,
        "current_round": draft_state.current_round,
        "runtime_seconds": runtime_seconds,
        **result,
    }
