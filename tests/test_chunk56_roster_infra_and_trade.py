"""
Chunk 56 -- regression coverage for:
  1. app/services/roster_identity.py ("my roster_id" resolution + cache),
     confirmed against BOTH real leagues via live, read-only Sleeper calls.
  2. app/routers/lineup.py's Chunk 56 update (use_live_roster=true with no
     roster_id now resolves MY roster instead of requiring one).
  3. app/routers/rosters.py (the roster browser) -- validated against a
     MONKEYPATCHED synthetic 10-team league built from Chunk 41's existing
     full-draft picklog (data/replay_trajectories/
     chunk41_slot7_seed1_full_picklog.json, ALL 10 slots' real picks, not
     just one), since both real leagues are pre_draft and every real
     roster is empty today. Also checked directly against both real
     leagues for graceful empty-roster handling.
  4. app/routers/trade.py (Trade Suggester skeleton) -- confirms the
     comparison is the simple raw VBD/points sum specified, not anything
     more elaborate.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.leagues import FORMER_BRADLEY_BUMS, KIDDOS
from app.main import app
from app.services import roster_identity

client = TestClient(app)

REPO_ROOT = Path(__file__).parent.parent
_PICKLOG_PATH = REPO_ROOT / "data" / "replay_trajectories" / "chunk41_slot7_seed1_full_picklog.json"


def _synthetic_10_team_league(my_slot: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Builds Sleeper-shaped rosters/users for all 10 draft slots from the real Chunk 41 picklog."""
    picklog = json.loads(_PICKLOG_PATH.read_text())
    by_slot: dict[int, list[str]] = {}
    for p in picklog:
        by_slot.setdefault(p["slot"], []).append(p["player_id"])
    assert len(by_slot) == 10

    my_id = roster_identity.MY_SLEEPER_USER_ID
    rosters = [
        {"roster_id": slot, "owner_id": (my_id if slot == my_slot else f"opp_{slot}"), "players": ids}
        for slot, ids in by_slot.items()
    ]
    users = [
        {
            "user_id": (my_id if slot == my_slot else f"opp_{slot}"),
            "display_name": ("vjrupp4949" if slot == my_slot else f"Opponent{slot}"),
            "metadata": {"team_name": ("My Synthetic Team" if slot == my_slot else f"Opp Team {slot}")},
        }
        for slot in by_slot
    ]
    return rosters, users


@pytest.fixture(autouse=True)
def clear_roster_id_cache():
    """Every test starts with a cold my-roster-id cache -- avoids leaking a synthetic/monkeypatched
    resolution into a later real-league test or vice versa."""
    roster_identity._my_roster_id_cache.clear()
    yield
    roster_identity._my_roster_id_cache.clear()


# ---------------------------------------------------------------------------
# 1. roster_identity -- live, read-only, against BOTH real leagues
# ---------------------------------------------------------------------------

def test_resolve_my_roster_id_both_real_leagues():
    # Plain sync test wrapping asyncio.run() -- this suite deliberately
    # doesn't depend on pytest-asyncio, see tests/conftest.py's docstring.
    async def _run():
        kiddos_id = await roster_identity.resolve_my_roster_id(KIDDOS, force_refresh=True)
        fbb_id = await roster_identity.resolve_my_roster_id(FORMER_BRADLEY_BUMS, force_refresh=True)
        return kiddos_id, fbb_id

    kiddos_id, fbb_id = asyncio.run(_run())
    # Confirmed directly (Chunk 56) via a live API check before writing this test.
    assert kiddos_id == 7
    assert fbb_id == 8


def test_resolve_my_roster_id_caches_without_refetching():
    async def _run():
        first = await roster_identity.resolve_my_roster_id(KIDDOS, force_refresh=True)
        with patch(
            "app.services.roster_identity.sleeper_client.get_rosters",
            new=AsyncMock(side_effect=AssertionError("should not refetch")),
        ):
            second = await roster_identity.resolve_my_roster_id(KIDDOS)
        return first, second

    first, second = asyncio.run(_run())
    assert second == first


# ---------------------------------------------------------------------------
# 2. lineup.py Chunk 56 update -- use_live_roster with no roster_id
# ---------------------------------------------------------------------------

def test_lineup_live_roster_omitted_roster_id_resolves_mine_both_leagues():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.post("/api/lineup/optimize", json={"use_live_roster": True, "league_key": league_key})
        assert resp.status_code == 200
        # both real leagues are pre_draft -- graceful empty, not the old 400
        assert resp.json()["roster_size"] == 0


# ---------------------------------------------------------------------------
# 3. Roster browser -- synthetic 10-team league (monkeypatched Sleeper)
# ---------------------------------------------------------------------------

