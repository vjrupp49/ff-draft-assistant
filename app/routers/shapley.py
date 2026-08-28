"""
POST /api/shapley/evaluate -- per-player Shapley value attribution for a
candidate roster, against portfolio.py's risk-adjusted objective. See
app/services/shapley.py for the method and why exact Shapley isn't used.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers._shared import resolve_league
from app.services import shapley as shapley_service
from app.services.portfolio import DEFAULT_RISK_AVERSION
from app.services.projections import build_baseline_projections

router = APIRouter()


class ShapleyEvaluateRequest(BaseModel):
    player_ids: list[str] = Field(..., min_length=1, description="Sleeper player_ids making up the roster")
    risk_aversion: float = Field(default=DEFAULT_RISK_AVERSION, ge=0)
    num_permutations: int = Field(default=shapley_service.NUM_PERMUTATIONS, ge=10, le=5000)
    num_sims: int = Field(default=shapley_service.SHAPLEY_NUM_SIMS, ge=100, le=20000)
    seed: Optional[int] = Field(default=42, description="Omit/null for a fresh random draw each call")
    league_key: Optional[str] = Field(
        default=None,
        description="Which league (app/leagues.py registry) this evaluation is for. Omit for today's default.",
    )


@router.post("/api/shapley/evaluate")
async def evaluate_shapley(request: ShapleyEvaluateRequest) -> dict[str, Any]:
    league = resolve_league(request.league_key)

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

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

    result = shapley_service.evaluate_shapley(
        roster_players,
        risk_aversion=request.risk_aversion,
        num_permutations=request.num_permutations,
        num_sims=request.num_sims,
        seed=request.seed,
    )
    result["league_key"] = league.key
    result["league_name"] = league.league_name
    return result
