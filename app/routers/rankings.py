"""GET /api/rankings -- the current best-guess draft board (pre-simulation)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.routers._shared import resolve_league
from app.services.projections import build_baseline_projections
from app.services.vbd import calculate_vbd

router = APIRouter()

VALID_POSITIONS = {"QB", "RB", "WR", "TE"}


@router.get("/api/rankings")
async def get_rankings(
    position: Optional[str] = Query(
        default=None, description="Filter to one position: QB, RB, WR, or TE"
    ),
    league_key: Optional[str] = Query(
        default=None,
        description=(
            "Which league (app/leagues.py registry) to rank for. Omit for today's default "
            "behavior. NOTE (Chunk 53 scope): this validates/echoes the league but does not "
            "change the VBD math itself -- app/services/vbd.py's replacement-level logic still "
            "reads NUM_TEAMS/ROSTER_POSITIONS as globals, not per-call. A league_key whose format "
            "differs from the active global config is rejected (409) rather than silently "
            "computing wrong numbers -- see app/routers/_shared.py's resolve_league."
        ),
    ),
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

    league = resolve_league(league_key)

    projections_payload = await build_baseline_projections()
    ranked = calculate_vbd(projections_payload["players"])

    if pos_filter:
        ranked = [p for p in ranked if p["position"] == pos_filter]

    return {
        "generated_at": projections_payload["generated_at"],
        "seasons_used": projections_payload["seasons_used"],
        "recency_weights": projections_payload["recency_weights"],
        "position_filter": pos_filter,
        "league_key": league.key,
        "league_name": league.league_name,
        "count": len(ranked),
        "players": ranked,
    }
