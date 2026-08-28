"""
GET /api/targets -- starred/target players for a league (Draft Outlook).
POST /api/targets -- star a player for a league.
DELETE /api/targets/{player_id} -- unstar a player for a league.

Planning/browsing route, per Chunk 53's classification -- see
app/routers/_shared.py's resolve_league. Persisted via
app/services/targets.py (a simple per-league JSON file -- see that
module's docstring for why, and why it's deliberately NOT gitignored
unlike this project's other data/*.json cache files).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.routers._shared import resolve_league
from app.services import targets as targets_service

router = APIRouter()


class TargetRequest(BaseModel):
    player_id: str = Field(..., description="Sleeper player_id to star/unstar")
    league_key: Optional[str] = Field(
        default=None, description="Which league (app/leagues.py registry) this target is for. Omit for today's default."
    )


@router.get("/api/targets")
async def list_targets(
    league_key: Optional[str] = Query(
        default=None, description="Which league (app/leagues.py registry) to list targets for. Omit for today's default."
    ),
) -> dict[str, Any]:
    league = resolve_league(league_key)
    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "player_ids": targets_service.get_targets(league.key),
    }


@router.post("/api/targets")
async def star_target(request: TargetRequest) -> dict[str, Any]:
    league = resolve_league(request.league_key)
    player_ids = targets_service.add_target(league.key, request.player_id)
    return {"league_key": league.key, "player_ids": player_ids}


@router.delete("/api/targets/{player_id}")
async def unstar_target(
    player_id: str,
    league_key: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    league = resolve_league(league_key)
    player_ids = targets_service.remove_target(league.key, player_id)
    return {"league_key": league.key, "player_ids": player_ids}
