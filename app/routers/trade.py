"""
POST /api/trade/compare -- Trade Suggester SKELETON (Chunk 56, Task 4).

EXPLICITLY NOT the real trade-value engine. Per this chunk's own brief:
NOT Shapley marginal-contribution analysis (app.services.shapley -- how a
player's value changes GIVEN the rest of a specific roster), NOT
season-simulation-based trade impact (app.services.simulation), and NOT
proactive "who should I trade with" suggestion logic. Those are real
modeling work, deliberately deferred to a future chunk.

What this IS: a transparent, easily-understood value gut-check for
MANUAL exploration -- Vincent picks players for each side of a
hypothetical trade, and gets the sum of raw VBD and raw projected_points
on each side, side by side, with the differential. No roster-fit
awareness (a side's players aren't evaluated against what's already on
that roster), no risk-adjustment, no marginal value. The method is
stated in every response (`method_note`) so this is never confused with
the app's actual Draft Score engine.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers._shared import resolve_league
from app.services.projections import build_baseline_projections
from app.services.vbd import calculate_vbd

router = APIRouter()

METHOD_NOTE = (
    "Simple sum of raw VBD and raw projected_points per side -- NOT roster-fit-aware, "
    "NOT Shapley marginal-contribution analysis, NOT season-simulation-based trade impact. "
    "A transparent gut-check for manual exploration only (Chunk 56 skeleton); the real "
    "trade-value engine is a future chunk's work."
)


class TradeCompareRequest(BaseModel):
    league_key: Optional[str] = Field(
        default=None, description="Which league (app/leagues.py registry). Omit for today's default."
    )
    side_a_player_ids: list[str] = Field(
        default_factory=list, description="Players on one side of the hypothetical trade (e.g. what Vincent gives up)."
    )
    side_b_player_ids: list[str] = Field(
        default_factory=list, description="Players on the other side (e.g. what Vincent would receive)."
    )


def _side_summary(player_ids: list[str], players_by_id: dict[str, Any], vbd_by_id: dict[str, float]) -> dict[str, Any]:
    rows = []
    total_vbd = 0.0
    total_projected_points = 0.0
    unknown: list[str] = []
    for pid in player_ids:
        p = players_by_id.get(pid)
        if p is None:
            unknown.append(pid)
            continue
        vbd = vbd_by_id.get(pid, 0.0)
        proj = p.get("projected_points") or 0.0
        rows.append(
            {
                "player_id": pid,
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "projected_points": p.get("projected_points"),
                "vbd": round(vbd, 1),
            }
        )
        total_vbd += vbd
        total_projected_points += proj
    return {
        "players": rows,
        "total_vbd": round(total_vbd, 1),
        "total_projected_points": round(total_projected_points, 1),
        "unknown_player_ids": unknown,
    }


@router.post("/api/trade/compare")
async def compare_trade(request: TradeCompareRequest) -> dict[str, Any]:
    league = resolve_league(request.league_key)

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}
    vbd_by_id = {p["player_id"]: p["vbd"] for p in calculate_vbd(list(players_by_id.values()))}

    side_a = _side_summary(request.side_a_player_ids, players_by_id, vbd_by_id)
    side_b = _side_summary(request.side_b_player_ids, players_by_id, vbd_by_id)

    if side_a["unknown_player_ids"] or side_b["unknown_player_ids"]:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown player_id(s): {side_a['unknown_player_ids'] + side_b['unknown_player_ids']}",
        )

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "side_a": side_a,
        "side_b": side_b,
        "vbd_differential": round(side_a["total_vbd"] - side_b["total_vbd"], 1),
        "projected_points_differential": round(side_a["total_projected_points"] - side_b["total_projected_points"], 1),
        "method_note": METHOD_NOTE,
    }
