"""
Chunk 68 -- draft-day operational resilience.

Covers the two failure modes that would be real problems live and
invisible until they happen:

  1. A browser tab drops its websocket mid-draft (wifi blip, laptop
     sleep, refresh) and reconnects -- does it resync to current state?
  2. The FastAPI process itself restarts mid-draft -- can it recover the
     session from Sleeper's pick feed rather than losing it with the
     process?

Plus the catch-up behavior (a mid-draft (re)start must not replay a stale
MCTS compute for every past turn) and finished-draft handling.

All Sleeper access + the expensive engine are stubbed -- no network, no
real draft touched, no real MCTS.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.config import NUM_DRAFT_ROUNDS
from app.services import draft_live

KIDDOS_DRAFT_ID = "1389755334746202113"  # used ONLY to assert we never persist/resume a real-league descriptor
MOCK_ID = "888899990000111122"


@pytest.fixture(autouse=True)
def _fast_projections(monkeypatch):
    async def _tiny():
        return {"players": [
            {"player_id": str(i), "name": f"P{i}", "position": ["QB", "RB", "WR", "TE"][i % 4],
             "team": "AAA", "projected_points": 200.0 - i} for i in range(1, 260)
        ]}
    monkeypatch.setattr(draft_live, "build_baseline_projections", _tiny)


@pytest.fixture(autouse=True)
def _fast_engine(monkeypatch):
    """Count expensive-tier fires without running real MCTS."""
    calls: list[int] = []

    def _compute(state, players_by_id, **kw):
        calls.append(state.current_pick_no)
        return {"draft_score": {"player_id": "1", "name": "P1", "position": "QB", "team": "AAA",
                                "score": 1.0, "score_stderr": 0.0, "vbd_score": 1.0},
                "explanation": {}, "alternatives_considered": []}

    monkeypatch.setattr(draft_live.draft_score_engine, "compute_draft_score", _compute)
    return calls


@pytest.fixture(autouse=True)
def _isolated_session_file(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_live, "_LIVE_SESSION_PATH", str(tmp_path / "live_session.json"))
    return Path(str(tmp_path / "live_session.json"))


@pytest.fixture(autouse=True)
def _fresh_manager(monkeypatch):
    """Every test gets its own manager singleton; always torn down.
    Poll interval shrunk so a 0.1s test sleep spans several poll cycles."""
    monkeypatch.setattr(draft_live, "_manager", None)
    monkeypatch.setattr(draft_live, "LIVE_POLL_INTERVAL_SECONDS", 0.02)
    yield
    mgr = draft_live.get_manager()
    if mgr._driver_task is not None:
        mgr._driver_task.cancel()
        mgr._driver_task = None


class _RecordingWS:
    """Stand-in for a browser websocket -- captures every message it's sent."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def snapshots(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("type") == "snapshot"]


def _fake_picks(n: int, num_teams: int = 10) -> list[dict[str, Any]]:
    """n snake-draft picks, players '1'.. so they exist in the stub projections."""
    out = []
    for pick_no in range(1, n + 1):
        rnd = (pick_no - 1) // num_teams
        idx = (pick_no - 1) % num_teams
        slot = (num_teams - idx) if rnd % 2 else (idx + 1)
        out.append({"pick_no": pick_no, "draft_slot": slot, "player_id": str(pick_no)})
    return out


# --------------------------------------------------------------------------
# 1. websocket reconnect resync
# --------------------------------------------------------------------------

