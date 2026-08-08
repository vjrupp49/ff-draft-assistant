"""
POST /api/mcts/recommend -- MCTS-ranked pick recommendations for a given
draft state, alongside each candidate's plain VBD score for comparison.

Accepts EITHER a hypothetical picks-so-far list (draft order/position not
locked in yet for this league) OR a flag to sync from the real live
Sleeper draft -- see app/services/draft_state.py.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import Field

from app.routers._shared import DraftStateRequest, resolve_draft_state
from app.services import mcts as mcts_service
from app.services.projections import build_baseline_projections

router = APIRouter()


class MctsRecommendRequest(DraftStateRequest):
    top_n: int = Field(default=8, ge=1, le=20)
    iterations: int = Field(default=mcts_service.ITERATIONS, ge=1, le=1000)
    candidate_breadth: int = Field(default=mcts_service.CANDIDATE_BREADTH, ge=2, le=30)
    tree_depth: int = Field(default=mcts_service.TREE_DEPTH, ge=1, le=4)
    rollout_extra_picks: int = Field(default=mcts_service.ROLLOUT_EXTRA_PICKS, ge=0, le=5)
    rollout_sim_count: int = Field(default=mcts_service.ROLLOUT_SIM_COUNT, ge=20, le=2000)
    risk_aversion: float = Field(
        default=mcts_service.DEFAULT_RISK_AVERSION,
        ge=0,
        description="Markowitz risk-aversion coefficient (see app/services/portfolio.py). 0 = ignore variance entirely.",
    )
    seed: Optional[int] = Field(default=None)


@router.post("/api/mcts/recommend")
async def mcts_recommend(request: MctsRecommendRequest) -> dict[str, Any]:
    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    draft_state = await resolve_draft_state(request)

    t0 = time.perf_counter()
    result = mcts_service.recommend(
        draft_state,
        players_by_id,
        top_n=request.top_n,
        iterations=request.iterations,
        candidate_breadth=request.candidate_breadth,
        tree_depth=request.tree_depth,
        rollout_extra_picks=request.rollout_extra_picks,
        rollout_sim_count=request.rollout_sim_count,
        risk_aversion=request.risk_aversion,
        seed=request.seed,
    )
    runtime_seconds = round(time.perf_counter() - t0, 3)

    return {
        "my_slot": draft_state.my_slot,
        "current_pick_no": draft_state.current_pick_no,
        "current_round": draft_state.current_round,
        "runtime_seconds": runtime_seconds,
        **result,
    }
