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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import NUM_TEAMS, ROSTER_POSITIONS, SLEEPER_DRAFT_ID
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError, sleeper_client

router = APIRouter()


class PickIn(BaseModel):
    pick_no: int
    slot: Optional[int] = None
    player_id: str


class MctsRecommendRequest(BaseModel):
    my_slot: int = Field(..., ge=1, description="Which of the 1..num_teams draft slots is mine")
    num_teams: int = Field(default=NUM_TEAMS)
    picks_so_far: list[PickIn] = Field(
        default_factory=list, description="Hypothetical picks already made (ignored if use_live_draft=true)"
    )
    use_live_draft: bool = Field(
        default=False, description="If true, pull real picks from the live Sleeper draft instead of picks_so_far"
    )
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

    if request.use_live_draft:
        try:
            sleeper_picks = await sleeper_client.get_draft_picks(SLEEPER_DRAFT_ID)
        except SleeperAPIError as exc:
            raise HTTPException(status_code=502, detail=f"Could not fetch live draft picks: {exc}") from exc
        draft_state = DraftState.from_sleeper_picks(
            my_slot=request.my_slot,
            sleeper_picks=sleeper_picks,
            num_teams=request.num_teams,
            roster_positions=list(ROSTER_POSITIONS),
        )
    else:
        draft_state = DraftState.hypothetical(
            my_slot=request.my_slot,
            picks_so_far=[p.model_dump() for p in request.picks_so_far],
            num_teams=request.num_teams,
            roster_positions=list(ROSTER_POSITIONS),
        )

    if not draft_state.is_my_turn:
        raise HTTPException(
            status_code=400,
            detail=(
                f"It is not my_slot={request.my_slot}'s turn at pick {draft_state.current_pick_no} "
                f"(slot {draft_state.slot_on_the_clock_now} is on the clock). Provide picks_so_far "
                "consistent with my_slot being on the clock, or check use_live_draft state."
            ),
        )

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