def test_reconnect_snapshot_reflects_picks_missed_while_disconnected(monkeypatch):
    """A client that drops for several picks and reconnects must get a
    snapshot with current state + a coherent recent-picks feed, not stale
    data or a single orphan row."""
    feed = {"picks": []}
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(side_effect=lambda _id: list(feed["picks"])))

    async def scenario():
        mgr = draft_live.get_manager()
        # my_slot 3 in a 10-team snake -> my turns at pick 3, 18, 23, ...
        await mgr.start_live(my_slot=3, num_teams=10, watch_draft_id=MOCK_ID)

        ws1 = _RecordingWS()
        await mgr.register(ws1)
        first = ws1.snapshots()[-1]

        # 6 picks happen while ws1 is "connected"
        feed["picks"] = _fake_picks(6)
        await asyncio.sleep(0.15)
        mgr.unregister(ws1)  # <-- disconnect
        during = mgr.snapshot()["current_pick_no"]

        # 10 more picks happen while nobody is listening
        feed["picks"] = _fake_picks(16)
        await asyncio.sleep(0.15)

        ws2 = _RecordingWS()
        await mgr.register(ws2)  # <-- reconnect
        resync = ws2.snapshots()[-1]
        await mgr.stop()
        return first, during, resync

    first, during, resync = asyncio.run(scenario())

    assert first["current_pick_no"] == 1  # nothing had happened yet
    assert during == 7  # 6 picks seen before the disconnect
    assert resync["current_pick_no"] == 17  # 16 picks ingested, now on pick 17
    # the reconnect feed is coherent: the buffer, newest picks, capped
    assert len(resync["recent_picks"]) == draft_live.RECENT_PICKS_BUFFER
    assert [p["pick_no"] for p in resync["recent_picks"]] == list(range(2, 17))
    assert resync["mode"] == "sleeper_mock"


def test_status_endpoint_and_ws_register_agree_after_reconnect(monkeypatch):
    """The /api/live/status resume path and a fresh ws register must return
    the same picture (the frontend uses both on a refresh)."""
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(return_value=_fake_picks(12)))

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=5, num_teams=10, watch_draft_id=MOCK_ID)
        await asyncio.sleep(0.1)
        status_snap = mgr.snapshot()  # what GET /api/live/status returns
        ws = _RecordingWS()
        await mgr.register(ws)
        register_snap = ws.snapshots()[-1]
        await mgr.stop()
        return status_snap, register_snap

    status_snap, register_snap = asyncio.run(scenario())
    for key in ("current_pick_no", "current_round", "is_my_turn", "picks_until_your_turn", "mode"):
        assert status_snap[key] == register_snap[key], key
    assert status_snap["current_pick_no"] == 13


# --------------------------------------------------------------------------
# 2. server-restart session persistence + resume
# --------------------------------------------------------------------------

def test_session_file_roundtrip_and_bad_input(_isolated_session_file):
    assert draft_live._load_live_session() is None  # nothing yet

    draft_live._save_live_session({"mode": "live", "my_slot": 4, "num_teams": 10, "watch_draft_id": None})
    loaded = draft_live._load_live_session()
    assert loaded["mode"] == "live" and loaded["my_slot"] == 4
    assert "saved_at" in loaded

    _isolated_session_file.write_text("not json", encoding="utf-8")
    assert draft_live._load_live_session() is None  # malformed -> ignored, not raised

    _isolated_session_file.write_text('{"mode": "live"}', encoding="utf-8")  # missing my_slot
    assert draft_live._load_live_session() is None

    draft_live._clear_live_session()
    assert draft_live._load_live_session() is None
    draft_live._clear_live_session()  # idempotent, no error


def test_start_live_persists_and_stop_clears(monkeypatch, _isolated_session_file):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=7, num_teams=10, watch_draft_id=MOCK_ID, session_warnings=["heads up"])
        persisted = json.loads(_isolated_session_file.read_text())
        await mgr.stop()
        cleared = _isolated_session_file.exists()
        return persisted, cleared

    persisted, cleared = asyncio.run(scenario())
    assert persisted["mode"] == "sleeper_mock"
    assert persisted["my_slot"] == 7
    assert persisted["watch_draft_id"] == MOCK_ID
    assert persisted["session_warnings"] == ["heads up"]
    assert cleared is False  # stop() removed it


def test_start_mock_clears_any_live_session(monkeypatch, _isolated_session_file):
    draft_live._save_live_session({"mode": "live", "my_slot": 1, "num_teams": 10, "watch_draft_id": None})

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_mock(my_slot=1, num_teams=10, seed=1, delay_seconds=0, mcts_iterations=1)
        await asyncio.sleep(0.05)
        await mgr.stop()

    asyncio.run(scenario())
    assert not _isolated_session_file.exists()  # a mock is not a resumable live session


