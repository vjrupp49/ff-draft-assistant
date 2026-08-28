"""
POST /api/lineup/optimize -- Start/Bench Lineup Optimizer (Chunk 55).

Reuses app.services.vbd.allocate_roster_starters_with_flex_ranks DIRECTLY
-- itself a thin wrapper over `_allocate_starters`, the exact same
starter-allocation core this project has used since Chunks 2/7/9/10/20/
33/38 (compute_replacement_levels, portfolio.py's evaluate_roster,
shapley.py, mcts.py's roster-aware rollout policy all call it already).
No new allocation logic is introduced here -- only a new request/
response wrapper and roster sourcing, per this chunk's own brief.

TWO WAYS to supply a roster:
  - player_ids (list[str]): direct/synthetic. This is what every other
    planning route in this app already takes (portfolio.py, shapley.py,
    simulate.py's roster endpoint) and is the only way to exercise this
    endpoint meaningfully today -- see SCOPING NOTE below.
  - use_live_roster=True + roster_id: pulls a real roster from Sleeper's
    live, READ-ONLY /league/{id}/rosters endpoint for `league_key`.
    Requires roster_id explicitly because this project has never tracked
    which Sleeper roster_id/owner_id is "mine" anywhere -- draft_state.py's
    own docstring is explicit that draft SLOT, not Sleeper roster_id/
    user_id, is how "mine" is tracked everywhere else in this codebase.
    There is no existing mapping to infer a roster_id from, so Vincent
    supplies it rather than this endpoint guessing at one.

SCOPING NOTE (Chunk 55, stated explicitly, not silently glossed over):
both real leagues (Kiddos, Former Bradley Bums) are still pre_draft as of
this chunk -- neither has a real roster yet. The live-roster path above
is real, working code that calls Sleeper's genuine rosters endpoint, but
is genuinely UNTESTED against an actual post-draft roster (there isn't
one yet, for either league). Confirmed directly (not assumed): Sleeper's
rosters endpoint currently returns each team's `players` as `null` for
both leagues pre-draft -- handled below as a valid, empty "nothing to
optimize yet" response, not an error. What WAS validated this chunk: the
allocation logic itself, cross-checked directly against
allocate_roster_starters_with_flex_ranks on synthetic-but-realistic
completed 15-round rosters reused from Chunks 40/41's mock-draft
artifacts already on disk (data/replay_trajectories/) -- see this
chunk's test file and report for results. Genuine end-to-end validation
against a real drafted roster has to wait until after an actual draft.

BYE-WEEK DATA: NOT incorporated -- checked, and it would require new
infrastructure, not a cheap addition. This project's entire data
pipeline (app/services/projections.py, nflverse SEASON-TOTAL stats) has
never pulled any NFL schedule/game-date/bye-week source --
app/services/simulation.py's own docstring says as much explicitly
("does NOT model a schedule... that's a separate, later Phase 2").
Sleeper's cached player records (app/services/sleeper.py) don't carry a
bye-week field either. Adding real bye-week awareness means pulling and
maintaining a whole new external schedule data source -- genuinely out
of scope for this chunk, not silently ignored.

INJURY STATUS: incorporated -- it WAS cheaply available. Sleeper's
player data (already pulled/cached by
app.services.sleeper.SleeperClient.get_all_players, and already flowing
through projections.py for every other field) carries a real,
currently-populated `injury_status` field (checked directly against
today's data/players_cache.json: 447 real players currently
"Questionable", 110 "IR", 92 "NA", 41 "PUP", 8 "Out", etc -- not a mostly-
empty/inert field) that simply wasn't being copied into
build_baseline_projections()'s per-player output. Fixed with a one-line
addition there (see that module's CHUNK 55 note) and surfaced per player
in this endpoint's response so Vincent can see it alongside the start/
bench call. Deliberately NOT blended into the allocation math itself or
projected_points -- this project's established "no invented weighted
averages" principle (see draft_score.py's own module docstring) applies
here too: an unvalidated points penalty for "Questionable" would be a
new, unvalidated model; surfacing the real flag next to the real
projection lets Vincent apply his own judgment instead.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers._shared import resolve_league
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError, sleeper_client
from app.services.vbd import allocate_roster_starters_with_flex_ranks, compute_league_wide_percentiles

router = APIRouter()


class LineupOptimizeRequest(BaseModel):
    player_ids: Optional[list[str]] = Field(
        default=None,
        description="Sleeper player_ids making up the roster to optimize. Required unless use_live_roster=true.",
    )
    league_key: Optional[str] = Field(
        default=None, description="Which league (app/leagues.py registry). Omit for today's default."
    )
    use_live_roster: bool = Field(
        default=False,
        description=(
            "If true, ignore player_ids and pull the roster from Sleeper's live, read-only "
            "/rosters endpoint for `roster_id` in `league_key` instead."
        ),
    )
    roster_id: Optional[int] = Field(
        default=None,
        description="Sleeper roster_id to pull when use_live_roster=true (see module docstring for why this is explicit, not inferred).",
    )


@router.post("/api/lineup/optimize")
async def optimize_lineup(request: LineupOptimizeRequest) -> dict[str, Any]:
    league = resolve_league(request.league_key)

    if request.use_live_roster:
        if request.roster_id is None:
            raise HTTPException(status_code=400, detail="roster_id is required when use_live_roster=true")
        try:
            rosters = await sleeper_client.get_rosters(league.league_id)
        except SleeperAPIError as exc:
            raise HTTPException(status_code=502, detail=f"Could not fetch live rosters: {exc}") from exc
        roster = next((r for r in rosters if r.get("roster_id") == request.roster_id), None)
        if roster is None:
            raise HTTPException(
                status_code=404, detail=f"roster_id={request.roster_id} not found in league '{league.key}'"
            )
        # Sleeper returns `players: null` (not []) for a roster with no
        # picks yet -- both real leagues are pre_draft as of this chunk,
        # so this is the expected, common case today, not a bug.
        player_ids: list[str] = [str(pid) for pid in (roster.get("players") or [])]
    else:
        if request.player_ids is None:
            raise HTTPException(status_code=400, detail="player_ids is required unless use_live_roster=true")
        # NOTE: an explicitly-empty list ([]) is NOT the same as omitted
        # (None) -- it's a genuinely empty roster (pre-draft, or a team
        # with no picks) and falls through to the graceful empty-roster
        # response below, not this validation error (Chunk 55 Task 7).
        player_ids = [str(pid) for pid in request.player_ids]

    if not player_ids:
        # A genuinely empty roster -- pre-draft (both real leagues today)
        # or an empty synthetic list. Handled as a valid, unremarkable
        # response, not an error (Chunk 55 Task 7).
        return {
            "league_key": league.key,
            "league_name": league.league_name,
            "roster_size": 0,
            "starters": [],
            "bench": [],
            "note": "This roster has no players yet (pre-draft, or an empty roster) -- nothing to optimize.",
        }

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    roster_players = []
    unknown_ids = []
    for pid in player_ids:
        player = players_by_id.get(pid)
        if player is None:
            unknown_ids.append(pid)
        else:
            roster_players.append(player)
    if unknown_ids:
        raise HTTPException(status_code=404, detail=f"Unknown player_id(s): {unknown_ids}")

    # CHUNK 39: percentile_lookup computed from the FULL player pool, not
    # recomputed locally from this one roster's own (often tiny,
    # degenerate) same-position sample -- see vbd.py's _allocate_starters
    # docstring and mcts.py's identical precedent for single-roster
    # callers (portfolio.py, shapley.py do the same).
    percentile_lookup = compute_league_wide_percentiles(list(players_by_id.values()))
    started_ids, flex_ranks = allocate_roster_starters_with_flex_ranks(roster_players, percentile_lookup)

    def _row(p: dict[str, Any]) -> dict[str, Any]:
        pid = p["player_id"]
        return {
            "player_id": pid,
            "name": p.get("name"),
            "position": p.get("position"),
            "team": p.get("team"),
            "projected_points": p.get("projected_points"),
            "injury_status": p.get("injury_status"),
            "flex_rank": flex_ranks.get(pid),
        }

    starters = [_row(p) for p in roster_players if p["player_id"] in started_ids]
    bench = [_row(p) for p in roster_players if p["player_id"] not in started_ids]
    starters.sort(key=lambda r: r["projected_points"] or 0, reverse=True)
    bench.sort(key=lambda r: r["projected_points"] or 0, reverse=True)

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "roster_size": len(roster_players),
        "starters": starters,
        "bench": bench,
    }
