"""
Chunk 15 Task 1 -- automated positional-balance regression tests.

Encodes Chunks 9/13/14's manual "does draft_score glut or starve any
position relative to the rest of the league" check as a permanent,
automated pytest suite, using the SAME >1-count-from-league-median
threshold established across those chunks: first used in Chunk 9 to flag
the original QB glut (5-8 QBs on a roster that can only ever start 2),
reused in Chunk 13 to confirm that fix, reused again in Chunk 14's wider
35-seed/3-slot stress test that both this test's seed sweeps are modeled
on directly.

DOCUMENTED KNOWN-GOOD BASELINE (Chunk 14's own numbers, for comparing a
future failure against a REAL reference, not just a bare assertion):
  - slot 7, 20 seeds: my QB median=3 (league median 3), RB median=5
    (league 4), WR median=6 (league 6), TE median=2 (league 3).
  - slots 1/5/10 combined, 5 seeds each (15 runs): my QB median=3
    (league 2), RB median=5 (league 4), WR median=5 (league 6), TE
    median=2 (league 3).

SEED COUNT: Chunk 14 found 15-20 seeds enough to separate a real
glut/shortage from noise. This suite uses 15 for the main sweep and 5
each across 3 slots for the sensitivity check -- the documented floor of
Chunk 14's own "15-20 is enough" finding.

MCTS ITERATIONS: dropped to TEST_MCTS_ITERATIONS (30) from the production
default (150) for SPEED, not a change to what's tested -- same
recommend() -> _roster_aware_pick code path Chunk 13 fixed, coarser
per-pick search. The >1-from-league-median threshold is computed against
each run's OWN other-9-teams median (who never touch MCTS), so it stays
self-calibrating regardless of MCTS noise from the lower iteration count.

HONEST LIMITATION (Chunk 15): reverting Chunk 13's fixes does NOT
reliably push the QB/TE median past the >1 threshold in a broad random
sweep -- the pre-fix rollout's blind-greedy continuation is a
PROBABILISTIC tendency, partly self-diluted by a broad sweep of
independently-random opponent seeds. `test_chunk12_regression.py` is the
deterministic guard for that specific bug (it replays the exact
historical draft sequence that triggered it). Treat this suite as a
general "does draft_score stay broadly sane" health check.

===================================================================
CHUNK 67 -- MIGRATED ONTO A FROZEN DATA SNAPSHOT
===================================================================
Both sweeps below were run against `conftest.py`'s LIVE `players_by_id`
fixture (projections.py + adp.py, live-fetched, 24h TTL) -- so their
pass/fail state tracked "today's data mood", not code behavior:
  - `slot7_multiseed`'s WR-shortage xfail has flipped
    xfail<->XPASS<->xfail across Chunks 33/38/39 and again at Chunk 66,
    every flip traced to a data refresh, no code change involved.
  - `slot_sensitivity` had the same instability, papered over with
    `strict=False`.

Chunk 67 freezes the input data: both sweeps now run against
`data/replay_snapshots/chunk40_20260826.json` (the Chunk 40 immutable
projections/ADP snapshot, loaded via `replay_lib.harness.load_players_by_id`),
the same fix applied to tests/test_adaptive_resolution_regression.py.
The seeds were always frozen (`range(1, 16)` etc.); the data is now too.

FROZEN-DATA RESULT (deterministic, verified identical across repeated
runs) -- both sweeps show the residual positional imbalance that is
Known Limitation #1, so both stay xfail, now `strict=True` (deterministic
=> an unexpected XPASS means a real, deliberate improvement landed and
the marker must be updated, per this file's own "forced to be removed
rather than forgotten" discipline):
  - slot 7 (15 seeds):          RB +2.0, WR -2.0   (QB +0.0, TE +0.0)
  - slots 1/5/10 (5 seeds each): QB +2.0, RB +2.0, WR -2.0   (TE +0.0)

Fixing that imbalance is out of scope here (Chunk 67 is test
infrastructure only) and is a separate, already-made decision not to
touch positional balance before the real drafts. The full pre-Chunk-67
drift history (Chunks 30/33/38/39/62) is in this file's git log.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from app.services.mock_draft import run_mock_draft
from replay_lib import harness

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
MAX_DEVIATION_FROM_LEAGUE_MEDIAN = 1  # Chunk 9/13/14's threshold, unchanged here
TEST_MCTS_ITERATIONS = 30  # vs. production's 150 -- speed-only change, see module docstring

SLOT7_SEEDS = list(range(1, 16))  # 15 seeds -- see module docstring
SLOT_SENSITIVITY_SLOTS = (1, 5, 10)
SLOT_SENSITIVITY_SEEDS = list(range(1, 6))  # 5 seeds each, per Chunk 14 Task 2

# CHUNK 67: frozen data snapshot (see module docstring). Committed via
# .gitignore negation; skip loudly if absent rather than fail deep in a
# mock draft.
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "replay_snapshots" / "chunk40_20260826.json"
pytestmark = pytest.mark.skipif(
    not SNAPSHOT_PATH.exists(),
    reason=f"frozen snapshot missing: {SNAPSHOT_PATH} -- see tests/test_adaptive_resolution_regression.py docstring",
)


@pytest.fixture(scope="module")
def frozen_players_by_id() -> dict[str, dict[str, Any]]:
    """{player_id: player} from the pinned Chunk 40 snapshot -- immutable,
    so these sweeps' pass/fail state reflects code behavior, not live-data drift."""
    return harness.load_players_by_id(str(SNAPSHOT_PATH))


