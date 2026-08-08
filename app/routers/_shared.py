"""
Shared draft-state resolution for routers that need "the current draft
state" from either a hypothetical picks_so_far list or the real live
Sleeper draft -- used by /api/mcts/recommend and /api/draft-score so this
logic exists in exactly one place rather than being duplicated between
them (draft_score.py is explicitly an orchestration layer over the
already-verified mcts.py/shapley.py services, not a new modeling
component -- this is the router-level equivalent of that same principle).
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.config import NUM_TEAMS, ROSTER_POSITIONS, SLEEPER_DRAFT_ID
from app.services.draft_state import DraftState
from app.services.sleeper import SleeperAPIError, sleeper_client


class PickIn(BaseModel):
    pick_no: int
    slot: Optional[int] = None
    player_id: str


class DraftStateRequest(BaseModel):
    my_slot: int = Field(..., ge=1, description="Which of the 1..num_teams draft slots is mine")
    num_teams: int = Field(default=NUM_TEAMS)
    picks_so_far: list[PickIn] = Field(
        default_factory=list, description="Hypothetical picks already made (ignored if use_live_draft=true)"
    )
    use_live_draft: bool = Field(
        default=False, description="If true, pull real picks from the live Sleeper draft instead of picks_so_far"
    )


async def resolve_draft_state(request: DraftStateRequest) -> DraftState:
    """
    Builds a DraftState from `request`, syncing from the real live Sleeper
    draft if requested, or from a hypothetical picks_so_far list otherwise.
    Raises HTTPException (502 on a Sleeper fetch failure, 400 if the
    resulting state isn't actually at my_slot's turn).
    """
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

    return draft_state
