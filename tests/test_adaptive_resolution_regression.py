"""
Chunk 26 -- regression tests for adaptive tie resolution
(app/services/mcts.py's `_adaptively_resolve_tie`), and for reordering the
decision logic so it runs BEFORE the Chunk 24 ADP-margin tie-break, which
is now a fallback for genuinely-tied candidates only.

Chunk 25's diagnostic found `within_noise_of_leader` groups are often a
BUDGET-DILUTION artifact (recommend()'s ITERATIONS split across up to
CANDIDATE_BREADTH root candidates), not genuine indifference -- a
well-powered re-test shed at least the weakest member from all 6 traced
tied groups, and fully resolved 2 of 6. It also found the well-powered
winner does NOT reliably match what the ADP-margin tie-break would pick,
and surfaced a real bug at pick 122 (the sole real-ADP-matched candidate
in an otherwise-unmatched tied group winning the tie-break BY DEFAULT
even though a fair re-test showed it was the WORST option in the group).

===================================================================
CHUNK 67 -- MIGRATED ONTO THE FROZEN-TRAJECTORY REPLAY HARNESS
===================================================================
These six picks were pinned against `conftest.py`'s LIVE `players_by_id`
fixture (projections.py + adp.py, both live-fetched with a 24h TTL). That
made the pins move on their own timeline: they drifted -- and were
re-pinned with a documented root-cause each time -- across Chunks 24, 26,
30, 31, 33, 38, 39, 60, 62 and 63/64. Chunk 66's regression drifted them
again (5 of 6 failing) purely from an ADP/projection cache refresh, with
no code change involved. The Chunk 64 note in this file's history called
it: "consider loosening these ... to name-only, or accepting a
near-every-chunk re-pin."

Chunk 67 does neither -- it removes the moving part. The tests now run
through `replay_lib.harness` (Chunk 40), the exact mechanism already
protecting tests/test_chunk55-58 from this same instability:

  - TRAJECTORY: frozen, per pick, at data/replay_trajectories/
    chunk67_adaptive_pick{N}.json -- picks-before-N from the same
    tests/fixtures/chunk22_real_draft_picks.json real-draft history this
    file always used (my_slot=2, 10 teams), via `harness.freeze_trajectory`.
  - DATA: frozen at data/replay_snapshots/chunk40_20260826.json -- the
    canonical immutable projections/ADP snapshot Chunk 40 captured, reused
    (not re-captured: a fresh pull would just be a new thing to drift).

The expected values below are now a ONE-TIME pin: `mcts.recommend()`'s
output on (frozen trajectory + frozen snapshot + seed=1), verified
identical across repeated runs. They will not move again unless
`_adaptively_resolve_tie` / the ADP-margin tie-break / the MCTS internals
are deliberately changed -- in which case a failure here is real signal,
and the fix is to re-derive the pins from the (unchanged) frozen inputs,
not to chase live data.

What the frozen Aug-26 snapshot pins each pick to (seed=1):
  pick  39 -> Kyren Williams   adaptive=True  adp_tb=False  (400/600 iters, early stop)
  pick  59 -> Zay Flowers      adaptive=True  adp_tb=True   (full 600; {Flowers, Goff} stay tied, ADP-margin picks Flowers)
  pick  79 -> Tony Pollard     adaptive=True  adp_tb=True   (full 600; 3-way {Pollard, Sutton, RJ Harvey}, all would-start)
  pick  82 -> Courtland Sutton adaptive=True  adp_tb=False  (500/600; Sutton separates from Pollard directly)
  pick 102 -> Matthew Stafford adaptive=False adp_tb=False  (no tie; separates in the base 150 iters)
  pick 122 -> Matthew Stafford adaptive=False adp_tb=False  (no tie; the pick-122 default-promotion guard below still holds)

The full drift history (Chunks 24-64) is preserved in this file's git
log and in docs/handoff/ -- not reproduced here now that it's settled.

The data-independent synthetic unit tests for the no-real-ADP-match
default-promotion mechanism live in
tests/test_adp_margin_tiebreak_regression.py and were never affected by
any of this.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import mcts as mcts_service
from replay_lib import harness

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = str(REPO_ROOT / "data" / "replay_snapshots" / "chunk40_20260826.json")
TRAJECTORY_DIR = REPO_ROOT / "data" / "replay_trajectories"
SEED = 1

# The migrated tests hard-depend on the frozen snapshot + trajectories
# (same as tests/test_chunk55-58 depend on the Chunk 41 picklog). They are
# committed under data/replay_{snapshots,trajectories}/ via .gitignore
# negation. If they're somehow absent, skip with an actionable message
# rather than a bare FileNotFoundError deep in the harness.
_MISSING = [
    p
    for p in [Path(SNAPSHOT_PATH), *(TRAJECTORY_DIR / f"chunk67_adaptive_pick{n}.json" for n in (39, 59, 79, 82, 102, 122))]
    if not p.exists()
]
pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason=f"frozen replay fixtures missing: {[str(p) for p in _MISSING]} -- regenerate per this file's docstring",
)


def _replay(pick_no: int) -> dict:
    """recommend()'s result for one frozen decision point (frozen data + trajectory + seed)."""
    trajectory = str(TRAJECTORY_DIR / f"chunk67_adaptive_pick{pick_no}.json")
    return harness.replay_decision(trajectory, SNAPSHOT_PATH, seed=SEED)["recommend_result"]


