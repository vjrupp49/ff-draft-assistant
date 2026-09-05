"""
"Sleeper Mock" watch mode -- point the existing LIVE driver at a separate
Sleeper mock draft the user started themselves (draft_id supplied), so
they can click picks on Sleeper and get live recommendations here.

Covers: the read-only pre-flight (`inspect_sleeper_draft`), the router
wiring (`/api/live/inspect-draft`, `/api/live/start-live` with
`watch_draft_id`), and -- the important one -- a NEGATIVE CONTROL that the
plain live path (no `watch_draft_id`) still polls SLEEPER_DRAFT_ID exactly
as before.

All Sleeper access is monkeypatched -- no network, no real draft touched.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import SLEEPER_DRAFT_ID
from app.main import app
from app.services import draft_live
from app.services.draft_live import inspect_sleeper_draft
from app.services.roster_identity import MY_SLEEPER_USER_ID

client = TestClient(app)

KIDDOS_DRAFT_ID = "1389755334746202113"
BRADLEY_DRAFT_ID = "1389749759891214337"
MOCK_ID = "111122223333444455"


def _superflex_draft(status: str = "drafting", **overrides: Any) -> dict[str, Any]:
    d = {
        "draft_id": MOCK_ID,
        "status": status,
        "type": "snake",
        "draft_order": {MY_SLEEPER_USER_ID: 4, "someone_else": 1},
        "settings": {"teams": 10, "rounds": 15, "slots_qb": 1, "slots_rb": 2,
                     "slots_wr": 2, "slots_flex": 3, "slots_super_flex": 1, "slots_bn": 6},
        "metadata": {"scoring_type": "2qb"},
    }
    d.update(overrides)
    return d


@pytest.fixture(autouse=True)
def _fast_projections(monkeypatch):
    """start_live() builds projections -- stub it so plumbing tests don't pay for it."""
    async def _tiny():
        return {"players": [{"player_id": "1", "name": "X", "position": "RB", "team": "A",
                             "projected_points": 100.0}]}
    monkeypatch.setattr(draft_live, "build_baseline_projections", _tiny)


@pytest.fixture(autouse=True)
def _isolate_live_session(monkeypatch, tmp_path):
    """CHUNK 68: start_live() now persists a session descriptor -- keep it out of the repo's data/."""
    monkeypatch.setattr(draft_live, "_LIVE_SESSION_PATH", str(tmp_path / "live_session.json"))


@pytest.fixture(autouse=True)
def _reset_manager():
    yield
    mgr = draft_live.get_manager()
    if mgr._driver_task is not None:
        mgr._driver_task.cancel()
        mgr._driver_task = None
    mgr.status = "idle"
    mgr.mode = None
    mgr.watched_draft_id = None
    mgr.session_warnings = []


# --- inspect_sleeper_draft -------------------------------------------------

def test_inspect_rejects_the_real_league_drafts():
    for real in (KIDDOS_DRAFT_ID, BRADLEY_DRAFT_ID):
        info = asyncio.run(inspect_sleeper_draft(real))
        assert info["ok"] is False
        assert "Live Draft" in info["error"]


def test_inspect_ok_superflex_mock_resolves_slot_from_draft_order(monkeypatch):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft",
                        AsyncMock(return_value=_superflex_draft()))
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                        AsyncMock(return_value=[{"pick_no": 1}, {"pick_no": 2}]))
    info = asyncio.run(inspect_sleeper_draft(MOCK_ID))
    assert info["ok"] is True
    assert info["my_slot"] == 4 and info["my_slot_source"] == "draft_order"
    assert info["num_teams"] == 10
    assert info["num_picks_so_far"] == 2
    assert info["format_warnings"] == []


def test_inspect_warns_on_non_superflex_and_uses_real_team_count(monkeypatch):
    weird = _superflex_draft(
        settings={"teams": 12, "rounds": 16, "slots_qb": 1, "slots_rb": 2, "slots_wr": 3,
                  "slots_te": 1, "slots_flex": 1, "slots_super_flex": 0, "slots_bn": 6},
        metadata={"scoring_type": "ppr"},
    )
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft", AsyncMock(return_value=weird))
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))
    info = asyncio.run(inspect_sleeper_draft(MOCK_ID))
    assert info["ok"] is True  # still watchable
    assert info["num_teams"] == 12  # snake math must use the REAL count
    joined = " ".join(info["format_warnings"]).lower()
    assert "12-team" in joined and "super_flex" in joined and "te slot" in joined


def test_inspect_blocks_a_finished_draft(monkeypatch):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft",
                        AsyncMock(return_value=_superflex_draft(status="complete")))
    info = asyncio.run(inspect_sleeper_draft(MOCK_ID))
    assert info["ok"] is False and "finished" in info["error"]


def test_inspect_needs_manual_slot_when_user_not_in_draft_order(monkeypatch):
    d = _superflex_draft(draft_order={"other": 1})
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft", AsyncMock(return_value=d))
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))
    info = asyncio.run(inspect_sleeper_draft(MOCK_ID))
    assert info["ok"] is False and "manually" in info["error"]
    # ...but an explicit override resolves it
    info2 = asyncio.run(inspect_sleeper_draft(MOCK_ID, my_slot_override=6))
    assert info2["ok"] is True and info2["my_slot"] == 6 and info2["my_slot_source"] == "you"


