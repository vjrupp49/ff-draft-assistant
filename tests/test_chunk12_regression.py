"""
Chunk 15 Task 4 -- direct regression test against the REAL Chunk 12 draft.

`fixtures/chunk12_real_draft_picks.json` is the actual pick-by-pick
history from the real Sleeper practice draft (type "league_mock", tied to
the real Kiddos league settings) that originally surfaced this project's
QB-shortage/TE-glut bug during Chunk 12's live dry run -- my_slot=7, 150
real picks, trimmed here to just {pick_no, draft_slot, player_id} (the
fields DraftState.from_sleeper_picks needs). Historical data, not a
synthetic mock seed -- the most direct possible guard against this exact
bug recurring, independent of whatever a future mock-draft seed sweep
happens to produce.

CHUNK 15 CORRECTION TO THE ORIGINAL PLAN (documented, not swept under the
rug): this test was originally going to assert "recommends a QB, full
stop" at pick 14 AND pick 34, matching Chunk 13's own re-validation
report. Building this test surfaced a real, separate bug first: mcts.py's
reward evaluation was calling `evaluate_roster(..., seed=None)` --
unseeded regardless of what `seed` recommend() was given -- so
recommend(seed=1) was never actually deterministic (confirmed directly:
5 identical calls produced 5 different scores, one with a flipped #1
pick). Fixed in mcts.py (see that module's CHUNK 15 FIX note). Once
reward evaluation was properly seeded and reproducible, re-checking
across 8 different seeds showed the HONEST picture: at picks 14/34/87/114
the QB is a genuine, engine-flagged statistical near-tie with whatever
wins (`within_noise_of_leader=True`) -- not a confident loser the way the
pre-Chunk-13 bug produced, but also not a clean, seed-independent #1
either. Asserting "QB is THE #1 pick" at those specific points would
therefore be testing MCTS's ordinary near-tie sampling noise (see
mcts.py's own STABILITY NOTE), not the bug -- exactly the kind of flaky,
not-actually-testing-anything assertion this project's history warns
against. What IS robust, checked across all 8 seeds: pick 147 (the LAST
of my 15 real turns -- no "wait for later" possible, which is precisely
where the old bug's procrastination logic had zero excuse left) recommends
a QB outright, every single time. That's the strict assertion below.
Picks 14 and 34 assert the honest, engine-native criterion instead: QB is
either the top pick, or explicitly flagged statistically indistinguishable
from it -- which the pre-fix code never showed (its QB entries were
confidently, non-noise-explainably behind the leader; see Chunk 13's
commit message for the concrete numbers).

CAVEAT (documented, not solved here): player_ids are Sleeper's permanent
player identifiers and expected to stay stable, but this fixture will
need attention if `build_baseline_projections()` (see conftest.py's
`players_by_id` fixture) ever stops producing entries for one of these
specific historical players -- e.g. many seasons out, once a player's
career-long data ages out of nfl_data_py's lookback window entirely.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chunk12_real_draft_picks.json"
MY_SLOT = 7  # the real Chunk 12 dry run's draft slot
SEED = 1  # arbitrary but fixed -- now meaningfully reproducible post-Chunk-15's determinism fix


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


def _recommend(pick_no: int, players_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    real_picks = _load_real_picks()
    state = _state_before_pick(pick_no, real_picks)
    return mcts_service.recommend(state, players_by_id, seed=SEED)


def _assert_qb_top_or_statistically_tied(pick_no: int, players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    The pre-fix bug showed a QB confidently, non-noise-explainably behind
    the leader at every one of these decision points (see module
    docstring). Post-fix, QB should be either the outright top pick or
    explicitly flagged `within_noise_of_leader` -- i.e. a real contender,
    not dismissed -- which is the honest, engine-native signal to assert
    against a genuine near-tie region, rather than a specific winner that
    can legitimately vary by seed even on correct code.
    """
    result = _recommend(pick_no, players_by_id)
    top = result["recommendations"][0]
    qb_entry = next((r for r in result["recommendations"] if r["position"] == "QB"), None)
    assert qb_entry is not None, f"pick {pick_no}: no QB among the top candidates at all -- unexpected, investigate"
    is_top_or_tied = qb_entry is top or qb_entry.get("within_noise_of_leader")
    assert is_top_or_tied, (
        f"pick {pick_no}: QB ({qb_entry['name']}, score={qb_entry['mcts_score']}) is neither the top pick nor "
        f"statistically tied with it (top={top['name']}, score={top['mcts_score']}) -- this is the confident, "
        "non-noise-explainable QB dismissal the pre-Chunk-13 bug produced; the fix may have regressed"
    )


def test_recommends_qb_at_pick_147(players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    Pick 147 is my LAST real turn of the draft -- robust across all 8
    seeds checked while building this test (see module docstring), and
    the most decisive single check available: the old bug's "I'll get a
    QB later" reasoning has zero "later" left to appeal to here, so a
    QB recommendation at this exact point is the highest-signal evidence
    the fix is holding.
    """
    result = _recommend(147, players_by_id)
    top = result["recommendations"][0]
    assert top["position"] == "QB", (
        f"expected the outright top recommendation at pick 147 (my last real turn) to be a QB, got "
        f"{top['name']} ({top['position']}) instead -- the QB-shortage/TE-glut bug this fixture exists "
        "to guard against may have regressed"
    )


def test_qb_is_a_real_contender_at_pick_14(players_by_id: dict[str, dict[str, Any]]) -> None:
    _assert_qb_top_or_statistically_tied(14, players_by_id)


def test_qb_is_a_real_contender_at_pick_34(players_by_id: dict[str, dict[str, Any]]) -> None:
    _assert_qb_top_or_statistically_tied(34, players_by_id)
