"""
GET /api/waivers/available -- Waiver/Free Agency Suggester SKELETON
(Chunk 57), following the exact same pattern Chunk 56's Trade Suggester
skeleton established: a simple raw-value ranking, not a recommendation
engine.

REUSE, NOT REIMPLEMENTATION:
  - Availability: cross-references the full player pool
    (app.services.projections.build_baseline_projections) against every
    roster in the league, via app.services.roster_identity.
    get_rosters_with_mine_flag (Chunk 56's shared roster-read
    infrastructure -- NOT re-fetched or re-derived here).
  - Ranking: app.services.vbd.calculate_vbd, the SAME VBD computation
    every other planning route in this app already uses. No new
    valuation logic.
  - "My roster" identity: app.services.roster_identity, Chunk 56's
    MY_SLEEPER_USER_ID resolution + cache, reused directly.

EXPLICITLY NOT roster-need-aware: this ranks ALL available free agents
by raw value, full stop. It does not look at what Vincent's roster is
thin at and does not recommend "you need a WR" or similar -- that is
real modeling work, deliberately deferred to a future chunk (mirrors
Chunk 56's Trade Suggester skeleton's own explicit non-goals: no Shapley,
no season-simulation, no proactive suggestion logic).

SCOPING NOTE, stated explicitly, not glossed over: both real leagues are
still pre_draft as of this chunk -- neither has any rostered players yet.
This means essentially the ENTIRE player pool will show as "available"
today. That is correct, expected behavior given the pre-draft state (the
same underlying pattern as Chunks 55/56's empty-roster caveat, surfacing
here as "everything is a free agent" instead of "every roster is empty")
-- not a bug, not something to work around. This becomes a genuinely
useful, much-shorter list once real drafts happen and rosters fill in.

OPTIONAL "my roster position counts" (Task 5): included, since it's
genuinely cheap -- Chunk 56's roster browser already resolves and
returns my roster's player_ids in one call; counting positions from
already-fetched projection data is a few lines, not new infrastructure.
Passive context only (Vincent judges need himself) -- explicitly not fed
into the ranking or used to filter/reorder anything.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.routers._shared import resolve_league
from app.services import roster_identity
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError
from app.services.vbd import calculate_vbd

router = APIRouter()

VALID_POSITIONS = {"QB", "RB", "WR", "TE"}


@router.get("/api/waivers/available")
async def available_free_agents(
    league_key: Optional[str] = Query(
        default=None, description="Which league (app/leagues.py registry). Omit for today's default."
    ),
    position: Optional[str] = Query(default=None, description="Filter to one position: QB, RB, WR, or TE"),
) -> dict[str, Any]:
    pos_filter = position.upper() if position else None
    if pos_filter and pos_filter not in VALID_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Invalid position '{position}'. Must be one of: {sorted(VALID_POSITIONS)}")

    league = resolve_league(league_key)

    try:
        rosters, my_roster_id = await roster_identity.get_rosters_with_mine_flag(league)
    except SleeperAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch live rosters: {exc}") from exc

    rostered_ids: set[str] = set()
    my_roster_ids: list[str] = []
    for r in rosters:
        ids = [str(pid) for pid in (r.get("players") or [])]
        rostered_ids.update(ids)
        if r.get("is_mine"):
            my_roster_ids = ids

    projections_payload = await build_baseline_projections()
    ranked = calculate_vbd(projections_payload["players"])

    available = [p for p in ranked if p["player_id"] not in rostered_ids]
    if pos_filter:
        available = [p for p in available if p["position"] == pos_filter]

    # Task 5 (optional, included -- cheap reuse of data already in hand):
    # passive "my roster counts by position" context, NOT used to filter
    # or reorder the ranking above in any way.
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}
    my_position_counts = {pos: 0 for pos in VALID_POSITIONS}
    for pid in my_roster_ids:
        p = players_by_id.get(pid)
        if p and p.get("position") in my_position_counts:
            my_position_counts[p["position"]] += 1

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "my_roster_id": my_roster_id,
        "my_roster_size": len(my_roster_ids),
        "my_roster_position_counts": my_position_counts,
        "total_rostered_players": len(rostered_ids),
        "position_filter": pos_filter,
        "count": len(available),
        "available_players": available,
    }