def test_resume_rebuilds_state_from_sleeper_after_restart(monkeypatch, _isolated_session_file):
    """The core recovery: process died mid-draft, a descriptor is on disk,
    startup re-arms the poller and draft_state rebuilds from the pick feed."""
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(return_value=_fake_picks(40)))
    draft_live._save_live_session(
        {"mode": "live", "my_slot": 2, "num_teams": 10, "watch_draft_id": None, "session_warnings": []}
    )

    async def scenario():
        # fresh process: brand-new manager, nothing in memory
        assert draft_live.get_manager().draft_state is None
        resumed = await draft_live.resume_live_session_if_any()
        await asyncio.sleep(0.1)
        mgr = draft_live.get_manager()
        snap = mgr.snapshot()
        await mgr.stop()
        return resumed, snap

    resumed, snap = asyncio.run(scenario())
    assert resumed is True
    assert snap["mode"] == "live"
    assert snap["my_slot"] == 2
    assert snap["current_pick_no"] == 41  # all 40 picks replayed from Sleeper
    assert snap["status"] == "running"


def test_resume_is_a_noop_with_no_session_file(_isolated_session_file):
    async def scenario():
        return await draft_live.resume_live_session_if_any()

    assert asyncio.run(scenario()) is False
    assert draft_live.get_manager().draft_state is None


def test_resume_discards_a_descriptor_with_a_bad_mode(_isolated_session_file):
    draft_live._save_live_session({"mode": "mock", "my_slot": 3, "num_teams": 10, "watch_draft_id": None})

    async def scenario():
        return await draft_live.resume_live_session_if_any()

    assert asyncio.run(scenario()) is False
    assert not _isolated_session_file.exists()  # self-healed


# --------------------------------------------------------------------------
# 3. catch-up: a mid-draft (re)start must not replay a stale compute per turn
# --------------------------------------------------------------------------

def test_catch_up_replay_fires_expensive_tier_at_most_once(monkeypatch, _fast_engine):
    """40 picks already made when the poller starts; my_slot=2 has had ~4
    turns already. Catching up must not run compute_draft_score for each."""
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(return_value=_fake_picks(40)))

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=2, num_teams=10)  # plain live path
        await asyncio.sleep(0.15)
        snap = mgr.snapshot()
        await mgr.stop()
        return snap

    snap = asyncio.run(scenario())
    assert snap["current_pick_no"] == 41
    # pick 41 (round 5, snake) is slot 2's? -> irrelevant; the point is the
    # catch-up replay of picks 1-40 fired AT MOST the single post-catch-up check.
    assert len(_fast_engine) <= 1, f"expensive tier fired {len(_fast_engine)}x during catch-up: {_fast_engine}"


# --------------------------------------------------------------------------
# 4. finished draft: stop polling, clear the session, announce completion
# --------------------------------------------------------------------------

def test_completed_draft_stops_polling_and_clears_session(monkeypatch, _isolated_session_file):
    total = 10 * NUM_DRAFT_ROUNDS
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(return_value=_fake_picks(total)))

    async def scenario():
        mgr = draft_live.get_manager()
        ws = _RecordingWS()
        await mgr.register(ws)
        await mgr.start_live(my_slot=4, num_teams=10, watch_draft_id=MOCK_ID)
        await asyncio.sleep(0.2)
        done = mgr._driver_task is None or mgr._driver_task.done()
        snap = mgr.snapshot()
        got_complete = any(m.get("type") == "draft_complete" for m in ws.messages)
        await mgr.stop()
        return done, snap, got_complete

    done, snap, got_complete = asyncio.run(scenario())
    assert snap["status"] == "complete"
    assert got_complete is True
    assert not _isolated_session_file.exists()
    assert done is True  # the driver returned, not left spinning on a finished draft


def test_real_league_draft_id_never_lands_in_a_persisted_descriptor(monkeypatch, _isolated_session_file):
    """A real-league draft_id can only ever reach start_live via the plain
    LIVE path (watch_draft_id stays None). The persisted descriptor for the
    plain path must not carry it."""
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=3, num_teams=10)  # plain live, watch_draft_id=None
        d = json.loads(_isolated_session_file.read_text())
        await mgr.stop()
        return d

    d = asyncio.run(scenario())
    assert d["watch_draft_id"] is None
    assert KIDDOS_DRAFT_ID not in json.dumps(d)
