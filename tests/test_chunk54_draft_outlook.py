"""
Chunk 54 -- regression coverage for the Draft Outlook view's new pieces:
per-league target persistence (app/services/targets.py,
app/routers/targets.py), the ADP-based survival estimator
(app/services/survival.py), and the Draft-Score top-picks endpoint that
pre-advances the board for a non-1 my_slot (app/routers/outlook.py).

Target-persistence tests monkeypatch `targets_service.TARGETS_PATH` to a
tmp_path file -- these must NEVER read or write the real
data/draft_targets.json, which holds Vincent's actual target picks.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import targets as targets_service
from app.services import survival as survival_service
from app.services.draft_state import DraftState

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_targets_file(tmp_path, monkeypatch):
    """Every test in this file gets its own empty, throwaway targets file."""
    monkeypatch.setattr(targets_service, "TARGETS_PATH", tmp_path / "draft_targets.json")


# ---------------------------------------------------------------------------
# Target persistence + per-league scoping
# ---------------------------------------------------------------------------

def test_target_star_unstar_round_trip():
    assert targets_service.get_targets("kiddos") == []
    assert targets_service.add_target("kiddos", "4984") == ["4984"]
    assert targets_service.get_targets("kiddos") == ["4984"]
    assert targets_service.remove_target("kiddos", "4984") == []
    assert targets_service.get_targets("kiddos") == []


def test_target_star_is_idempotent():
    targets_service.add_target("kiddos", "4984")
    targets_service.add_target("kiddos", "4984")
    assert targets_service.get_targets("kiddos") == ["4984"]


def test_targets_scoped_per_league_no_leakage():
    targets_service.add_target("kiddos", "4984")
    targets_service.add_target("former_bradley_bums", "7564")
    assert targets_service.get_targets("kiddos") == ["4984"]
    assert targets_service.get_targets("former_bradley_bums") == ["7564"]


def test_targets_router_scoping_and_validation():
    resp = client.post("/api/targets", json={"player_id": "9221", "league_key": "kiddos"})
    assert resp.status_code == 200
    assert resp.json()["player_ids"] == ["9221"]

    resp = client.get("/api/targets", params={"league_key": "former_bradley_bums"})
    assert resp.json()["player_ids"] == [], "Former Bradley Bums must not see Kiddos' target"

    resp = client.get("/api/targets", params={"league_key": "bogus"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Survival estimator (app/services/survival.py)
# ---------------------------------------------------------------------------

def test_survival_trivial_when_pick_no_not_in_future(players_by_id: dict[str, Any]):
    state = DraftState.hypothetical(my_slot=1, picks_so_far=[], num_teams=10)
    probs = survival_service.estimate_survival_probabilities(state, players_by_id, target_pick_no=1, num_replays=10)
    undrafted_ids = [pid for pid in players_by_id if pid not in state.drafted_player_ids]
    assert all(probs[pid] == 1.0 for pid in undrafted_ids[:20])


def test_survival_decreases_monotonically_with_pick_no(players_by_id: dict[str, Any]):
    """A top-ADP player's survival probability should never INCREASE as the target pick number grows."""
    state = DraftState.hypothetical(my_slot=1, picks_so_far=[], num_teams=10)
    top_adp_id = min(
        (pid for pid in players_by_id if players_by_id[pid].get("market_adp") is not None),
        key=lambda pid: players_by_id[pid]["market_adp"],
    )
    prev = 1.0
    for pick_no in (2, 6, 12, 24):
        probs = survival_service.estimate_survival_probabilities(
            state, players_by_id, target_pick_no=pick_no, num_replays=150, seed=1
        )
        current = probs[top_adp_id]
        assert current <= prev + 0.05, (  # small tolerance for Monte Carlo noise
            f"survival probability rose from {prev} to {current} between earlier and pick_no={pick_no}"
        )
        prev = current


def test_survival_router_rejects_pick_no_past_draft_length():
    resp = client.get("/api/outlook/survival", params={"pick_no": 99999, "league_key": "kiddos"})
    assert resp.status_code == 400


def test_survival_router_works_for_both_leagues():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.get("/api/outlook/survival", params={"pick_no": 12, "league_key": league_key, "top_n": 5, "num_replays": 30})
        assert resp.status_code == 200
        body = resp.json()
        assert body["league_key"] == league_key
        assert len(body["players"]) == 5


# ---------------------------------------------------------------------------
# Draft Score top-picks (app/routers/outlook.py) -- non-1 my_slot pre-advance
# ---------------------------------------------------------------------------

def test_top_picks_slot_one_needs_no_simulated_picks():
    resp = client.get("/api/outlook/top-picks", params={"my_slot": 1, "league_key": "kiddos", "top_n": 5, "seed": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["picks_simulated_before_my_turn"] == 0
    assert body["current_pick_no"] == 1
    assert body["note"] is None
    assert len(body["recommendations"]) > 0


def test_top_picks_non_one_slot_pre_advances_board():
    resp = client.get("/api/outlook/top-picks", params={"my_slot": 7, "league_key": "kiddos", "top_n": 5, "seed": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["picks_simulated_before_my_turn"] == 6
    assert body["current_pick_no"] == 7
    assert body["note"] is not None
    assert len(body["recommendations"]) > 0


def test_top_picks_rejects_slot_beyond_num_teams():
    resp = client.get("/api/outlook/top-picks", params={"my_slot": 99, "league_key": "kiddos"})
    assert resp.status_code == 400


def test_top_picks_works_for_both_leagues():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.get("/api/outlook/top-picks", params={"my_slot": 1, "league_key": league_key, "top_n": 5})
        assert resp.status_code == 200
        assert resp.json()["league_key"] == league_key
