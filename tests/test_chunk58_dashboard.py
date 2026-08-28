"""
Chunk 58 -- regression coverage for the League Dashboard
(app/routers/dashboard.py): a real transactions feed and Power Rankings
(portfolio.evaluate_roster across every roster), deliberately NOT
standings/best-team/best-draft.

  1. Transactions against BOTH real leagues (live, read-only) -- confirms
     the expected sparse/empty pre-draft state.
  2. Power Rankings against BOTH real leagues (live, read-only) -- all 10
     rosters tied at 0.0 pre-draft, "my" roster correctly flagged via
     Chunk 56's roster_identity (reused, not re-derived).
  3. Power Rankings demo mode -- clearly labeled (is_demo=True), built
     from Chunk 41's existing full-draft picklog (ALL 10 slots), produces
     a real non-tied ranking, cross-checked byte-identical against
     calling evaluate_roster() directly with the same seed.
  4. Confirms NO standings field/endpoint exists anywhere in this
     module's response shapes (explicitly out of scope, not faked).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services import portfolio as portfolio_service
from app.services import roster_identity
from app.services.vbd import compute_league_wide_percentiles

client = TestClient(app)

REPO_ROOT = Path(__file__).parent.parent
_PICKLOG_PATH = REPO_ROOT / "data" / "replay_trajectories" / "chunk41_slot7_seed1_full_picklog.json"


def setup_function():
    roster_identity._my_roster_id_cache.clear()


def teardown_function():
    roster_identity._my_roster_id_cache.clear()


# ---------------------------------------------------------------------------
# 1. Transactions -- both real leagues, expected sparse/empty pre-draft
# ---------------------------------------------------------------------------

def test_transactions_both_real_leagues_pre_draft_empty():
    for league_key in ("kiddos", "former_bradley_bums"):
        resp = client.get("/api/dashboard/transactions", params={"league_key": league_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["transactions"] == []
        assert body["league_key"] == league_key


def test_transactions_bogus_league_key_404():
    resp = client.get("/api/dashboard/transactions", params={"league_key": "bogus"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Power Rankings -- both real leagues, expected all-tied-at-zero pre-draft
# ---------------------------------------------------------------------------

def test_power_rankings_both_real_leagues_all_tied_pre_draft():
    for league_key, expected_my_roster_id in (("kiddos", 7), ("former_bradley_bums", 8)):
        resp = client.get("/api/dashboard/power-rankings", params={"league_key": league_key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_demo"] is False
        rankings = body["rankings"]
        assert len(rankings) == 10
        assert {r["risk_adjusted_score"] for r in rankings} == {0.0}
        assert sorted(r["rank"] for r in rankings) == list(range(1, 11))

        mine = [r for r in rankings if r["is_mine"]]
        assert len(mine) == 1
        # Confirmed directly (Chunk 56): roster_id=7 in Kiddos, roster_id=8 in Former Bradley Bums.
        assert mine[0]["roster_id"] == expected_my_roster_id


def test_power_rankings_bogus_league_key_404():
    resp = client.get("/api/dashboard/power-rankings", params={"league_key": "bogus"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Power Rankings demo -- clearly labeled, real (non-tied) ranking
# ---------------------------------------------------------------------------

def test_power_rankings_demo_is_clearly_labeled_and_non_tied():
    resp = client.get("/api/dashboard/power-rankings/demo", params={"league_key": "kiddos"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_demo"] is True
    assert "demo_source" in body and "chunk41" in body["demo_source"].lower()

    rankings = body["rankings"]
    assert len(rankings) == 10
    scores = [r["risk_adjusted_score"] for r in rankings]
    assert len(set(scores)) > 1, "demo rankings should be real, differentiated scores, not tied like the pre-draft real view"
    assert scores == sorted(scores, reverse=True)
    for r in rankings:
        assert r["team_name"].startswith("Demo Team"), "demo team names must be unmistakably synthetic"


def test_power_rankings_demo_matches_evaluate_roster_directly(players_by_id: dict[str, Any]):
    picklog = json.loads(_PICKLOG_PATH.read_text())
    my_ids = [p["player_id"] for p in picklog if p["slot"] == 1]
    percentile_lookup = compute_league_wide_percentiles(list(players_by_id.values()))
    roster_players = [players_by_id[pid] for pid in my_ids]
    direct_result = portfolio_service.evaluate_roster(roster_players, percentile_lookup=percentile_lookup, seed=42)

    resp = client.get("/api/dashboard/power-rankings/demo", params={"league_key": "kiddos"})
    body = resp.json()
    demo_slot1 = next(r for r in body["rankings"] if r["roster_id"] == 1)
    assert demo_slot1["risk_adjusted_score"] == direct_result["risk_adjusted_score"]
    assert demo_slot1["is_mine"] is True  # demo mode designates slot 1 as "mine"


def test_power_rankings_demo_never_hits_live_sleeper(monkeypatch):
    """Demo mode must not call Sleeper at all -- it's built entirely from the on-disk picklog."""
    from app.services.sleeper import sleeper_client

    def _boom(*args, **kwargs):
        raise AssertionError("demo mode must not call Sleeper")

    monkeypatch.setattr(sleeper_client, "get_rosters", _boom)
    monkeypatch.setattr(sleeper_client, "get_users", _boom)
    monkeypatch.setattr(sleeper_client, "get_transactions", _boom)

    resp = client.get("/api/dashboard/power-rankings/demo", params={"league_key": "kiddos"})
    assert resp.status_code == 200
    assert resp.json()["is_demo"] is True


# ---------------------------------------------------------------------------
# 4. Standings explicitly NOT built anywhere
# ---------------------------------------------------------------------------

def test_no_standings_field_anywhere_in_dashboard_responses():
    tx = client.get("/api/dashboard/transactions", params={"league_key": "kiddos"}).json()
    pr = client.get("/api/dashboard/power-rankings", params={"league_key": "kiddos"}).json()
    demo = client.get("/api/dashboard/power-rankings/demo", params={"league_key": "kiddos"}).json()
    for payload in (tx, pr, demo):
        assert "standings" not in payload
        assert "wins" not in json.dumps(payload).lower()
        assert "losses" not in json.dumps(payload).lower()
