"""GET /api/rankings -- the current best-guess draft board (pre-simulation)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.services.projections import build_baseline_projections
from app.services.vbd import calculate_vbd

router = APIRouter()

VALID_POSITIONS = {"QB", "RB", "WR", "TE"}


@router.get("/api/rankings")
async def get_rankings(
    position: Optional[str] = Query(
        default=None, description="Filter to one position: QB, RB, WR, or TE"
    )
):
    """
    All QB/RB/WR/TE players ranked by VBD (baseline projection minus this
    league's positional replacement level), descending. Pre-simulation --
    point estimate only. See app/services/vbd.py for the replacement-level
    methodology.
    """
    pos_filter = position.upper() if position else None
    if pos_filter and pos_filter not in VALID_POSITIONS:
        return {
            "error": f"Invalid position '{position}'. Must be one of: {sorted(VALID_POSITIONS)}"
        }

    projections_payload = await build_baseline_projections()
    ranked = calculate_vbd(projections_payload["players"])

    if pos_filter:
        ranked = [p for p in ranked if p["position"] == pos_filter]

    return {
        "generated_at": projections_payload["generated_at"],
        "seasons_used": projections_payload["seasons_used"],
        "recency_weights": projections_payload["recency_weights"],
        "position_filter": pos_filter,
        "count": len(ranked),
        "players": ranked,
    }
