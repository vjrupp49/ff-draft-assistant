"""
Chunk 15 Task 2 -- draft-end boundary regression test.

Permanent form of Chunk 14 Task 5's direct methodology: monkeypatch
mcts.evaluate_roster to record every roster size it's called with during
a real recommend() call at pick 149 and pick 150 (the last two picks of
this league's 150-pick draft), and assert none ever exceeds the real
15-slot roster max -- i.e. `mcts._draft_is_over` (Chunk 13 Fix #2) is
still preventing MCTS's lookahead from inventing fictional round-16+
states, the exact bug Chunk 13 found and fixed for the last 1-2 of my
real turns each draft.

NEGATIVE CONTROL (proves this test isn't vacuous): see
`test_negative_control_phantom_roster_without_guard` below -- it
forcibly disables `_draft_is_over` and asserts a phantom (>15) roster
DOES appear. Skipped by default (the suite's default run only tests WITH
the guard active, per this chunk's brief); run explicitly with
`RUN_NEGATIVE_CONTROL=1 pytest tests/test_draft_end_boundary.py` to prove
this suite is exercising something real, not passing trivially.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import pytest

from app.config import NUM_DRAFT_ROUNDS, NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState, slot_on_the_clock

from tests._sim_helpers import simulate_n_picks

REAL_ROSTER_MAX = NUM_DRAFT_ROUNDS  # 15 -- the real per-team roster cap this league actually has


def _max_roster_size_seen(
    state: DraftState, players_by_id: dict[str, dict[str, Any]], seed: int, disable_guard: bool = False
) -> Optional[int]:
    """Runs one real recommend() call, spying on every evaluate_roster call's roster size."""
    sizes: list[int] = []
    real_evaluate_roster = mcts_service.evaluate_roster
    real_draft_is_over = mcts_service._draft_is_over

    def spy(roster_players, *args, **kwargs):
        sizes.append(len(roster_players))
        return real_evaluate_roster(roster_players, *args, **kwargs)

    mcts_service.evaluate_roster = spy
    if disable_guard:
        mcts_service._draft_is_over = lambda s: False
    try:
        mcts_service.recommend(state, players_by_id, seed=seed)
    finally:
        mcts_service.evaluate_roster = real_evaluate_roster
        mcts_service._draft_is_over = real_draft_is_over
    return max(sizes) if sizes else None


@pytest.fixture(scope="module")
def picks_148(players_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return simulate_n_picks(148, players_by_id, seed=7)


@pytest.fixture(scope="module")
def picks_149(picks_148: list[dict[str, Any]], players_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    # Same seed as picks_148 -- np.random.default_rng(seed) is deterministic,
    # so re-simulating 149 picks with the identical seed reproduces the
    # SAME first 148 picks plus one new, consistent 149th (see
    # simulate_n_picks's docstring for why this is safe/cheap rather than
    # threading rng state across calls).
    extra = simulate_n_picks(149, players_by_id, seed=7)[-1]
    return picks_148 + [extra]


def test_no_phantom_roster_at_pick_149(picks_148: list[dict[str, Any]], players_by_id: dict[str, dict[str, Any]]) -> None:
    my_slot = slot_on_the_clock(149, NUM_TEAMS)
    state = DraftState.hypothetical(
        my_slot=my_slot, picks_so_far=picks_148, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS)
    )
    assert state.current_pick_no == 149
    assert state.is_my_turn

    max_size = _max_roster_size_seen(state, players_by_id, seed=1)
    assert max_size is not None
    assert max_size <= REAL_ROSTER_MAX, (
        f"pick 149: evaluate_roster saw a {max_size}-player roster, real max is {REAL_ROSTER_MAX} -- "
        "a fictional round 16+ was simulated (Chunk 13 Fix #2 regressed)"
    )


def test_no_phantom_roster_at_pick_150(picks_149: list[dict[str, Any]], players_by_id: dict[str, dict[str, Any]]) -> None:
    my_slot = slot_on_the_clock(150, NUM_TEAMS)
    state = DraftState.hypothetical(
        my_slot=my_slot, picks_so_far=picks_149, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS)
    )
    assert state.current_pick_no == 150
    assert state.is_my_turn

    max_size = _max_roster_size_seen(state, players_by_id, seed=1)
    assert max_size is not None
    assert max_size <= REAL_ROSTER_MAX, (
        f"pick 150: evaluate_roster saw a {max_size}-player roster, real max is {REAL_ROSTER_MAX} -- "
        "a fictional round 16+ was simulated (Chunk 13 Fix #2 regressed)"
    )


@pytest.mark.skipif(
    os.environ.get("RUN_NEGATIVE_CONTROL") != "1",
    reason="negative control -- proves the guard is necessary, not part of the suite's default run (see module docstring)",
)
def test_negative_control_phantom_roster_without_guard(
    picks_149: list[dict[str, Any]], players_by_id: dict[str, dict[str, Any]]
) -> None:
    """
    Proves the pick-150 test above isn't vacuous: with `_draft_is_over`
    forcibly disabled, a phantom (>15) roster DOES appear. Deliberately
    not run by default -- it demonstrates the bug, so a normal green
    suite run shouldn't include it.
    """
    my_slot = slot_on_the_clock(150, NUM_TEAMS)
    state = DraftState.hypothetical(
        my_slot=my_slot, picks_so_far=picks_149, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS)
    )
    max_size = _max_roster_size_seen(state, players_by_id, seed=1, disable_guard=True)
    assert max_size is not None
    assert max_size > REAL_ROSTER_MAX, (
        "expected disabling _draft_is_over to allow a phantom (>15) roster, but it didn't -- "
        "this negative control failed, meaning the positive test above may not be testing anything real"
    )
