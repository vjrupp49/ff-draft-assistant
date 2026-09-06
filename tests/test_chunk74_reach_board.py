"""
Chunk 74 -- reach fields on every shown alternative (Part B item 1).

The "sort by ADP risk" toggle is frontend-only (re-orders the same array),
so the backend contract to test is: each `alternatives_considered` entry
now carries `adp` / `picks_early` / `is_reach`, the list is up to 7
(so the frontend toggle has spare candidates), it stays in value order,
and it still excludes the #1 pick. Stubs recommend()/shapley/portfolio --
no MCTS.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import draft_score_engine
from app.services.draft_state import DraftState


def _state(my_slot: int = 3, picks: int = 22) -> DraftState:
    s = DraftState(my_slot=my_slot, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS))
    for i in range(picks):
        s.add_pick(f"drafted_{i}")
    return s


@pytest.fixture
def _stub_engine(monkeypatch):
    holder: dict[str, Any] = {"recommendations": []}

    def fake_recommend(draft_state, players_by_id, **kw):
        return {"recommendations": holder["recommendations"]}

    def fake_shapley(roster, **kw):
        return {"players": [{"player_id": p["player_id"], "shapley_value": 10.0, "stderr": 1.0} for p in roster]}

    def fake_portfolio(roster, **kw):
        return {"players": [{"player_id": p["player_id"], "is_starter": True,
                             "bench_discount_applied": None, "bench_rank": None} for p in roster]}

    monkeypatch.setattr(draft_score_engine.mcts_service, "recommend", fake_recommend)
    monkeypatch.setattr(draft_score_engine.shapley_service, "evaluate_shapley", fake_shapley)
    monkeypatch.setattr(draft_score_engine.portfolio_service, "evaluate_roster", fake_portfolio)
    return holder


def _rec(pid, name, mcts, adp, pos="RB"):
    return {"player_id": pid, "name": name, "position": pos, "team": "AAA",
            "mcts_score": mcts, "mcts_score_stderr": 1.0, "vbd_score": 40.0,
            "market_adp": adp, "within_noise_of_leader": False}


def _players(recs):
    return {r["player_id"]: {"player_id": r["player_id"], "name": r["name"], "position": r["position"],
                             "team": "AAA", "projected_points": 100.0, "market_adp": r["market_adp"]}
            for r in recs}


# --------------------------------------------------------------------------

def test_every_alternative_carries_adp_and_reach_fields(_stub_engine):
    # current pick 23 -> reach threshold: picks_early >= 15 i.e. adp >= 38
    recs = [
        _rec("p1", "Top Pick", mcts=200.0, adp=20.0),   # #1 -> excluded from alts
        _rec("p2", "On Pace", mcts=190.0, adp=25.0),     # 25-23 = 2  -> not a reach
        _rec("p3", "Big Reach", mcts=180.0, adp=70.0),   # 70-23 = 47 -> reach
        _rec("p4", "Edge Reach", mcts=170.0, adp=38.0),  # 38-23 = 15 -> reach (boundary)
        _rec("p5", "No ADP", mcts=160.0, adp=None),
    ]
    _stub_engine["recommendations"] = recs
    r = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))

    alts = r["alternatives_considered"]
    assert [a["name"] for a in alts] == ["On Pace", "Big Reach", "Edge Reach", "No ADP"]  # #1 excluded, value order
    by_name = {a["name"]: a for a in alts}
    assert by_name["On Pace"] == {**by_name["On Pace"], "adp": 25.0, "picks_early": 2.0, "is_reach": False}
    assert by_name["Big Reach"]["is_reach"] is True and by_name["Big Reach"]["picks_early"] == 47.0
    assert by_name["Edge Reach"]["is_reach"] is True and by_name["Edge Reach"]["picks_early"] == 15.0
    assert by_name["No ADP"]["adp"] is None
    assert by_name["No ADP"]["picks_early"] is None
    assert by_name["No ADP"]["is_reach"] is False


def test_alternatives_list_is_up_to_seven_and_stays_in_value_order(_stub_engine):
    recs = [_rec(f"p{i}", f"P{i}", mcts=300.0 - i, adp=10.0 + i) for i in range(12)]
    _stub_engine["recommendations"] = recs
    r = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    alts = r["alternatives_considered"]
    assert len(alts) == 7  # was 5; +2 spare for the frontend risk-sort
    assert "P0" not in [a["name"] for a in alts]  # P0 is #1 by score -> excluded
    scores = [a["score"] for a in alts]
    assert scores == sorted(scores, reverse=True)  # backend does NOT reorder; risk-sort is frontend-only


def test_the_number_one_pick_still_carries_its_own_reach_block(_stub_engine):
    recs = [_rec("p1", "Reachy #1", mcts=200.0, adp=55.0), _rec("p2", "Alt", mcts=190.0, adp=24.0)]
    _stub_engine["recommendations"] = recs
    r = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert r["reach"]["is_reach"] is True          # Chunk 69 block unchanged
    assert r["draft_score"]["adp"] == 55.0
    assert "Reachy #1" not in [a["name"] for a in r["alternatives_considered"]]
