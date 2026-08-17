"""
Chunk 24 -- regression tests for the ADP-margin tie-break
(app/services/mcts.py's `_apply_adp_margin_tie_break` / `_next_turn_pick_no`,
wired into `recommend()`).

USER FEEDBACK THAT TRIGGERED THIS: after Chunk 22's live combined-fix dry
run, the app still reached hard for real-market-safe players (e.g. Alvin
Kamara, real ADP 150.8, taken 88.8 picks before the user's next real turn)
over players with a tight or negative real-ADP margin who were genuinely
at risk of being gone. Chunk 23/24's diagnostic found this wasn't a
missing "wait value" concept or insufficient rollout depth -- reward is
purely a function of the assembled roster (confirmed by direct trace of
`evaluate_roster`'s signature: no ADP/availability argument exists at
all) -- but several of `within_noise_of_leader`'s flagged "ties" turned
out to be a BUDGET-DILUTION artifact of splitting a fixed iteration count
across up to CANDIDATE_BREADTH root candidates: a forced-root test giving
one candidate the full iteration budget alone resolved some of these
into real (if small) differences favoring the tighter-margin candidate in
4 of 5 real decision points tested across Chunks 23-24.

`fixtures/chunk22_real_draft_picks.json` is the real 150-pick history from
that live dry run (my_slot=2) -- the most direct possible guard against
this exact regression recurring, same methodology as
test_flex_concentration_regression.py (Chunk 20) and
test_opponent_model_adp_regression.py (Chunk 21).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chunk22_real_draft_picks.json"
MY_SLOT = 2  # the real Chunk 22 dry run's draft slot


def _load_real_picks() -> list[dict[str, Any]]:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _state_before_pick(pick_no: int, real_picks: list[dict[str, Any]]) -> DraftState:
    picks_before = [p for p in real_picks if p["pick_no"] < pick_no]
    state = DraftState.from_sleeper_picks(
        my_slot=MY_SLOT, sleeper_picks=picks_before, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS)
    )
    assert state.current_pick_no == pick_no
    assert state.is_my_turn
    return state


# ---------------------------------------------------------------------
# Unit tests for _next_turn_pick_no -- pure function, no network.
# ---------------------------------------------------------------------

def test_next_turn_pick_no_is_not_zero_while_on_the_clock():
    """
    Regression guard for the exact off-by-one bug Chunk 23 caught in an
    earlier diagnostic script: `state.picks_until_next_turn()`, called
    while already on the clock, returns 0 (a different question). This
    must return the NEXT real pick_no this slot is on the clock for.
    """
    # Pick 1 already made (by slot 1), so it's slot 2's turn NOW at pick 2 --
    # its NEXT turn after this one (10-team snake) is pick 19.
    state = DraftState.hypothetical(my_slot=2, picks_so_far=[{"pick_no": 1, "slot": 1, "player_id": "x"}], num_teams=10)
    assert state.current_pick_no == 2 and state.is_my_turn
    next_turn = mcts_service._next_turn_pick_no(state)
    assert next_turn != 0
    assert next_turn == 19


def test_next_turn_pick_no_matches_real_draft_sequence():
    real_picks = _load_real_picks()
    state = _state_before_pick(59, real_picks)
    assert mcts_service._next_turn_pick_no(state) == 62  # ground truth from the real fixture


# ---------------------------------------------------------------------
# Unit tests for _apply_adp_margin_tie_break -- pure function, synthetic data.
# ---------------------------------------------------------------------

def _r(name, mcts_score, market_adp, within_noise):
    return {"name": name, "mcts_score": mcts_score, "market_adp": market_adp, "within_noise_of_leader": within_noise}


def test_tie_break_promotes_tightest_margin_among_tied_candidates():
    results = [
        _r("Safe", 100.0, 150.8, True),   # leader, huge margin
        _r("AtRisk", 99.0, 63.0, True),   # tied with leader, tight margin
        _r("NotTied", 50.0, 10.0, False),  # not flagged tied -- must never be promoted
    ]
    out = mcts_service._apply_adp_margin_tie_break(results, next_turn_pick_no=62)
    assert out[0]["name"] == "AtRisk"


def test_tie_break_does_nothing_when_no_real_tie():
    results = [
        _r("Leader", 100.0, 150.8, True),
        _r("Second", 50.0, 63.0, False),
    ]
    out = mcts_service._apply_adp_margin_tie_break(results, next_turn_pick_no=62)
    assert out[0]["name"] == "Leader"


def test_tie_break_leaves_leader_when_it_already_has_the_tightest_margin():
    results = [
        _r("Leader", 100.0, 63.0, True),
        _r("Tied", 99.0, 150.8, True),
    ]
    out = mcts_service._apply_adp_margin_tie_break(results, next_turn_pick_no=62)
    assert out[0]["name"] == "Leader"


def test_unmatched_candidate_never_wins_the_tie_break():
    """
    CHUNK 24 explicit design decision: a candidate with no real market_adp
    match must never be PROMOTED by this tie-break -- there's no real
    signal to call it "at risk." It can still remain the leader if it was
    already ranked first (nothing here demotes it).
    """
    results = [
        _r("Leader", 100.0, 150.8, True),
        _r("Unmatched", 99.0, None, True),
        _r("Matched", 98.0, 63.0, True),
    ]
    out = mcts_service._apply_adp_margin_tie_break(results, next_turn_pick_no=62)
    assert out[0]["name"] == "Matched"  # the matched candidate wins, not the unmatched one despite similar score
    assert out[0]["name"] != "Unmatched"


def test_all_unmatched_tied_candidates_falls_back_to_existing_ranking_unchanged():
    results = [
        _r("Leader", 100.0, None, True),
        _r("Tied", 99.0, None, True),
    ]
    out = mcts_service._apply_adp_margin_tie_break(results, next_turn_pick_no=62)
    assert out == results  # completely unchanged -- genuine fallback, not a substitution


# ---------------------------------------------------------------------
# Real-draft replay: picks 59/79/39 are the exact real decision points
# Chunks 23-24 diagnosed. This locks in that the fix actually changes the
# top recommendation the way the diagnostic predicted it should.
#
# CHUNK 26 CORRECTION: pick 39 originally asserted Josh Jacobs here (the
# ADP tie-break's own pick at the time). Chunk 26 added adaptive tie
# resolution AHEAD of this tie-break -- at pick 39/seed=1 that pass now
# fully resolves the group on its own (Brock Bowers separates confidently,
# see test_adaptive_resolution_regression.py's own coverage of this exact
# pick), so the ADP tie-break never fires there anymore
# (`adp_tie_break_applied` is False). This is Chunk 26's fix working as
# designed -- adaptive resolution taking precedence over the ADP fallback
# per its own root-cause finding (Chunk 25 Task 3: a confidently-resolved
# winner can genuinely differ from the ADP tie-break's pick) -- not a
# regression in this one. Picks 59/79 still land on the ADP tie-break
# (their cores remain genuinely tied even after adaptive resolution), so
# those two still directly test what this file is named for.
#
# CHUNK 30 CORRECTION: after migrating projections.py off nfl_data_py's
# dead stats source onto current 2025 data (see that chunk's report), the
# picture flipped again -- pick 59 now resolves on its own (adaptive
# resolution alone, no tie-break needed, see
# test_adaptive_resolution_regression.py), while pick 39 now DOES land on
# the ADP tie-break (Josh Jacobs, real ADP 32.4 -- the tightest margin of
# its now-current tied group). Re-verified each directly (roster context,
# real ADP alignment) before repinning, not a blind re-recording.
#
# CHUNK 31 CORRECTION (LA/LAR team-abbreviation fix -- isolated from the
# Chunk 30 migration above): fixing team_changed()'s "LA" vs "LAR"
# mismatch (see app/services/adp.py and test_adaptive_resolution_regression.py's
# own matching correction for the full root-cause writeup) restored Kyren
# Williams' real projected_points (277.8, up from a wrongly-suppressed
# 177.3), which now beats Josh Jacobs (242.0, unaffected) outright via
# adaptive resolution alone -- `adp_tie_break_applied` is False for pick 39
# now, so it's no longer a valid example of THIS test's specific mechanism
# (same fate pick 59 had after Chunk 26, see the CHUNK 26 note above).
# Removed from this parametrize list rather than repinned to a winner this
# test can't actually demonstrate; pick 79 remains genuinely tied and
# still exercises the tie-break directly.
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "pick_no,expected_top_name",
    [
        (79, "Tony Pollard"),   # real ADP 83.3, margin +1.3 to next turn (82) -- tightest of the genuinely-tied set
    ],
)
def test_tie_break_promotes_the_at_risk_candidate_at_real_decision_points(
    pick_no: int, expected_top_name: str, players_by_id: dict[str, dict[str, Any]]
) -> None:
    real_picks = _load_real_picks()
    state = _state_before_pick(pick_no, real_picks)

    result = mcts_service.recommend(state, players_by_id, seed=1)
    top = result["recommendations"][0]

    assert top["name"] == expected_top_name, (
        f"pick {pick_no}: expected the ADP-margin tie-break to promote {expected_top_name} "
        f"(tightest real-ADP margin among the statistically-tied candidates), got {top['name']} instead"
    )
