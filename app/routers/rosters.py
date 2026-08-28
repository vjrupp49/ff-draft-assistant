"""
GET /api/rosters -- Roster Browser (Chunk 56, Task 3): every roster in a
league (mine and all opponents'), read-only. Reuses
app.services.roster_identity's shared "which roster is mine" resolution
(Chunk 56) rather than duplicating that lookup here.

SCOPING NOTE, same as Chunk 55's lineup optimizer: both real leagues are
still pre_draft as of this chunk -- every roster's `players` list is
currently empty for both leagues (confirmed directly). This endpoint is
real, working code against Sleeper's genuine rosters/users endpoints, but
is genuinely UNTESTED against real, populated opponent rosters -- that
has to wait until after an actual draft. See this chunk's test file for
how the display/summarization logic (team names, player rows, is_mine
flag) was validated instead: a monkeypatched Sleeper client returning a
full 10-team SYNTHETIC league built from Chunks 40/41's existing
mock-draft artifact (every draft slot's real picks, not just one), not
newly generated data.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.routers._shared import resolve_league
from app.services import roster_identity
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError, sleeper_client

router = APIRouter()


@router.get("/api/rosters")
async def list_rosters(
    league_key: Optional[str] = Query(
        default=None, description="Which league (app/leagues.py registry). Omit for today's default."
    ),
) -> dict[str, Any]:
    league = resolve_league(league_key)

    try:
        rosters, my_roster_id = await roster_identity.get_rosters_with_mine_flag(league)
        users = await sleeper_client.get_users(league.league_id)
    except SleeperAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch live league data: {exc}") from exc

    users_by_id = {u.get("user_id"): u for u in users}

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    def _player_row(pid: str) -> dict[str, Any]:
        p = players_by_id.get(pid)
        if p is None:
            # A real drafted roster could contain someone outside this
            # pipeline's draft-relevant pool (e.g. since filtered as a
            # free agent/no-team player in projections.py) -- surfaced
            # honestly rather than silently dropped or hard-failed, since
            # unlike lineup.py this is a read-only BROWSER, not a
            # computation that needs every player resolved to run.
            return {"player_id": pid, "name": None, "position": None, "team": None, "projected_points": None, "unresolved": True}
        return {
            "player_id": pid,
            "name": p.get("name"),
            "position": p.get("position"),
            "team": p.get("team"),
            "projected_points": p.get("projected_points"),
            "injury_status": p.get("injury_status"),
        }

    out = []
    for r in rosters:
        owner = users_by_id.get(r.get("owner_id"), {})
        player_ids = [str(pid) for pid in (r.get("players") or [])]
        out.append(
            {
                "roster_id": r.get("roster_id"),
                "owner_id": r.get("owner_id"),
                "is_mine": bool(r.get("is_mine")),
                "owner_display_name": owner.get("display_name"),
                "team_name": (owner.get("metadata") or {}).get("team_name") or owner.get("display_name") or f"Roster {r.get('roster_id')}",
                "player_count": len(player_ids),
                "players": [_player_row(pid) for pid in player_ids],
            }
        )
    # Mine first, then by roster_id -- a stable, predictable order for the browser UI.
    out.sort(key=lambda r: (not r["is_mine"], r["roster_id"] if r["roster_id"] is not None else 0))

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "my_roster_id": my_roster_id,
        "count": len(out),
        "rosters": out,
    }
