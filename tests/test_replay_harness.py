"""
Chunk 40 -- unit tests for replay_lib/harness.py's pure I/O logic (trajectory
freeze/load roundtrip, snapshot load, immutability-by-convention refusal to
overwrite). Deliberately does NOT include a test that calls
mcts.recommend() through the harness -- that would make this file as slow
as the MCTS-heavy tests it's meant to complement, and the harness's actual
replay behavior is proven empirically in the Chunk 40 report (determinism
proof, Chunk 33 reproduction, Chunk 38 before/after) rather than as a
permanent regression test, matching this chunk's infrastructure-only scope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from replay_lib import harness


# ---------------------------------------------------------------------
# Trajectory freeze/load roundtrip
# ---------------------------------------------------------------------


def _sample_picks() -> list[dict]:
    # 3-team, 2-round snake draft: pick order 1,2,3 | 3,2,1
    return [
        {"pick_no": 1, "slot": 1, "player_id": "A"},
        {"pick_no": 2, "slot": 2, "player_id": "B"},
        {"pick_no": 3, "slot": 3, "player_id": "C"},
        {"pick_no": 4, "slot": 3, "player_id": "D"},
        {"pick_no": 5, "slot": 2, "player_id": "E"},
        {"pick_no": 6, "slot": 1, "player_id": "F"},
    ]


def test_freeze_and_load_roundtrip_lands_on_the_right_pick(tmp_path: Path) -> None:
    traj_dir = tmp_path / "trajectories"
    path = harness.freeze_trajectory(
        _sample_picks(), pick_no=5, my_slot=2, name="sample", out_dir=str(traj_dir),
        num_teams=3, roster_positions=["QB", "RB"], source="unit test",
    )
    assert Path(path).exists()

    state, meta = harness.load_frozen_trajectory(path)
    assert meta["target_pick_no"] == 5
    assert meta["num_picks_frozen"] == 4  # picks 1-4 only, pick 5 itself excluded
    assert state.current_pick_no == 5
    assert state.is_my_turn  # pick 5 is slot 2's turn, matches my_slot=2
    assert state.roster_player_ids() == ["B"]  # slot 2's only pick so far


def test_freeze_accepts_draft_slot_key_same_as_slot_key(tmp_path: Path) -> None:
    """Sleeper's real pick format (and the existing chunk22 fixture) use
    'draft_slot', not mock_draft.py's 'slot' -- both must work unchanged."""
    picks_draft_slot_key = [{"pick_no": p["pick_no"], "draft_slot": p["slot"], "player_id": p["player_id"]} for p in _sample_picks()]
    path = harness.freeze_trajectory(
        picks_draft_slot_key, pick_no=5, my_slot=2, name="sample2", out_dir=str(tmp_path / "t2"), num_teams=3,
    )
    state, _meta = harness.load_frozen_trajectory(path)
    assert state.current_pick_no == 5
    assert state.roster_player_ids() == ["B"]


def test_load_rejects_a_pick_no_that_is_not_my_turn(tmp_path: Path) -> None:
    """pick_no=4 is slot 3's turn (round 2 snake reversal) -- freezing it
    with my_slot=2 must fail loudly, not silently hand back the wrong turn."""
    path = harness.freeze_trajectory(
        _sample_picks(), pick_no=4, my_slot=2, name="wrong_turn", out_dir=str(tmp_path / "t3"), num_teams=3,
    )
    with pytest.raises(harness.ReplayHarnessError, match="not my_slot"):
        harness.load_frozen_trajectory(path)


def test_freeze_refuses_to_overwrite_an_existing_name(tmp_path: Path) -> None:
    out_dir = str(tmp_path / "t4")
    harness.freeze_trajectory(_sample_picks(), pick_no=5, my_slot=2, name="dup", out_dir=out_dir, num_teams=3)
    with pytest.raises(harness.ReplayHarnessError, match="already exists"):
        harness.freeze_trajectory(_sample_picks(), pick_no=5, my_slot=2, name="dup", out_dir=out_dir, num_teams=3)


def test_freeze_rejects_a_pick_missing_both_slot_keys(tmp_path: Path) -> None:
    bad_picks = [{"pick_no": 1, "player_id": "A"}]
    with pytest.raises(harness.ReplayHarnessError, match="neither 'slot' nor 'draft_slot'"):
        harness.freeze_trajectory(bad_picks, pick_no=2, my_slot=1, name="bad", out_dir=str(tmp_path / "t5"), num_teams=3)


# ---------------------------------------------------------------------
# Data snapshot load + immutability
# ---------------------------------------------------------------------


def test_load_players_by_id_from_snapshot(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snap.json"
    payload = {
        "generated_at": "2026-01-01T00:00:00Z",
        "players": [
            {"player_id": "1", "name": "Player One", "position": "QB", "projected_points": 300.0},
            {"player_id": "2", "name": "Player Two", "position": "WR", "projected_points": 200.0},
        ],
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    players_by_id = harness.load_players_by_id(str(snapshot_path))
    assert set(players_by_id) == {"1", "2"}
    assert players_by_id["1"]["position"] == "QB"


# No dedicated test for `capture_data_snapshot`'s happy path: it's a thin
# async wrapper that (a) calls the ALREADY-tested build_baseline_projections
# pipeline unchanged and (b) writes+refuses-to-overwrite a file -- the
# overwrite-refusal half (its only genuinely new logic) is exercised below
# with a fake pipeline, without needing a real (slow, network-dependent)
# projections build.
def test_capture_data_snapshot_refuses_to_overwrite(tmp_path: Path) -> None:
    import asyncio
    from unittest.mock import patch

    out_dir = tmp_path / "snapshots"
    out_dir.mkdir()
    (out_dir / "existing.json").write_text("{}", encoding="utf-8")

    async def _fake_build(force_refresh: bool = False):
        return {"players": []}

    with patch("replay_lib.harness.build_baseline_projections", _fake_build):
        with pytest.raises(harness.ReplayHarnessError, match="already exists"):
            asyncio.run(harness.capture_data_snapshot("existing", out_dir=str(out_dir)))