def test_roster_browser_synthetic_league_resolves_mine_and_all_opponents():
    rosters, users = _synthetic_10_team_league(my_slot=3)
    with patch("app.services.sleeper.sleeper_client.get_rosters", new=AsyncMock(return_value=rosters)), \
         patch("app.services.sleeper.sleeper_client.get_users", new=AsyncMock(return_value=users)):
        resp = client.get("/api/rosters", params={"league_key": "kiddos"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["my_roster_id"] == 3
    assert body["count"] == 10

    mine = [r for r in body["rosters"] if r["is_mine"]]
    assert len(mine) == 1
    assert mine[0]["roster_id"] == 3
    assert mine[0]["team_name"] == "My Synthetic Team"
    assert mine[0]["player_count"] == 15
    assert all(p["name"] for p in mine[0]["players"])  # every synthetic player_id resolved to a real name

    others = [r for r in body["rosters"] if not r["is_mine"]]
    assert len(others) == 9
    assert all(r["player_count"] == 15 for r in others)
    # mine-first ordering
    assert body["rosters"][0]["is_mine"] is True


def test_roster_browser_both_real_leagues_graceful_empty():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.get("/api/rosters", params={"league_key": league_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 10
        mine = [r for r in body["rosters"] if r["is_mine"]]
        assert len(mine) == 1
        assert mine[0]["player_count"] == 0
        assert mine[0]["players"] == []


def test_roster_browser_bogus_league_key_404():
    resp = client.get("/api/rosters", params={"league_key": "bogus"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Trade Suggester skeleton -- simple raw value comparison only
# ---------------------------------------------------------------------------

def test_trade_compare_is_simple_additive_vbd_sum(players_by_id: dict[str, Any]):
    from app.services.vbd import calculate_vbd

    ranked = calculate_vbd(list(players_by_id.values()))
    vbd_by_id = {p["player_id"]: p["vbd"] for p in ranked}

    side_a_ids = ["4984"]  # Josh Allen
    side_b_ids = ["9221"]  # Jahmyr Gibbs
    resp = client.post(
        "/api/trade/compare",
        json={"league_key": "kiddos", "side_a_player_ids": side_a_ids, "side_b_player_ids": side_b_ids},
    )
    assert resp.status_code == 200
    body = resp.json()

    expected_a = round(vbd_by_id["4984"], 1)
    expected_b = round(vbd_by_id["9221"], 1)
    assert body["side_a"]["total_vbd"] == expected_a
    assert body["side_b"]["total_vbd"] == expected_b
    assert body["vbd_differential"] == round(expected_a - expected_b, 1)


def test_trade_compare_response_has_no_shapley_or_portfolio_fields():
    """The skeleton must not silently grow the real (future-chunk) value engine's fields --
    checks the actual response KEYS (top-level and per-player), not the method_note's own
    explanatory prose, which legitimately mentions "Shapley"/"marginal" by name to disclaim them."""
    resp = client.post(
        "/api/trade/compare",
        json={"league_key": "kiddos", "side_a_player_ids": ["4984"], "side_b_player_ids": ["9221"]},
    )
    body = resp.json()
    assert set(body.keys()) == {
        "league_key", "league_name", "side_a", "side_b",
        "vbd_differential", "projected_points_differential", "method_note",
    }
    for side in (body["side_a"], body["side_b"]):
        assert set(side.keys()) == {"players", "total_vbd", "total_projected_points", "unknown_player_ids"}
        for row in side["players"]:
            assert set(row.keys()) == {"player_id", "name", "position", "team", "projected_points", "vbd"}
            assert "shapley" not in row and "marginal_value" not in row and "risk_aversion" not in row
    assert "method_note" in body


def test_trade_compare_both_leagues():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.post(
            "/api/trade/compare",
            json={"league_key": league_key, "side_a_player_ids": ["4984"], "side_b_player_ids": ["9221"]},
        )
        assert resp.status_code == 200
        assert resp.json()["league_key"] == league_key


def test_trade_compare_unknown_player_id_404():
    resp = client.post(
        "/api/trade/compare",
        json={"league_key": "kiddos", "side_a_player_ids": ["not_a_real_id"], "side_b_player_ids": []},
    )
    assert resp.status_code == 404


def test_trade_compare_empty_sides_is_valid_zero_comparison():
    resp = client.post("/api/trade/compare", json={"league_key": "kiddos", "side_a_player_ids": [], "side_b_player_ids": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["side_a"]["total_vbd"] == 0
    assert body["side_b"]["total_vbd"] == 0
    assert body["vbd_differential"] == 0
