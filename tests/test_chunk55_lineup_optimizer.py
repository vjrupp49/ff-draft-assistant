"""
Chunk 55 -- regression coverage for the Start/Bench Lineup Optimizer
(app/routers/lineup.py). Uses a REAL completed roster reused from Chunks
40/41's existing mock-draft artifacts (data/replay_trajectories/
chunk41_slot7_seed1_full_picklog.json, slot 7's full 15-round roster) --
not newly generated data, per this chunk's own scoping note (both real
leagues are still pre_draft; genuine real-roster validation has to wait
until after an actual draft).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services import vbd as vbd_service

client = TestClient(app)

REPO_ROOT = Path(__file__).parent.parent
_PICKLOG_PATH = REPO_ROOT / "data" / "replay_trajectories" / "chunk41_slot7_seed1_full_picklog.json"


def _slot7_roster_ids() -> list[str]:
    picklog = json.loads(_PICKLOG_PATH.read_text())
    ids = [p["player_id"] for p in picklog if p["slot"] == 7]
    assert len(ids) == 15  # a full, completed 15-round SUPER_FLEX roster
    return ids


def test_optimizer_matches_allocate_roster_starters_directly(players_by_id: dict[str, Any]):
    """The endpoint's starter/bench split must be byte-identical to calling
    vbd.allocate_roster_starters_with_flex_ranks directly -- no reimplemented logic."""
    roster_ids = _slot7_roster_ids()
    resp = client.post("/api/lineup/optimize", json={"player_ids": roster_ids, "league_key": "kiddos"})
    assert resp.status_code == 200
    body = resp.json()
    endpoint_starters = {p["player_id"] for p in body["starters"]}
    endpoint_bench = {p["player_id"] for p in body["bench"]}

    roster_players = [players_by_id[pid] for pid in roster_ids]
    percentile_lookup = vbd_service.compute_league_wide_percentiles(list(players_by_id.values()))
    direct_started, _ = vbd_service.allocate_roster_starters_with_flex_ranks(roster_players, percentile_lookup)

    assert endpoint_starters == direct_started
    assert endpoint_bench == (set(roster_ids) - direct_started)
    assert len(endpoint_starters) + len(endpoint_bench) == 15


def test_optimizer_works_for_both_leagues():
    roster_ids = _slot7_roster_ids()
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.post("/api/lineup/optimize", json={"player_ids": roster_ids, "league_key": league_key})
        assert resp.status_code == 200
        assert resp.json()["league_key"] == league_key
        assert resp.json()["roster_size"] == 15


def test_optimizer_surfaces_injury_status_field():
    """injury_status must be present as a key on every row (None is fine -- most players aren't hurt),
    confirming projections.py's Chunk 55 addition actually flows through to this endpoint."""
    roster_ids = _slot7_roster_ids()
    resp = client.post("/api/lineup/optimize", json={"player_ids": roster_ids, "league_key": "kiddos"})
    body = resp.json()
    for row in body["starters"] + body["bench"]:
        assert "injury_status" in row


def test_empty_roster_handled_gracefully_not_as_an_error():
    """An explicitly-empty player_ids list (distinct from omitting the field) must be a valid 200,
    not the 'player_ids is required' validation error -- this is the pre-draft case for both real leagues."""
    resp = client.post("/api/lineup/optimize", json={"player_ids": [], "league_key": "kiddos"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["roster_size"] == 0
    assert body["starters"] == []
    assert body["bench"] == []


def test_live_roster_path_read_only_and_graceful_for_pre_draft_leagues():
    """Real, read-only call against Sleeper's rosters endpoint for both real leagues --
    both are pre_draft as of this chunk, so an empty roster is the correct, expected result."""
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.post(
            "/api/lineup/optimize",
            json={"use_live_roster": True, "roster_id": 1, "league_key": league_key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["roster_size"] == 0
        assert "note" in body


def test_missing_player_ids_is_400_not_500():
    resp = client.post("/api/lineup/optimize", json={"league_key": "kiddos"})
    assert resp.status_code == 400


def test_live_roster_omitted_roster_id_resolves_my_roster_chunk_56():
    """CHUNK 56 update: use_live_roster=true with NO roster_id now resolves MY roster via
    app.services.roster_identity instead of requiring one -- both real leagues are pre_draft,
    so this is a graceful empty-roster 200, not the old 400 "roster_id is required" error."""
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.post("/api/lineup/optimize", json={"use_live_roster": True, "league_key": league_key})
        assert resp.status_code == 200
        assert resp.json()["roster_size"] == 0


def test_unknown_player_id_is_404():
    resp = client.post("/api/lineup/optimize", json={"player_ids": ["not_a_real_player_id"], "league_key": "kiddos"})
    assert resp.status_code == 404


def test_bogus_league_key_is_404():
    resp = client.post("/api/lineup/optimize", json={"player_ids": ["4984"], "league_key": "bogus"})
    assert resp.status_code == 404
