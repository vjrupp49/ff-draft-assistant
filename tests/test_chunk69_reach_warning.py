"""
Chunk 69 -- the display-only "reach" hint on a recommendation.

The hint is pure arithmetic on values mcts.recommend() already returns
(`market_adp` + `vbd_score` on every candidate) -- so these tests stub
recommend()/shapley/portfolio and exercise ONLY the reach block that
compute_draft_score() bolts on at the end. No MCTS runs here.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import draft_score_engine
from app.services.draft_state import DraftState


def _state(my_slot: int = 3, picks: int = 22) -> DraftState:
    """A draft with `picks` picks already made -> current_pick_no = picks+1.
    my_slot=3, 10-team snake: my turns are pick 3, 18, 23, 38, ..."""
    s = DraftState(my_slot=my_slot, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS))
    for i in range(picks):
        s.add_pick(f"drafted_{i}")
    return s


@pytest.fixture
def _stub_engine(monkeypatch):
    """Stub the three heavy calls compute_draft_score makes. The test
    supplies the `recommendations` list (with market_adp / vbd_score)."""
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


def _rec(pid, name, pos, mcts, vbd, adp):
    return {"player_id": pid, "name": name, "position": pos, "team": "AAA",
            "mcts_score": mcts, "mcts_score_stderr": 1.0, "vbd_score": vbd,
            "market_adp": adp, "within_noise_of_leader": False}


def _players(recs):
    return {r["player_id"]: {"player_id": r["player_id"], "name": r["name"],
                             "position": r["position"], "team": "AAA",
                             "projected_points": 100.0, "market_adp": r["market_adp"]} for r in recs}


# --------------------------------------------------------------------------

def test_flags_a_reach_and_names_an_at_risk_alternative(_stub_engine):
    # current pick 23 (my_slot=3), next turn pick 38.
    recs = [
        _rec("rb1", "Reachy RB", "RB", mcts=100.0, vbd=40.0, adp=55.0),   # ADP 55 vs pick 23 -> 32 early -> REACH
        _rec("wr1", "At-Risk WR", "WR", mcts=95.0, vbd=48.0, adp=30.0),    # ADP 30 <= 38 -> at risk, highest vbd
        _rec("wr2", "Safer WR", "WR", mcts=96.0, vbd=52.0, adp=44.0),      # ADP 44 > 38 -> NOT at risk (survives)
        _rec("te1", "At-Risk TE", "TE", mcts=90.0, vbd=35.0, adp=25.0),    # at risk but lower vbd than wr1
    ]
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))

    assert result["draft_score"]["name"] == "Reachy RB"  # highest mcts_score
    assert result["draft_score"]["adp"] == 55.0
    reach = result["reach"]
    assert reach["is_reach"] is True
    assert reach["current_pick_no"] == 23
    assert reach["next_turn_pick_no"] == 38
    assert reach["picks_early"] == 32.0
    assert reach["alternative"]["name"] == "At-Risk WR"  # highest vbd among adp <= 38, != focus
    assert reach["alternative"]["adp"] == 30.0


def test_no_reach_when_recommendation_is_on_pace(_stub_engine):
    recs = [
        _rec("rb1", "On-Pace RB", "RB", mcts=100.0, vbd=40.0, adp=27.0),  # ADP 27 vs pick 23 -> 4 early -> not a reach
        _rec("wr1", "A WR", "WR", mcts=90.0, vbd=48.0, adp=20.0),
    ]
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert result["reach"]["is_reach"] is False
    assert result["reach"]["picks_early"] == 4.0
    assert result["reach"]["alternative"] is None


def test_exactly_at_threshold_is_a_reach(_stub_engine):
    recs = [_rec("rb1", "Edge RB", "RB", mcts=100.0, vbd=40.0, adp=38.0)]  # 38 - 23 = 15 -> >= 15
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert result["reach"]["is_reach"] is True
    assert result["reach"]["picks_early"] == 15.0
    assert result["reach"]["alternative"] is None  # no other candidate to offer


def test_reach_but_no_alternative_when_nobody_is_at_risk(_stub_engine):
    recs = [
        _rec("rb1", "Reachy RB", "RB", mcts=100.0, vbd=40.0, adp=60.0),
        _rec("wr1", "Also Safe WR", "WR", mcts=95.0, vbd=50.0, adp=50.0),  # ADP 50 > next turn 38 -> survives
    ]
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert result["reach"]["is_reach"] is True
    assert result["reach"]["alternative"] is None


def test_a_wildly_underdrafted_elite_is_not_offered_as_the_alternative(_stub_engine):
    """A player whose ADP is far BELOW the current pick (elite still on the
    board -- opponent-model quirk or a real falling knife) must not be the
    'at risk before your next turn' suggestion. current pick 23, next 38."""
    recs = [
        _rec("rb1", "Reachy RB", "RB", mcts=100.0, vbd=40.0, adp=55.0),
        _rec("qb1", "Elite QB Somehow Here", "QB", mcts=98.0, vbd=90.0, adp=6.0),  # ADP 6 << pick 23 -> excluded
        _rec("wr1", "Genuinely At-Risk WR", "WR", mcts=95.0, vbd=44.0, adp=33.0),  # 23 <= 33 <= 38 -> the real answer
    ]
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert result["reach"]["is_reach"] is True
    assert result["reach"]["alternative"]["name"] == "Genuinely At-Risk WR"


def test_missing_adp_data_is_safe(_stub_engine):
    recs = [_rec("rb1", "Unknown-ADP RB", "RB", mcts=100.0, vbd=40.0, adp=None)]
    _stub_engine["recommendations"] = recs
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22), _players(recs))
    assert result["reach"]["is_reach"] is False
    assert result["reach"]["recommended_adp"] is None
    assert result["reach"]["picks_early"] is None
    assert result["draft_score"]["adp"] is None


def test_my_next_turn_pick_no_snake_math():
    f = draft_score_engine._my_next_turn_pick_no
    # 10-team snake, my_slot 3: turns at 3, 18, 23, 38, 43, ...
    assert f(_state(my_slot=3, picks=2)) == 18   # on the clock at pick 3 -> next is 18
    assert f(_state(my_slot=3, picks=17)) == 23  # on the clock at pick 18 -> next is 23
    assert f(_state(my_slot=1, picks=0)) == 20   # slot 1: pick 1 -> next is 20
