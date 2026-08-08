"""
GET /api/simulate/player/{player_id} -- one player's simulated season outcome distribution.
POST /api/simulate/roster -- a candidate roster's simulated (correlated) season outcome distribution.

See app/services/simulation.py for the model and its deliberately bounded
scope (player/roster-level Monte Carlo, no schedule/matchup simulation).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.projections import build_baseline_projections
from app.services.simulation import (
    DEFAULT_NUM_SIMS,
    DEFAULT_SEED,
    simulate_player_summary,
    simulate_roster_summary,
)

router = APIRouter()


async def _players_by_id() -> dict[str, dict]:
    payload = await build_baseline_projections()
    return {p["player_id"]: p for p in payload["players"]}


@router.get("/api/simulate/player/{player_id}")
async def simulate_player(
    player_id: str,
    num_sims: int = Query(default=DEFAULT_NUM_SIMS, ge=100, le=20000),
):
    """
    Simulated season-total outcome distribution for one player: mean,
    median, stddev, p5/p95, min/max across `num_sims` simulated seasons.
    Cached (see app/services/simulation.py) keyed to the player's current
    projection, so this is fast on repeat calls.
    """
    players = await _players_by_id()
    player = players.get(player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Unknown player_id '{player_id}'")

    summary = simulate_player_summary(player, num_sims=num_sims)
    return {
        "player_id": player_id,
        "name": player.get("name"),
        "position": player.get("position"),
        "team": player.get("team"),
        "projected_points": player.get("projected_points"),
        "num_sims": num_sims,
        **summary,
    }


class RosterSimulationRequest(BaseModel):
    player_ids: list[str] = Field(..., min_length=1, description="Sleeper player_ids making up the candidate roster")
    num_sims: int = Field(default=DEFAULT_NUM_SIMS, ge=100, le=20000)
    seed: Optional[int] = Field(default=DEFAULT_SEED, description="Omit/null for a fresh random draw each call")


@router.post("/api/simulate/roster")
async def simulate_roster(request: RosterSimulationRequest):
    """
    Simulated season-total outcome distribution for a candidate roster --
    the same correlated player-level draws summed per simulation run (see
    app/services/simulation.py for the team-game-script correlation
    simplification). Returns the roster-level summary plus each player's
    own individual summary from the same run.
    """
    players_by_id = await _players_by_id()

    roster_players = []
    unknown_ids = []
    for pid in request.player_ids:
        player = players_by_id.get(pid)
        if player is None:
            unknown_ids.append(pid)
        else:
            roster_players.append(player)

    if unknown_ids:
        raise HTTPException(status_code=404, detail=f"Unknown player_id(s): {unknown_ids}")

    result = simulate_roster_summary(roster_players, num_sims=request.num_sims, seed=request.seed)
    return result
