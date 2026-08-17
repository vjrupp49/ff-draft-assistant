"""
POST /api/portfolio/evaluate -- risk-adjusted (Markowitz-style) value of a
candidate roster. See app/services/portfolio.py for the objective and why
a flat default risk_aversion was chosen over a standings-aware one.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import portfolio as portfolio_service
from app.services.projections import build_baseline_projections
from app.services.simulation import DEFAULT_NUM_SIMS

router = APIRouter()


class PortfolioEvaluateRequest(BaseModel):
    player_ids: list[str] = Field(..., min_length=1, description="Sleeper player_ids making up the candidate roster")
    risk_aversion: float = Field(
        default=portfolio_service.DEFAULT_RISK_AVERSION,
        ge=0,
        description="Markowitz risk-aversion coefficient. 0 = ignore variance entirely (pure expected value).",
    )
    num_sims: int = Field(default=DEFAULT_NUM_SIMS, ge=100, le=20000)
    seed: Optional[int] = Field(default=42, description="Omit/null for a fresh random draw each call")


@router.post("/api/portfolio/evaluate")
async def evaluate_portfolio(request: PortfolioEvaluateRequest) -> dict[str, Any]:
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

    return portfolio_service.evaluate_roster(
        roster_players,
        risk_aversion=request.risk_aversion,
        num_sims=request.num_sims,
        seed=request.seed,
    )