# ---------------------------------------------------------------------
# The headline regression guard: pick 122's default-promotion bug.
# CHUNK 30: loosened to the actual bug signature -- the specific
# Jeudy/Njoku/Engram tied group no longer occurs at this pick, but
# "Jeudy must never win by default" still holds and is worth guarding
# directly, alongside the data-independent synthetic unit tests in
# test_adp_margin_tiebreak_regression.py.
# ---------------------------------------------------------------------

def test_pick_122_no_longer_promotes_unmatched_group_default_by_default() -> None:
    """
    Jerry Jeudy must never be the top recommendation here again: adaptive
    resolution correctly sheds him (a well-powered re-test found him
    significantly worse than David Njoku / Evan Engram) BEFORE the ADP
    tie-break ever sees the group -- so the tie-break never gets a chance
    to promote him just for being the only candidate with real ADP data.
    """
    top = _replay(122)["recommendations"][0]

    assert top["name"] != "Jerry Jeudy", (
        f"pick 122: Jerry Jeudy must not be promoted by default just for being the sole real-ADP-matched "
        f"candidate in an otherwise-unmatched tied group -- got {top['name']}, or the bug has regressed "
        "if this is Jeudy again"
    )


# ---------------------------------------------------------------------
# Real-draft replay: locks in the exact per-pick behavior at seed=1 across
# all 6 of Chunk 25's traced decision points. CHUNK 67: now a one-time pin
# against frozen inputs (see module docstring) -- re-derive from the
# unchanged frozen trajectory + snapshot only after a deliberate change to
# _adaptively_resolve_tie / the ADP-margin tie-break / MCTS internals.
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "pick_no,expected_top_name,expect_adaptive_applied,expect_adp_tie_break_applied",
    [
        (39, "Kyren Williams", True, False),
        (59, "Zay Flowers", True, True),
        (79, "Tony Pollard", True, True),
        (82, "Courtland Sutton", True, False),
        (102, "Matthew Stafford", False, False),
        (122, "Matthew Stafford", False, False),
    ],
)
def test_adaptive_resolution_replay_matches_expected_behavior(
    pick_no: int,
    expected_top_name: str,
    expect_adaptive_applied: bool,
    expect_adp_tie_break_applied: bool,
) -> None:
    result = _replay(pick_no)
    top = result["recommendations"][0]

    assert top["name"] == expected_top_name, (
        f"pick {pick_no}: expected top recommendation {expected_top_name}, got {top['name']}"
    )
    assert result["adaptive_resolution_applied"] is expect_adaptive_applied
    assert result["adp_tie_break_applied"] is expect_adp_tie_break_applied


def test_adaptive_resolution_can_stop_early_before_the_iteration_cap() -> None:
    """
    Adaptive resolution must be able to stop before burning the full
    ADAPTIVE_RESOLUTION_MAX_ITERATIONS budget once a tied group's leader
    has genuinely separated. On the frozen snapshot, pick 39 (Kyren
    Williams leading Josh Jacobs by ~32 pts) demonstrates this directly:
    the pass engages and resolves in 400 of the 600-iteration budget.

    CHUNK 67: re-pointed from pick 59 to pick 39. Pick 59 is a genuine
    {Flowers, Goff} near-tie on the frozen data that (correctly) never
    separates and burns the full 600 -- it can't demonstrate early
    stopping. Pick 39 does.
    """
    result = _replay(39)

    assert result["adaptive_resolution_applied"] is True
    assert 0 < result["adaptive_iterations_used"] < mcts_service.ADAPTIVE_RESOLUTION_MAX_ITERATIONS, (
        f"expected adaptive resolution to stop early (before the "
        f"{mcts_service.ADAPTIVE_RESOLUTION_MAX_ITERATIONS}-iteration cap) once pick 39's group resolved, "
        f"got {result['adaptive_iterations_used']} iterations used"
    )
