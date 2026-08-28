"""
League Dashboard (Chunk 58): GET /api/dashboard/transactions and
GET /api/dashboard/power-rankings.

Deliberately NOT a full "league dashboard" with standings/best-team/
best-draft features -- those would mostly be fake placeholders right now
(see module docstring notes on each endpoint for why). Two real
components only:
  - transactions: Sleeper's actual transaction history, displayed as-is.
  - power-rankings: app.services.portfolio.evaluate_roster (Chunk 5,
    validated and reused throughout this project since) run across every
    roster in the league, reusing Chunk 56's roster_identity for "my"
    roster and rosters.py's team-name resolution pattern.

EXPLICITLY OUT OF SCOPE: real win/loss standings. Games haven't been
played and won't be for a long time -- there is nothing here to compute,
approximate, or fake. No standings endpoint/field exists in this module;
the frontend shows a plain "not available until games are played" note
instead of a synthetic-looking number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.routers._shared import resolve_league
from app.services import portfolio as portfolio_service
from app.services import roster_identity
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError, sleeper_client
from app.services.vbd import compute_league_wide_percentiles

router = APIRouter()

# Sleeper's transactions endpoint is per-round (its term for NFL week);
# round 0 covers pre-season/pre-Week-1 moves. This app has no NFL
# schedule/current-week data (see Chunk 55's bye-week scoping note for
# the same underlying gap), so rather than guess how many weeks matter,
# a small fixed range is fetched and merged -- real, actual data, just
# not exhaustive league history. Cheap: 4 read-only GETs per call.
TRANSACTION_ROUNDS_FETCHED = [0, 1, 2, 3]


@router.get("/api/dashboard/transactions")
async def league_transactions(
    league_key: Optional[str] = Query(default=None, description="Which league (app/leagues.py registry). Omit for today's default."),
) -> dict[str, Any]:
    """
    Real Sleeper transaction history (waiver claims, trades, free-agent
    adds/drops) for `league_key`, merged across TRANSACTION_ROUNDS_FETCHED
    and sorted most-recent-first. No modeling -- display only.

    Both real leagues are pre_draft as of this chunk: expect this to
    return an empty (or near-empty) list. That's correct, real behavior
    -- no waiver claims, trades, or free-agent moves are possible before
    a league has even drafted -- not a bug to fix.
    """
    league = resolve_league(league_key)

    try:
        rosters = await sleeper_client.get_rosters(league.league_id)
        users = await sleeper_client.get_users(league.league_id)
        raw_transactions: list[dict[str, Any]] = []
        for round_ in TRANSACTION_ROUNDS_FETCHED:
            raw_transactions.extend(await sleeper_client.get_transactions(league.league_id, round_))
    except SleeperAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch live league data: {exc}") from exc

    users_by_id = {u.get("user_id"): u for u in users}
    roster_owner_by_id = {r.get("roster_id"): r.get("owner_id") for r in rosters}

    def _team_name(roster_id: Optional[int]) -> str:
        owner = users_by_id.get(roster_owner_by_id.get(roster_id), {})
        return (owner.get("metadata") or {}).get("team_name") or owner.get("display_name") or f"Roster {roster_id}"

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    def _player_name(pid: Any) -> str:
        p = players_by_id.get(str(pid))
        return p["name"] if p else str(pid)

    # De-dupe (a transaction can appear in more than one round's response
    # for its own round) and sort most-recent-first.
    seen_ids: set[str] = set()
    transactions: list[dict[str, Any]] = []
    for tx in raw_transactions:
        tx_id = tx.get("transaction_id")
        if tx_id in seen_ids:
            continue
        seen_ids.add(tx_id)
        adds = tx.get("adds") or {}
        drops = tx.get("drops") or {}
        transactions.append(
            {
                "transaction_id": tx_id,
                "type": tx.get("type"),
                "status": tx.get("status"),
                "created": tx.get("created"),
                "roster_ids": tx.get("roster_ids") or [],
                "team_names": [_team_name(rid) for rid in (tx.get("roster_ids") or [])],
                "adds": [{"player_id": pid, "name": _player_name(pid), "to_roster_id": rid} for pid, rid in adds.items()],
                "drops": [{"player_id": pid, "name": _player_name(pid), "from_roster_id": rid} for pid, rid in drops.items()],
                "waiver_bid": (tx.get("settings") or {}).get("waiver_bid"),
            }
        )
    transactions.sort(key=lambda t: t.get("created") or 0, reverse=True)

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "rounds_fetched": TRANSACTION_ROUNDS_FETCHED,
        "count": len(transactions),
        "transactions": transactions,
    }


def _rank_rosters(
    rosters: list[dict[str, Any]],
    users_by_id: dict[Any, dict[str, Any]],
    players_by_id: dict[str, dict[str, Any]],
    percentile_lookup: dict[str, float],
) -> list[dict[str, Any]]:
    """Shared scoring/ranking core for both the real and demo Power Rankings views."""
    entries = []
    for r in rosters:
        owner = users_by_id.get(r.get("owner_id"), {})
        team_name = (owner.get("metadata") or {}).get("team_name") or owner.get("display_name") or f"Roster {r.get('roster_id')}"
        player_ids = [str(pid) for pid in (r.get("players") or [])]
        roster_players = [players_by_id[pid] for pid in player_ids if pid in players_by_id]

        # CHUNK 39: stable, externally-computed percentile table -- see
        # vbd.py's _allocate_starters docstring and this project's other
        # single-roster callers (lineup.py, trade.py's sibling routes).
        # seed=42: matches /api/portfolio/evaluate's own default (Chunk
        # 9-ish precedent) -- a Power Rankings dashboard should give a
        # STABLE score on reload, not jitter run-to-run from an unseeded
        # Monte Carlo draw every 10-roster comparison recomputes.
        result = portfolio_service.evaluate_roster(roster_players, percentile_lookup=percentile_lookup, seed=42)
        entries.append(
            {
                "roster_id": r.get("roster_id"),
                "team_name": team_name,
                "is_mine": bool(r.get("is_mine")),
                "roster_size": len(roster_players),
                "risk_adjusted_score": result["risk_adjusted_score"],
                "mean": result["mean"],
                "stddev": result["stddev"],
            }
        )
    entries.sort(key=lambda e: e["risk_adjusted_score"], reverse=True)
    for i, e in enumerate(entries, start=1):
        e["rank"] = i
    return entries


@router.get("/api/dashboard/power-rankings")
async def power_rankings(
    league_key: Optional[str] = Query(default=None, description="Which league (app/leagues.py registry). Omit for today's default."),
) -> dict[str, Any]:
    """
    Real portfolio.evaluate_roster() (Chunk 5, validated and reused
    throughout this project since) run across every roster in the
    league, ranked by risk_adjusted_score descending. "My" roster is
    flagged via app.services.roster_identity (Chunk 56) -- reused
    directly, not re-derived.

    Both real leagues are pre_draft: every roster is empty, so
    evaluate_roster([]) returns its own documented zero-value result for
    all 10 teams -- expect every team tied at risk_adjusted_score=0.0.
    That is correct: no one has drafted anything yet. Not a bug, not
    something to work around.
    """
    league = resolve_league(league_key)

    try:
        rosters, _my_roster_id = await roster_identity.get_rosters_with_mine_flag(league)
        users = await sleeper_client.get_users(league.league_id)
    except SleeperAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch live rosters: {exc}") from exc

    users_by_id = {u.get("user_id"): u for u in users}

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}
    percentile_lookup = compute_league_wide_percentiles(list(players_by_id.values()))

    rankings = _rank_rosters(rosters, users_by_id, players_by_id, percentile_lookup)

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "is_demo": False,
        "rankings": rankings,
    }


@router.get("/api/dashboard/power-rankings/demo")
async def power_rankings_demo(
    league_key: Optional[str] = Query(default=None, description="Which league (app/leagues.py registry) to score the demo roster shapes under. Omit for today's default."),
) -> dict[str, Any]:
    """
    DEMO MODE (Chunk 58 Task 4, optional -- included since it was cheap
    to build on top of _rank_rosters above): previews what Power Rankings
    looks like once a real draft completes, using a SYNTHETIC 10-team
    league built from Chunks 40/41's existing mock-draft artifact
    (data/replay_trajectories/chunk41_slot7_seed1_full_picklog.json, all
    10 draft slots' real picks) -- not newly generated data, and NOT a
    live Sleeper call of any kind (no real league data involved at all).

    `is_demo: true` is always present in the response so a caller can
    never mistake this for real data -- the frontend renders this behind
    an unmistakable "DEMO / SYNTHETIC DATA" banner, never blended into
    the real power-rankings view.
    """
    league = resolve_league(league_key)

    picklog_path = Path("data/replay_trajectories/chunk41_slot7_seed1_full_picklog.json")
    picklog = json.loads(picklog_path.read_text())
    by_slot: dict[int, list[str]] = {}
    for p in picklog:
        by_slot.setdefault(p["slot"], []).append(p["player_id"])

    demo_rosters = [{"roster_id": slot, "owner_id": f"demo_owner_{slot}", "players": ids, "is_mine": slot == 1} for slot, ids in by_slot.items()]
    demo_users_by_id = {f"demo_owner_{slot}": {"display_name": f"Demo Team {slot}"} for slot in by_slot}

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}
    percentile_lookup = compute_league_wide_percentiles(list(players_by_id.values()))

    rankings = _rank_rosters(demo_rosters, demo_users_by_id, players_by_id, percentile_lookup)

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "is_demo": True,
        "demo_source": "data/replay_trajectories/chunk41_slot7_seed1_full_picklog.json (Chunk 40/41 mock-draft artifact, all 10 draft slots)",
        "rankings": rankings,
    }
