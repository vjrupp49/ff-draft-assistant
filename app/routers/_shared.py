"""
Shared draft-state resolution for routers that need "the current draft
state" from either a hypothetical picks_so_far list or the real live
Sleeper draft -- used by /api/mcts/recommend and /api/draft-score so this
logic exists in exactly one place rather than being duplicated between
them (draft_score.py is explicitly an orchestration layer over the
already-verified mcts.py/shapley.py services, not a new modeling
component -- this is the router-level equivalent of that same principle).

CHUNK 53 -- `resolve_league` adds real, validated, per-request league_key
support for planning/browsing routes (see app/leagues.py's registry).
SCOPE BOUNDARY, stated explicitly, not silently decided: this resolves and
validates league_key, threads it into DraftState construction for the
HYPOTHETICAL branch only (never `use_live_draft=True` -- that branch keeps
hitting SLEEPER_DRAFT_ID and the global ROSTER_POSITIONS exactly as
before, matching the live-draft-path exemption), and REJECTS (409) any
league_key whose num_teams/roster_positions/scoring differs from the
currently-active global engine config. That guard exists because
app/services/vbd.py's replacement-level math (_slot_counts,
_league_slot_needs) and app/services/projections.py's point-scoring both
read NUM_TEAMS/ROSTER_POSITIONS/SCORING as plain module-level globals, not
per-call parameters -- there is no way to make a single request honor a
league whose shape differs from whatever ACTIVE_LEAGUE_KEY currently is
without touching that core compute-engine code, which is deliberately out
of scope here (see Chunks 47/49 for why that code is treated as
higher-risk than this). Since Chunk 51 confirmed Kiddos and Former Bradley
Bums share an IDENTICAL format today, this guard never actually fires for
either real league -- it's a safety net against a future differently-
shaped league silently producing wrong numbers, not a limitation felt by
the current user.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.config import NUM_TEAMS, ROSTER_POSITIONS, SLEEPER_DRAFT_ID
from app.leagues import ACTIVE_LEAGUE, LEAGUES, LeagueConfig
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
    league_key: Optional[str] = Field(
        default=None,
        description=(
            "Which league (see app/leagues.py registry) to plan against. Omit for the current "
            "ACTIVE_LEAGUE_KEY behavior (unchanged default). Ignored when use_live_draft=true -- "
            "the live path always uses the process's single active league, by design."
        ),
    )


def resolve_league(league_key: Optional[str]) -> LeagueConfig:
    """
    Resolves a league_key to a LeagueConfig for planning/browsing routes.
    None -> today's default behavior (the active global league). An
    unknown key is a 404 (a real, validated lookup, not a silently-ignored
    param). A key that resolves to a config whose num_teams/
    roster_positions/scoring differs from the currently-active global
    engine config is a 409 -- see this module's docstring for why.
    """
    if league_key is None:
        return ACTIVE_LEAGUE
    league = LEAGUES.get(league_key)
    if league is None:
        raise HTTPException(status_code=404, detail=f"Unknown league_key '{league_key}'. Known: {sorted(LEAGUES)}")
    if (
        league.num_teams != ACTIVE_LEAGUE.num_teams
        or league.roster_positions != ACTIVE_LEAGUE.roster_positions
        or league.scoring != ACTIVE_LEAGUE.scoring
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"league_key='{league_key}' has a different format than the currently active engine "
                f"config ('{ACTIVE_LEAGUE.key}') -- scoring/roster shape/num_teams are still globally "
                "configured (see app/routers/_shared.py's Chunk 53 scope note), so this route can't yet "
                "honor a genuinely different format. Switch app.leagues.ACTIVE_LEAGUE_KEY to use this "
                "league fully."
            ),
        )
    return league


async def resolve_draft_state(request: DraftStateRequest) -> DraftState:
    """
    Builds a DraftState from `request`, syncing from the real live Sleeper
    draft if requested, or from a hypothetical picks_so_far list otherwise.
    Raises HTTPException (502 on a Sleeper fetch failure, 400 if the
    resulting state isn't actually at my_slot's turn).
    """
    if request.use_live_draft:
        # Live-draft path -- deliberately untouched by Chunk 53's league_key
        # work, per the chunk's own scope (single active-league config here).
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
        league = resolve_league(request.league_key)
        draft_state = DraftState.hypothetical(
            my_slot=request.my_slot,
            picks_so_far=[p.model_dump() for p in request.picks_so_far],
            num_teams=request.num_teams,
            roster_positions=list(league.roster_positions),
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