# --- driver: which draft_id gets polled ---------------------------------------

def test_start_live_no_watch_id_polls_the_real_draft_id(monkeypatch):
    """NEGATIVE CONTROL: the plain live path is unchanged -- polls SLEEPER_DRAFT_ID."""
    seen = AsyncMock(return_value=[])
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", seen)

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=3)
        await asyncio.sleep(0.05)
        snap = mgr.snapshot()
        await mgr.stop()
        return snap

    snap = asyncio.run(scenario())
    assert seen.await_count >= 1
    assert seen.await_args_list[0].args[0] == SLEEPER_DRAFT_ID
    assert snap["mode"] == "live"
    assert snap["watched_draft_id"] is None


def test_expensive_tier_fires_only_on_your_real_turn_not_provisionally(monkeypatch):
    """
    CHUNK 66: the tiered manager used to run compute_draft_score 3x per
    turn (picks_until 2, 1, 0 -- two provisional, one real). Now it fires
    ONLY when it's actually our turn, against the real state, and the
    payload carries no `is_provisional`. my_slot=4 in a 10-team snake ->
    first turn is pick 4 (picks 1-3 are opponents).
    """
    fired_at: list[int] = []

    def fake_compute(state, players_by_id, **kw):
        fired_at.append(state.current_pick_no)
        return {"draft_score": {"player_id": "999", "name": "Pick", "position": "RB",
                                "team": "A", "score": 1.0, "score_stderr": 0.0, "vbd_score": 1.0},
                "explanation": {}, "alternatives_considered": []}

    monkeypatch.setattr(draft_live.draft_score_engine, "compute_draft_score", fake_compute)

    def run(num_opponent_picks_available):
        fired_at.clear()
        picks = [{"pick_no": i, "player_id": str(100 + i)}
                 for i in range(1, num_opponent_picks_available + 1)]
        monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks",
                            AsyncMock(return_value=picks))
        mgr = draft_live.get_manager()
        broadcasts: list[dict[str, Any]] = []
        orig = mgr.broadcast
        async def capture(msg):
            broadcasts.append(msg)
            await orig(msg)
        monkeypatch.setattr(mgr, "broadcast", capture)

        async def scenario():
            await mgr.start_live(my_slot=4, watch_draft_id=MOCK_ID)
            await asyncio.sleep(0.1)
            await mgr.stop()

        asyncio.run(scenario())
        return list(fired_at), broadcasts

    # only picks 1-2 in yet -> current pick is 3, an opponent -> no compute at all
    fires, _ = run(2)
    assert fires == [], f"expensive tier fired before my turn: {fires}"

    # pick 3 lands -> current_pick_no advances to 4 (my slot) -> exactly one real fire
    fires, broadcasts = run(3)
    assert fires == [4], f"expected exactly one fire on pick 4, got {fires}"
    scores = [m for m in broadcasts if m.get("type") == "draft_score"]
    assert len(scores) == 1
    assert "is_provisional" not in scores[0]
    assert scores[0]["is_my_turn"] is True


def test_start_live_with_watch_id_polls_that_draft_id(monkeypatch):
    seen = AsyncMock(return_value=[])
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", seen)

    async def scenario():
        mgr = draft_live.get_manager()
        await mgr.start_live(my_slot=4, watch_draft_id=MOCK_ID, session_warnings=["heads up"])
        await asyncio.sleep(0.05)
        snap = mgr.snapshot()
        await mgr.stop()
        return snap

    snap = asyncio.run(scenario())
    assert seen.await_args_list[0].args[0] == MOCK_ID
    assert snap["mode"] == "sleeper_mock"
    assert snap["watched_draft_id"] == MOCK_ID
    assert snap["session_warnings"] == ["heads up"]


# --- router wiring ----------------------------------------------------------

def test_inspect_draft_endpoint(monkeypatch):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft",
                        AsyncMock(return_value=_superflex_draft()))
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))
    r = client.get(f"/api/live/inspect-draft?draft_id={MOCK_ID}")
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["my_slot"] == 4


def test_start_live_endpoint_rejects_real_league_draft_id():
    r = client.post("/api/live/start-live", json={"my_slot": 3, "watch_draft_id": KIDDOS_DRAFT_ID})
    assert r.status_code == 400
    assert "Live Draft" in r.json()["detail"]


def test_start_live_endpoint_watch_mode_happy_path(monkeypatch):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft",
                        AsyncMock(return_value=_superflex_draft()))
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))
    # the frontend posts the slot it got back from /inspect-draft (4); it is honoured
    r = client.post("/api/live/start-live", json={"my_slot": 4, "watch_draft_id": MOCK_ID})
    assert r.status_code == 200
    snap = r.json()
    assert snap["mode"] == "sleeper_mock" and snap["watched_draft_id"] == MOCK_ID
    assert snap["my_slot"] == 4
    assert snap["num_teams"] == 10


def test_plain_live_endpoint_still_works(monkeypatch):
    monkeypatch.setattr(draft_live.sleeper_client, "get_draft_picks", AsyncMock(return_value=[]))
    r = client.post("/api/live/start-live", json={"my_slot": 3})
    assert r.status_code == 200
    snap = r.json()
    assert snap["mode"] == "live" and snap["watched_draft_id"] is None