def _team_position_counts(
    all_picks: list[dict[str, Any]], players_by_id: dict[str, dict[str, Any]], num_teams: int = 10
) -> dict[int, dict[str, int]]:
    by_slot: dict[int, dict[str, int]] = {slot: defaultdict(int) for slot in range(1, num_teams + 1)}
    for pick in all_picks:
        p = players_by_id.get(pick["player_id"])
        if not p:
            continue
        by_slot[pick["slot"]][p["position"]] += 1
    return by_slot


def _run_sweep(
    slots_and_seeds: list[tuple[int, int]], players_by_id: dict[str, dict[str, Any]]
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """
    Runs one full mock draft per (my_slot, seed) pair with the
    draft_score strategy. Returns (my_counts, opp_counts): for each
    position, the list of counts across every run -- my_counts from the
    draft_score-strategy team, opp_counts pooled from every OTHER team in
    the SAME runs (the real opponent_model.py policy, unchanged).
    """
    my_counts: dict[str, list[int]] = defaultdict(list)
    opp_counts: dict[str, list[int]] = defaultdict(list)
    for my_slot, seed in slots_and_seeds:
        result = run_mock_draft(
            my_slot=my_slot, strategy="draft_score", opponent_seed=seed, players_by_id=players_by_id,
            mcts_iterations=TEST_MCTS_ITERATIONS,
        )
        by_slot = _team_position_counts(result["all_picks"], players_by_id)
        for pos in FANTASY_POSITIONS:
            my_counts[pos].append(by_slot[my_slot].get(pos, 0))
        for slot, counts in by_slot.items():
            if slot == my_slot:
                continue
            for pos in FANTASY_POSITIONS:
                opp_counts[pos].append(counts.get(pos, 0))
    return my_counts, opp_counts


def _assert_balanced(my_counts: dict[str, list[int]], opp_counts: dict[str, list[int]], label: str) -> None:
    failures = []
    details = []
    for pos in FANTASY_POSITIONS:
        my_median = statistics.median(my_counts[pos])
        league_median = statistics.median(opp_counts[pos])
        deviation = my_median - league_median
        details.append(f"{pos}: my median={my_median} league median={league_median} deviation={deviation:+.1f}")
        if abs(deviation) > MAX_DEVIATION_FROM_LEAGUE_MEDIAN:
            failures.append(details[-1])
    assert not failures, (
        f"{label}: positional balance violated (threshold is +/-{MAX_DEVIATION_FROM_LEAGUE_MEDIAN} from league "
        f"median -- see module docstring for Chunk 14's known-good reference numbers):\n"
        + "\n".join(failures)
        + "\n\nfull breakdown:\n"
        + "\n".join(details)
    )


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN LIMITATION #1 (WR shortage / RB glut). CHUNK 67: migrated onto the frozen Chunk 40 "
    "snapshot -- deterministic now, no longer drifts with live data. On that frozen data, slot 7 / 15 "
    "seeds shows RB +2.0 and WR -2.0 (QB +0.0, TE +0.0). Fixing positional balance is out of scope for "
    "Chunk 67 (test infra only) and a separate decision not to touch before the real drafts. An "
    "unexpected XPASS here means a deliberate balance fix landed -- update this marker. See module "
    "docstring's CHUNK 67 section.",
)
def test_positional_balance_slot7_multiseed(frozen_players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    Chunk 9's original QB glut (5-8 QBs) and Chunk 13's TE glut/QB
    shortage (5 TEs / 1 QB) would both fail this test outright -- this is
    the automated form of the exact check that caught both, at slot 7
    across 15 seeds.
    """
    slots_and_seeds = [(7, seed) for seed in SLOT7_SEEDS]
    my_counts, opp_counts = _run_sweep(slots_and_seeds, frozen_players_by_id)
    _assert_balanced(my_counts, opp_counts, "slot 7 (15 seeds)")


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN LIMITATION #1 (WR shortage / RB+QB glut). CHUNK 67: migrated onto the frozen Chunk 40 "
    "snapshot (was strict=False to paper over live-data drift -- now deterministic). On that frozen "
    "data, slots 1/5/10 combined shows QB +2.0, RB +2.0, WR -2.0 (TE +0.0). Same out-of-scope note as "
    "test_positional_balance_slot7_multiseed above.",
)
def test_positional_balance_slot_sensitivity(frozen_players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    Chunk 14 Task 2: re-run across DIFFERENT draft slots (1, 5, 10) to
    check the fix isn't slot-position-dependent.

    IMPORTANT: asserts against the COMBINED median across all slots/seeds
    together, NOT per-slot medians individually. Chunk 14 found individual
    per-slot samples (n=5 each) produce noisy, false-positive-looking
    flags that vanish once combined into the full 15-run sample. Do NOT
    "fix" this test by tightening it back to per-slot flagging -- increase
    SLOT_SENSITIVITY_SEEDS instead if per-slot sensitivity ever needs
    re-checking.
    """
    slots_and_seeds = [(slot, seed) for slot in SLOT_SENSITIVITY_SLOTS for seed in SLOT_SENSITIVITY_SEEDS]
    my_counts, opp_counts = _run_sweep(slots_and_seeds, frozen_players_by_id)
    _assert_balanced(my_counts, opp_counts, "slots 1/5/10 combined (5 seeds each)")
