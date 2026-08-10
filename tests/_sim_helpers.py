"""
Shared test-only simulation helpers (Chunk 15) -- NOT a test module itself
(deliberately not named `test_*.py` so pytest doesn't try to collect it).

Reused across test_draft_end_boundary.py and test_runtime_budget.py so
neither reimplements "simulate N picks fast via opponent_model" or
"advance a real DraftState to a specific real turn" on its own -- same
project principle applied everywhere else (reuse draft_state.py/vbd.py/
opponent_model.py rather than duplicating their logic).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import opponent_model
from app.services import vbd as vbd_service
from app.services.draft_state import DraftState


def simulate_n_picks(n: int, players_by_id: dict[str, dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """
    Simulates the first `n` picks of a draft purely via opponent_model.py
    (fast, no MCTS) -- used to cheaply reach a deep, plausible draft state
    for tests that only care about behavior near the END of the draft,
    without paying for 148 real MCTS calls to get there.
    """
    state = DraftState(my_slot=1, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS))
    rng = np.random.default_rng(seed)
    all_players = list(players_by_id.values())
    for _ in range(n):
        vbd_ranked = vbd_service.calculate_vbd(all_players, drafted_player_ids=state.drafted_player_ids)
        adp_ranks = opponent_model.build_adp_proxy_ranks(vbd_ranked)
        available = [
            p for p in all_players
            if p["player_id"] not in state.drafted_player_ids and p["position"] in vbd_service.FANTASY_POSITIONS
        ]
        team_counts = state.position_counts(state.slot_on_the_clock_now, players_by_id)
        pid = opponent_model.sample_pick(rng, team_counts, available, state.current_pick_no, adp_ranks)
        state.add_pick(pid)
    return [{"pick_no": p.pick_no, "slot": p.slot, "player_id": p.player_id} for p in state.picks]


def build_state_with_real_roster(
    my_slot: int, players_by_id: dict[str, dict[str, Any]], seed: int, min_pick_no: int = 80
) -> DraftState:
    """
    Builds a DraftState at `my_slot`'s first real turn at/after
    `min_pick_no`, using cheap VBD-greedy picks for "my" turns along the
    way (not MCTS -- the caller doesn't need realistic picks, just a
    non-trivially-sized real roster to test against) and opponent_model
    for every other team's turns. Used by tests that need a mid-draft
    state with actual roster depth, not an empty-roster edge case.
    """
    state = DraftState(my_slot=my_slot, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS))
    rng = np.random.default_rng(seed)
    all_players = list(players_by_id.values())
    while not (state.is_my_turn and state.current_pick_no >= min_pick_no):
        vbd_ranked = vbd_service.calculate_vbd(all_players, drafted_player_ids=state.drafted_player_ids)
        if state.is_my_turn:
            state.add_pick(vbd_ranked[0]["player_id"])
        else:
            adp_ranks = opponent_model.build_adp_proxy_ranks(vbd_ranked)
            available = [
                p for p in all_players
                if p["player_id"] not in state.drafted_player_ids and p["position"] in vbd_service.FANTASY_POSITIONS
            ]
            team_counts = state.position_counts(state.slot_on_the_clock_now, players_by_id)
            pid = opponent_model.sample_pick(rng, team_counts, available, state.current_pick_no, adp_ranks)
            state.add_pick(pid)
    return state
