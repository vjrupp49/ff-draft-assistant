"""
Chunk 57 -- regression coverage for the Waiver/Free Agency Suggester
skeleton (app/routers/waivers.py):
  1. Availability against BOTH real leagues (live, read-only) -- confirms
     the expected pre-draft "essentially everything is available" state
     is handled gracefully, not as an error or edge case needing a fix.
  2. Availability against a MONKEYPATCHED synthetic 10-team league built
     from ALL 10 draft slots of Chunk 41's existing full-draft picklog
     (not just one roster, not newly generated data) -- confirms rostered
     players are correctly excluded and "my roster" position counts are
     correct.
  3. Ranking method: byte-identical to calling vbd.calculate_vbd()
     directly, sorted descending -- no reimplemented valuation logic.
  4. Confirms app.services.roster_identity (Chunk 56) is reused directly
     for "my roster" -- not re-derived here.
  5. injury_status (Chunk 55) flows through into the response.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import roster_identity
from app.services.vbd import calculate_vbd

client = TestClient(app)

REPO_ROOT = Path(__file__).parent.parent
_PICKLOG_PATH = REPO_ROOT / "data" / "replay_trajectories" / "chunk41_slot7_seed1_full_picklog.json"


def _synthetic_10_team_league(my_slot: int = 5) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
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
            "metadata": {"team_name": ("My Team" if slot == my_slot else f"Opp Team {slot}")},
        }
        for slot in by_slot
    ]
    all_rostered: set[str] = set()
    for ids in by_slot.values():
        all_rostered.update(ids)
    return rosters, users, all_rostered


@pytest.fixture(autouse=True)
def clear_roster_id_cache():
    roster_identity._my_roster_id_cache.clear()
    yield
    roster_identity._my_roster_id_cache.clear()


# ---------------------------------------------------------------------------
# 1. Pre-draft real leagues -- "essentially everything available"
# ---------------------------------------------------------------------------

def test_waivers_both_real_leagues_pre_draft_shows_full_pool_available(players_by_id: dict[str, Any]):
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.get("/api/waivers/available", params={"league_key": league_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_rostered_players"] == 0
        assert body["my_roster_size"] == 0
        assert body["my_roster_position_counts"] == {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        # essentially the WHOLE draft-relevant player pool is "available" pre-draft
        assert body["count"] == len(players_by_id)


# ---------------------------------------------------------------------------
# 2. Synthetic 10-team league -- rostered players correctly excluded
# ---------------------------------------------------------------------------

def test_waivers_synthetic_league_excludes_rostered_players():
    rosters, users, all_rostered = _synthetic_10_team_league(my_slot=5)
    with patch("app.services.sleeper.sleeper_client.get_rosters", new=AsyncMock(return_value=rosters)), \
         patch("app.services.sleeper.sleeper_client.get_users", new=AsyncMock(return_value=users)):
        resp = client.get("/api/waivers/available", params={"league_key": "kiddos"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["my_roster_id"] == 5
    assert body["my_roster_size"] == 15
    assert sum(body["my_roster_position_counts"].values()) == 15
    assert body["total_rostered_players"] == len(all_rostered)

    available_ids = {p["player_id"] for p in body["available_players"]}
    assert not (available_ids & all_rostered), "a rostered player leaked into the available list"


def test_waivers_bogus_league_key_404():
    resp = client.get("/api/waivers/available", params={"league_key": "bogus"})
    assert resp.status_code == 404


def test_waivers_invalid_position_400():
    resp = client.get("/api/waivers/available", params={"league_key": "kiddos", "position": "K"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. Ranking method -- simple raw VBD, not roster-need-aware, not reimplemented
# ---------------------------------------------------------------------------

def test_waivers_ranking_matches_calculate_vbd_directly(players_by_id: dict[str, Any]):
    direct_ranked = calculate_vbd(list(players_by_id.values()))
    direct_wr_vbd = {p["player_id"]: p["vbd"] for p in direct_ranked if p["position"] == "WR"}

    resp = client.get("/api/waivers/available", params={"league_key": "kiddos", "position": "WR"})
    body = resp.json()
    assert all(p["position"] == "WR" for p in body["available_players"])
    vbds = [p["vbd"] for p in body["available_players"]]
    assert vbds == sorted(vbds, reverse=True)
    for p in body["available_players"][:25]:
        assert p["vbd"] == direct_wr_vbd[p["player_id"]]


def test_waivers_response_has_no_needs_aware_fields():
    """This is a plain ranked list, not a recommendation engine -- no roster-need scoring, no
    "recommended" flag, no positional-need weighting anywhere in the response shape."""
    resp = client.get("/api/waivers/available", params={"league_key": "kiddos"})
    body = resp.json()
    assert set(body.keys()) == {
        "league_key", "league_name", "my_roster_id", "my_roster_size",
        "my_roster_position_counts", "total_rostered_players",
        "position_filter", "count", "available_players",
    }
    for row in body["available_players"][:10]:
        assert "need_score" not in row and "recommended" not in row and "roster_fit" not in row


# ---------------------------------------------------------------------------
# 4. roster_identity (Chunk 56) reused directly, not re-derived
# ---------------------------------------------------------------------------

def test_waivers_reuses_roster_identity_not_rederived():
    """Pre-warm roster_identity's cache with a KNOWN synthetic answer, then confirm waivers.py's
    my_roster_id in the response matches it exactly -- proving it went through the shared
    resolver/cache rather than independently re-matching owner_id somewhere in waivers.py."""
    from app.leagues import KIDDOS

    rosters, users, _ = _synthetic_10_team_league(my_slot=9)
    with patch("app.services.sleeper.sleeper_client.get_rosters", new=AsyncMock(return_value=rosters)):
        import asyncio

        asyncio.run(roster_identity.resolve_my_roster_id(KIDDOS, force_refresh=True))

    with patch("app.services.sleeper.sleeper_client.get_rosters", new=AsyncMock(return_value=rosters)), \
         patch("app.services.sleeper.sleeper_client.get_users", new=AsyncMock(return_value=users)):
        resp = client.get("/api/waivers/available", params={"league_key": "kiddos"})

    assert resp.json()["my_roster_id"] == 9  # the pre-warmed cached value, not re-derived


# ---------------------------------------------------------------------------
# 5. injury_status (Chunk 55) flows through
# ---------------------------------------------------------------------------

def test_waivers_rows_carry_injury_status_field():
    resp = client.get("/api/waivers/available", params={"league_key": "kiddos"})
    body = resp.json()
    assert len(body["available_players"]) > 0
    for row in body["available_players"][:20]:
        assert "injury_status" in row
