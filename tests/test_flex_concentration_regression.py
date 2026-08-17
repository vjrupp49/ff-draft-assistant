"""
Chunk 20 -- regression tests for the FLEX-slot concentration discount
(app/services/portfolio.py's flex_concentration_discount_for, wired into
portfolio.py/shapley.py/mcts.py -- see portfolio.py's module comment for
the full root-cause story).

Chunk 19's live dry run found the app's own recommendations, followed
exactly, produced a real final roster of QB=1/TE=8 -- worse than the
original Chunk 12/13 bug, via a genuinely different mechanism: a
sequence of individually-defensible near-ties that, cumulatively,
produced an unusable roster, because nothing priced the risk of MULTIPLE
same-position players sharing the same small FLEX+SUPER_FLEX pool.

`fixtures/chunk19_real_draft_picks.json` is the actual pick-by-pick
history from that real draft (my_slot=10, 150 real picks) -- the most
direct possible guard against this exact regression recurring, tied to
real historical data rather than only synthetic mock seeds (same
methodology as test_chunk12_regression.py for the Chunk 13 fix).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services import portfolio as portfolio_service
from app.services.draft_state import DraftState

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chunk19_real_draft_picks.json"
MY_SLOT = 10  # the real Chunk 19 dry run's draft slot
SEED = 1


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
# Unit tests for flex_concentration_discount_for -- pure function, no
# network, no simulation needed.
# ---------------------------------------------------------------------

def test_flex_concentration_discount_te_rank1_is_undiscounted():
    # The FIRST TE sharing the pool is completely normal roster
    # construction (e.g. one elite pass-catching TE) -- no discount.
    assert portfolio_service.flex_concentration_discount_for("TE", 1) == 1.0


def test_flex_concentration_discount_te_decays_by_rank():
    d2 = portfolio_service.flex_concentration_discount_for("TE", 2)
    d3 = portfolio_service.flex_concentration_discount_for("TE", 3)
    d4 = portfolio_service.flex_concentration_discount_for("TE", 4)
    assert d2 == 0.5
    assert d3 == pytest.approx(0.30)
    assert d4 == pytest.approx(0.18)
    assert d2 > d3 > d4  # strictly decaying


def test_flex_concentration_discount_other_positions_undiscounted():
    """
    CHUNK 20 CORRECTION (documented, not swept under the rug): the first
    version of this fix applied the same aggressive discount to every
    position. Re-validating against the Chunk 9 harness found this
    caused a NEW regression -- WR ended up under league median (-2.0
    deviation) that hadn't existed before, since Tasks 1-3's evidence
    only ever confirmed a TE-specific problem. Scoped back to TE only,
    matching Chunk 10's own precedent of never touching a constant
    without directly-confirmed evidence. This test locks in that only TE
    is affected -- do NOT "fix" this by extending the discount to QB/RB/WR
    without first gathering the same kind of direct evidence Chunk 20
    Tasks 1-3 gathered for TE.
    """
    for position in ("QB", "RB", "WR"):
        assert portfolio_service.flex_concentration_discount_for(position, 2) == 1.0
        assert portfolio_service.flex_concentration_discount_for(position, 4) == 1.0


# ---------------------------------------------------------------------
# Real-draft replay: pick 71 is the clearest, most decisive real example
# this chunk found -- the best available QB's own immediate marginal
# value (301.65) clearly beat the eventually-picked TE's (247.73) by 54
# points at the time, yet the pre-fix engine's full recommendation showed
# them as a near-exact statistical tie (2606.7 vs 2606.1). This test
# locks in that the fix restores a clear, non-tied preference away from
# TE at this exact real historical point.
# ---------------------------------------------------------------------

def test_pick_71_no_longer_shows_false_te_near_tie(players_by_id: dict[str, dict[str, Any]]) -> None:
    real_picks = _load_real_picks()
    state = _state_before_pick(71, real_picks)

    result = mcts_service.recommend(state, players_by_id, seed=SEED)
    top = result["recommendations"][0]

    assert top["position"] != "TE", (
        f"pick 71: expected a non-TE top recommendation (this roster already has 2 TEs sharing the "
        f"FLEX+SUPER_FLEX pool), got {top['name']} ({top['position']}) -- the flex-concentration discount "
        "may have regressed"
    )

    te_entry = next((r for r in result["recommendations"] if r["position"] == "TE"), None)
    if te_entry is not None:
        assert not te_entry.get("within_noise_of_leader"), (
            f"pick 71: TE candidate {te_entry['name']} (score={te_entry['mcts_score']}) is still statistically "
            f"tied with the leader ({top['name']}, score={top['mcts_score']}) -- expected a clear, non-tied "
            "separation now that flex-slot concentration is priced, not a false near-tie"
        )
