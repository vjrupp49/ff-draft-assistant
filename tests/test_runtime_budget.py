"""
Chunk 15 Task 3 -- runtime budget regression test.

NOT a performance/optimization target -- a deliberately generous ceiling
meant only to catch a CATASTROPHIC future regression (someone
accidentally disabling a cache, or 10x-ing mcts.ITERATIONS /
ROLLOUT_SIM_COUNT, say). Chunk 14's own 525-real-pick sweep found a
worst-case single recommend() call of 7.96s (with ordinary desktop
contention noise included -- Chunk 14 was itself briefly thrown off by a
stray uvicorn process left running, which is exactly the kind of ambient
load this ceiling needs to tolerate rather than flake on).

RUNTIME_CEILING_SECONDS is set to 20s: roughly 2.5x that observed worst
case, comfortably below this league's actual Sleeper pick timer (60s,
confirmed live in Chunk 12's dry run), and loose enough that normal
system load shouldn't trip it. If this test ever fails, it means
something is roughly an order of magnitude slower than expected -- a
real, dedicated benchmark/profiling pass (like Chunk 14 Task 4's direct
A/B) is the right tool for tracking smaller, incremental performance
drift; this test is a tripwire, not a stopwatch.
"""
from __future__ import annotations

import time
from typing import Any

from app.services import mcts as mcts_service

from tests._sim_helpers import build_state_with_real_roster

RUNTIME_CEILING_SECONDS = 20.0  # ~2.5x Chunk 14's observed 7.96s worst case -- see module docstring


def test_single_recommend_call_stays_within_runtime_budget(players_by_id: dict[str, dict[str, Any]]) -> None:
    # Mid-draft state (not an empty-roster edge case) so the roster-aware
    # rollout (Chunk 13's _roster_aware_pick) has realistic, non-trivial
    # work to do -- matching the conditions Chunk 14 actually profiled.
    state = build_state_with_real_roster(my_slot=5, players_by_id=players_by_id, seed=1, min_pick_no=80)

    t0 = time.perf_counter()
    mcts_service.recommend(state, players_by_id, seed=1)
    elapsed = time.perf_counter() - t0

    assert elapsed < RUNTIME_CEILING_SECONDS, (
        f"a single mcts.recommend() call took {elapsed:.1f}s, exceeding the "
        f"{RUNTIME_CEILING_SECONDS}s catastrophic-regression ceiling -- see this module's docstring "
        "before assuming it's just system noise (the ceiling already has ~2.5x margin over Chunk 14's "
        "observed worst case for exactly that reason)."
    )
