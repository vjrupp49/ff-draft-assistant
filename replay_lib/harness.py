"""
Chunk 40 -- fixed-trajectory replay harness (infrastructure only, see the
chunk's own report for why this exists: Chunk 39 left the WR/QB balance
question confirmed-worse-but-unattributable, because every fresh full-draft
comparison since Chunk 38 stacked two independent confounds -- live
ADP/projection data drifting between runs, AND one early decision cascading
into a totally different rest-of-draft. This module lets two CODE VERSIONS
be compared on the exact same decision by holding both trajectory and data
constant and varying only the code under test).

WHY THIS LIVES OUTSIDE app/, NOT AS app/services/replay_harness.py: the
whole point of this harness is to run `app.services.mcts.recommend()` (and
friends) under TWO DIFFERENT git commits in the same comparison -- see
scripts/replay_run.py, which selects which commit's `app` package gets
imported via a REPLAY_APP_ROOT env var + sys.path ordering, one subprocess
per commit. Old commits (e.g. pre-Chunk-33, pre-Chunk-38) obviously don't
contain this Chunk-40 module -- if this file lived inside the `app` package
itself, importing `app.services.replay_harness` while REPLAY_APP_ROOT points
at an old worktree would fail outright (that commit's `app` package has no
such file), or worse, silently succeed by falling through to some OTHER
copy of `app` on sys.path, defeating the whole "which app package resolves
depends only on which commit we're testing" design. Keeping this module in
its own top-level `replay_lib` package means it's ALWAYS imported from the
current (Chunk 40+) repo regardless of which commit's `app` package is
under test in a given subprocess -- see scripts/replay_run.py's own
docstring for the exact sys.path mechanics.

THREE CAPABILITIES (Chunk 40 tasks 1-3):

1. Data snapshot capture/reload (`capture_data_snapshot` /
   `load_players_by_id`). app/services/projections.py's
   `build_baseline_projections()` ALREADY writes its full output to a
   24h-TTL disk cache (data/baseline_projections.json) -- confirmed by
   reading that module directly before building anything new here. What's
   missing is a NAMED, IMMUTABLE copy: the existing cache is a single
   mutable path that silently changes if 24h elapses or anything calls
   `force_refresh=True` mid-comparison, which is exactly the data-drift
   confound Chunk 39 hit. `capture_data_snapshot` just calls the existing
   pipeline once and writes its return value to a new, distinct,
   never-overwritten file -- ZERO changes to projections.py/adp.py needed
   (both already return/accept plain, directly-serializable dicts).

2. Trajectory freezing (`freeze_trajectory` / `load_frozen_trajectory`).
   app/services/draft_state.py's `DraftState.from_sleeper_picks` ALREADY
   builds exact replayable state from a list of {pick_no, draft_slot,
   player_id} dicts -- confirmed by reading that module directly, and by
   tests/test_adaptive_resolution_regression.py's own `_state_before_pick`
   helper, which already does exactly this (against
   tests/fixtures/chunk22_real_draft_picks.json, a REAL frozen trajectory
   that's been sitting in this repo since Chunk 24). What's missing is a
   REUSABLE, general version of that pattern -- not hardcoded to one test
   file's one fixture -- that can freeze a cutoff point from ANY full pick
   log (a real Sleeper draft's picks, or a fresh synthetic
   mock_draft.run_mock_draft() run) and serialize it so replay doesn't
   need to re-simulate anything before that point. ZERO changes to
   draft_state.py needed.

3. The replay itself (`replay_decision`). Loads a frozen trajectory + a
   pinned snapshot and calls `app.services.mcts.recommend()` exactly the
   way production (app/services/draft_score_engine.py) and the
   Chunk-37-corrected mock_draft.py harness do (top_n=CANDIDATE_BREADTH,
   not top_n=1 -- see mock_draft.py's own Chunk 37 fix note for why that
   distinction silently disabled tie-break logic for years). Also computes
   would-start status per candidate against the roster AS OF that pick
   (via vbd.py's existing `allocate_roster_starters`) -- the same
   instrumentation format used in every prior instrumented decision-point
   report (Chunk 32/36/38), which recommend() itself doesn't return.

CONCLUSION FOR THIS CHUNK'S SCOPE: no hooks were needed in vbd.py, mcts.py,
portfolio.py, shapley.py, draft_state.py, or projections.py -- every
capability this chunk needs already existed cleanly in those modules,
confirmed by reading them directly (not assumed). This module is pure
new, additive glue code around existing, unmodified capabilities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services import vbd as vbd_service
from app.services.draft_state import DraftState, slot_on_the_clock
from app.services.projections import build_baseline_projections

DEFAULT_SNAPSHOT_DIR = "data/replay_snapshots"
DEFAULT_TRAJECTORY_DIR = "data/replay_trajectories"


class ReplayHarnessError(RuntimeError):
    """Raised for harness-specific problems (bad/inconsistent frozen state, name collisions, etc)."""


# ---------------------------------------------------------------------
# Task 1: data snapshot capture/reload
# ---------------------------------------------------------------------


async def capture_data_snapshot(
    name: str, out_dir: str = DEFAULT_SNAPSHOT_DIR, force_refresh: bool = False
) -> str:
    """
    Calls the EXISTING `build_baseline_projections()` pipeline once (its
    own 24h-TTL cache is reused unless `force_refresh=True`, same as any
    other caller) and writes the returned payload to
    `<out_dir>/<name>.json` -- a NAMED file that is never auto-refreshed
    or overwritten by anything else in the app, unlike
    `projections.PROJECTIONS_CACHE_PATH`, which anything calling
    `build_baseline_projections()` elsewhere (a live server, another test
    run) can silently roll forward from under a long-running comparison.

    Deliberately refuses to overwrite an existing snapshot of the same
    name -- snapshots are meant to be immutable-by-convention (pick a new
    `name` for a fresh pull) so a comparison that's already referencing
    one file path can never have its data silently change out from under
    it after the fact.
    """
    payload = await build_baseline_projections(force_refresh=force_refresh)
    out_path = Path(out_dir) / f"{name}.json"
    if out_path.exists():
        raise ReplayHarnessError(
            f"Snapshot '{name}' already exists at {out_path} -- snapshots are immutable by convention "
            "(this is the whole point: a comparison referencing this file must never see its data change "
            "later). Pick a new name for a fresh pull."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(out_path)


def load_players_by_id(snapshot_path: str) -> dict[str, dict[str, Any]]:
    """{player_id: player} from a frozen snapshot file -- same shape as
    tests/conftest.py's `players_by_id` fixture, just sourced from a
    pinned file instead of a live (TTL-cached, mutable) pipeline call."""
    with open(snapshot_path, encoding="utf-8") as f:
        payload = json.load(f)
    return {p["player_id"]: p for p in payload["players"]}


# ---------------------------------------------------------------------
# Task 2: trajectory freezing
# ---------------------------------------------------------------------


def freeze_trajectory(
    all_picks: list[dict[str, Any]],
    pick_no: int,
    my_slot: int,
    name: str,
    out_dir: str = DEFAULT_TRAJECTORY_DIR,
    num_teams: int = NUM_TEAMS,
    roster_positions: Optional[list[str]] = None,
    source: str = "",
) -> str:
    """
    Freezes every pick strictly before `pick_no` from `all_picks` into a
    self-contained, replayable file at `<out_dir>/<name>.json`.

    `all_picks` items need `pick_no`, `player_id`, and EITHER `slot`
    (mock_draft.py's own pick-log key) or `draft_slot` (Sleeper's real
    pick key, also tests/fixtures/chunk22_real_draft_picks.json's key) --
    accepted directly, no reshaping needed by the caller, so this works
    unchanged against a real Sleeper draft's picks, an existing test
    fixture, OR a fresh mock_draft.run_mock_draft() result's `all_picks`.

    Refuses to overwrite an existing trajectory of the same name, for the
    same immutability-by-convention reason as `capture_data_snapshot`.
    """
    picks_before = []
    for p in all_picks:
        if p["pick_no"] >= pick_no:
            continue
        slot = p.get("slot", p.get("draft_slot"))
        if slot is None:
            raise ReplayHarnessError(f"pick {p['pick_no']} has neither 'slot' nor 'draft_slot' -- can't freeze it.")
        picks_before.append({"pick_no": p["pick_no"], "draft_slot": slot, "player_id": p["player_id"]})
    picks_before.sort(key=lambda p: p["pick_no"])

    payload = {
        "meta": {
            "target_pick_no": pick_no,
            "my_slot": my_slot,
            "num_teams": num_teams,
            "roster_positions": list(roster_positions or ROSTER_POSITIONS),
            "source": source,
            "num_picks_frozen": len(picks_before),
        },
        "picks_before": picks_before,
    }

    out_path = Path(out_dir) / f"{name}.json"
    if out_path.exists():
        raise ReplayHarnessError(
            f"Trajectory '{name}' already exists at {out_path} -- trajectories are immutable by "
            "convention. Pick a new name to freeze a different cutoff/draft."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return str(out_path)


def load_frozen_trajectory(path: str) -> tuple[DraftState, dict[str, Any]]:
    """
    Rebuilds the exact DraftState a frozen trajectory represents (via the
    EXISTING `DraftState.from_sleeper_picks` -- no new state-construction
    logic needed), and sanity-checks it lands exactly where the freeze
    claimed it would: replaying `picks_before` must produce
    `current_pick_no == meta.target_pick_no`, and that pick must actually
    be `my_slot`'s turn (recommend() requires this and would otherwise
    fail with a less specific error deeper in the call stack). Returns
    (state, meta).
    """
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    meta = payload["meta"]
    state = DraftState.from_sleeper_picks(
        my_slot=meta["my_slot"],
        sleeper_picks=payload["picks_before"],
        num_teams=meta["num_teams"],
        roster_positions=meta["roster_positions"],
    )
    if state.current_pick_no != meta["target_pick_no"]:
        raise ReplayHarnessError(
            f"Frozen trajectory '{path}' is inconsistent: replaying {len(payload['picks_before'])} picks "
            f"lands at pick {state.current_pick_no}, but meta.target_pick_no={meta['target_pick_no']} -- "
            "the pick log this was frozen from may have gaps or duplicate pick_nos."
        )
    if not state.is_my_turn:
        raise ReplayHarnessError(
            f"Frozen trajectory '{path}''s target_pick_no={meta['target_pick_no']} is not my_slot="
            f"{meta['my_slot']}'s turn (on the clock: slot {state.slot_on_the_clock_now}) -- pick a "
            "pick_no that's actually a 'my turn' decision point."
        )
    return state, meta


def _next_turn_pick_no(state: DraftState) -> int:
    """
    Same algorithm as app/services/mcts.py's private `_next_turn_pick_no`
    (deliberately reimplemented here rather than importing a `_`-prefixed
    name across modules -- see that function's own docstring for why this
    is a pure function of pick_no/num_teams, not state.picks). Kept in
    sync by inspection; if mcts.py's version ever changes, update here too.
    """
    pick_no = state.current_pick_no + 1
    while slot_on_the_clock(pick_no, state.num_teams) != state.my_slot:
        pick_no += 1
    return pick_no


# ---------------------------------------------------------------------
# Task 3: the replay itself
# ---------------------------------------------------------------------


def replay_decision(
    trajectory_path: str,
    snapshot_path: str,
    seed: Optional[int] = 1,
    top_n: int = mcts_service.CANDIDATE_BREADTH,
    **recommend_kwargs: Any,
) -> dict[str, Any]:
    """
    Loads a frozen trajectory + a pinned data snapshot and runs
    `app.services.mcts.recommend()` -- whichever CODE VERSION that name
    resolves to is entirely determined by the caller's sys.path (see
    scripts/replay_run.py's REPLAY_APP_ROOT handling), not by anything in
    this function. `top_n=CANDIDATE_BREADTH` matches production
    (draft_score_engine.py) and the Chunk-37-corrected mock_draft.py, NOT
    the old top_n=1 harness bug -- both tie-break mechanisms
    (adaptive resolution, ADP-margin) need the full top-N list to have
    anything to operate on.

    Adds `would_start_now` per candidate (using vbd.py's EXISTING
    `allocate_roster_starters` against the roster as of this pick, same
    as the Chunk 32/36/38 report methodology) since recommend() itself
    doesn't compute or return that.
    """
    state, meta = load_frozen_trajectory(trajectory_path)
    players_by_id = load_players_by_id(snapshot_path)

    result = mcts_service.recommend(state, players_by_id, top_n=top_n, seed=seed, **recommend_kwargs)

    my_roster_ids = state.roster_player_ids()
    my_roster_players = [players_by_id[pid] for pid in my_roster_ids if pid in players_by_id]
    for r in result["recommendations"]:
        candidate = players_by_id.get(r["player_id"])
        if candidate is None:
            r["would_start_now"] = None
            continue
        started_ids = vbd_service.allocate_roster_starters(my_roster_players + [candidate])
        r["would_start_now"] = r["player_id"] in started_ids

    return {
        "trajectory_path": trajectory_path,
        "trajectory_meta": meta,
        "snapshot_path": snapshot_path,
        "seed": seed,
        "top_n": top_n,
        "pick_no": state.current_pick_no,
        "next_turn_pick_no": _next_turn_pick_no(state),
        "my_roster_before": my_roster_ids,
        "recommend_result": result,
    }
