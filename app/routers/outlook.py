"""
GET /api/outlook/top-picks -- real Draft Score (MCTS) ranking of the top
candidates for a fresh, 0-picks-made board, for the Draft Outlook page
(Chunk 54). Reuses app.services.mcts.recommend() unchanged, with the SAME
defaults the live view uses (Task 2: "consistent with what Vincent will
actually see live") -- no separate/cheaper tuning for this view.

GET /api/outlook/survival -- "likely available at pick N" board-risk view
for the Draft Outlook page (Chunk 54).

Both are planning/browsing routes, per Chunk 53's classification -- see
app/routers/_shared.py's resolve_league.

survival reuses app/services/survival.py's Monte Carlo replay (itself a
reuse of opponent_model.py's real-ADP sampling machinery, Chunks 21/32/41)
rather than running a fresh full MCTS search per hypothetical pick
number -- see that module's docstring for the full method and its stated
limitations.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.routers._shared import resolve_league
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState
from app.services.opponent_model import build_adp_proxy_ranks, build_market_adp_ranks, sample_pick
from app.services.projections import build_baseline_projections
from app.services.survival import DEFAULT_NUM_REPLAYS, estimate_survival_probabilities
from app.services.vbd import FANTASY_POSITIONS, calculate_vbd

router = APIRouter()


@router.get("/api/outlook/top-picks")
async def top_picks(
    my_slot: int = Query(..., ge=1, description="Which draft slot to evaluate (1..num_teams)"),
    league_key: Optional[str] = Query(default=None, description="Which league (app/leagues.py registry). Omit for today's default."),
    top_n: int = Query(default=12, ge=1, le=20),
    seed: Optional[int] = Query(default=None, description="Omit for a fresh random draw each call"),
) -> dict[str, Any]:
    league = resolve_league(league_key)
    if my_slot > league.num_teams:
        raise HTTPException(status_code=400, detail=f"my_slot={my_slot} exceeds this league's num_teams ({league.num_teams})")

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    state = DraftState.hypothetical(
        my_slot=my_slot, picks_so_far=[], num_teams=league.num_teams, roster_positions=list(league.roster_positions)
    )

    # mcts_service.recommend() requires it to LITERALLY be my_slot's turn --
    # for any slot but 1, a genuine 0-picks-made state isn't there yet. Since
    # nothing real has happened before the draft even starts, there's no
    # real "what would the other teams actually do" signal to condition on
    # either -- so, exactly like app/services/survival.py's board-risk
    # replay, this pre-advances the board ONE realization using the same
    # real-ADP opponent_model.sample_pick machinery MCTS's own rollouts use
    # (app.services.mcts._advance_opponents does the identical thing
    # mid-search; this is that same idea, run once up front here rather
    # than duplicated/imported from a leading-underscore internal).
    picks_simulated = 0
    if not state.is_my_turn:
        all_players = list(players_by_id.values())
        vbd_full = calculate_vbd(all_players, drafted_player_ids=state.drafted_player_ids)
        adp_ranks = build_market_adp_ranks(all_players, build_adp_proxy_ranks(vbd_full))
        rng = np.random.default_rng(seed)
        guard = 0
        while not state.is_my_turn and guard < state.num_teams * 2:
            available = [p for p in all_players if p["player_id"] not in state.drafted_player_ids and p["position"] in FANTASY_POSITIONS]
            if not available:
                break
            team_counts = state.position_counts(state.slot_on_the_clock_now, players_by_id)
            pick = sample_pick(rng, team_counts, available, state.current_pick_no, adp_ranks)
            if pick is None:
                break
            state.add_pick(pick)
            picks_simulated += 1
            guard += 1

    result = mcts_service.recommend(state, players_by_id, top_n=top_n, seed=seed)

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "my_slot": my_slot,
        "current_pick_no": state.current_pick_no,
        "picks_simulated_before_my_turn": picks_simulated,
        "note": (
            None if picks_simulated == 0 else
            f"my_slot={my_slot} isn't on the clock at pick 1, so the {picks_simulated} pick(s) before your "
            "turn were simulated via the same real-ADP opponent model MCTS itself uses, not left blank."
        ),
        "recommendations": result["recommendations"],
    }


@router.get("/api/outlook/survival")
async def survival(
    pick_no: int = Query(..., ge=1, description="Overall pick number to estimate board risk at (e.g. 24 for the pick just before your 3rd turn in a 10-team snake)"),
    league_key: Optional[str] = Query(default=None, description="Which league (app/leagues.py registry). Omit for today's default."),
    top_n: int = Query(default=40, ge=1, le=200, description="How many of today's top-VBD players to report survival odds for"),
    num_replays: int = Query(default=DEFAULT_NUM_REPLAYS, ge=20, le=2000),
    seed: Optional[int] = Query(default=None, description="Omit for a fresh random draw each call"),
) -> dict[str, Any]:
    league = resolve_league(league_key)

    total_picks = league.num_teams * len(league.roster_positions)
    if pick_no > total_picks:
        raise HTTPException(status_code=400, detail=f"pick_no={pick_no} exceeds this league's total draft length ({total_picks} picks)")

    projections_payload = await build_baseline_projections()
    players_by_id = {p["player_id"]: p for p in projections_payload["players"]}

    # A fresh, 0-picks-made hypothetical state -- this is a PRE-DRAFT
    # browsing view (per Chunk 54's framing: "who's likely still around
    # before the draft even starts"), not a mid-draft recompute. my_slot
    # is inert here (every pick is sampled the same ADP+need-driven way
    # regardless of whose turn it is -- see survival.py's docstring), so
    # a fixed placeholder value is fine.
    state = DraftState.hypothetical(
        my_slot=1, picks_so_far=[], num_teams=league.num_teams, roster_positions=list(league.roster_positions)
    )

    ranked = calculate_vbd(list(players_by_id.values()), drafted_player_ids=state.drafted_player_ids)
    top_candidates = ranked[:top_n]

    survival_probs = estimate_survival_probabilities(
        state, players_by_id, target_pick_no=pick_no, num_replays=num_replays, seed=seed
    )

    players = [
        {
            "player_id": p["player_id"],
            "name": p["name"],
            "position": p["position"],
            "team": p.get("team"),
            "vbd": p["vbd"],
            "market_adp": p.get("market_adp"),
            "survival_probability": round(survival_probs.get(p["player_id"], 0.0), 4),
        }
        for p in top_candidates
    ]

    return {
        "league_key": league.key,
        "league_name": league.league_name,
        "pick_no": pick_no,
        "num_replays": num_replays,
        "count": len(players),
        "players": players,
    }
