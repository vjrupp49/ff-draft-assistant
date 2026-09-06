"""
Chunk 73 -- the display-only "rookie / new situation" badge.

Like Chunk 69's reach flag, it reads fields projections.py ALREADY puts
on every player (`low_confidence`, `seasons_used`, `team_changed`,
`most_recent_historical_team`) -- so these tests stub
recommend()/shapley/portfolio and exercise ONLY the `situation` block
compute_draft_score() appends. No MCTS runs here.
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
    holder: dict[str, Any] = {"recommendations": [], "players": {}}

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


def _rec(pid="p1", name="Player", pos="RB", adp=30.0):
    return {"player_id": pid, "name": name, "position": pos, "team": "AAA",
            "mcts_score": 100.0, "mcts_score_stderr": 1.0, "vbd_score": 40.0,
            "market_adp": adp, "within_noise_of_leader": False}


def _player(pid="p1", name="Player", pos="RB", team="AAA", *, seasons=(2025, 2024, 2023),
            low_confidence=False, team_changed=False, prev_team=None, adp=30.0):
    return {"player_id": pid, "name": name, "position": pos, "team": team,
            "projected_points": 100.0, "market_adp": adp,
            "seasons_used": list(seasons), "low_confidence": low_confidence,
            "team_changed": team_changed, "most_recent_historical_team": prev_team}


def _run(stub, rec, player):
    stub["recommendations"] = [rec]
    return draft_score_engine.compute_draft_score(_state(), {player["player_id"]: player})


# --------------------------------------------------------------------------

def test_established_same_team_player_is_not_flagged(_stub_engine):
    r = _run(_stub_engine, _rec(), _player(seasons=(2025, 2024, 2023), low_confidence=False, team_changed=False))
    s = r["situation"]
    assert s["flag"] is False
    assert s["rookie_or_thin_track_record"] is False
    assert s["team_changed"] is False
    assert s["from_team"] is None and s["to_team"] is None


def test_rookie_with_no_history_is_flagged(_stub_engine):
    r = _run(_stub_engine, _rec(name="Rookie RB"),
             _player(name="Rookie RB", seasons=(), low_confidence=True, team_changed=False))
    s = r["situation"]
    assert s["flag"] is True
    assert s["rookie_or_thin_track_record"] is True
    assert s["team_changed"] is False


def test_thin_history_low_confidence_is_flagged_even_with_a_season(_stub_engine):
    # projections.py sets low_confidence for "very limited snaps" too, not
    # only zero seasons -- honor that flag.
    r = _run(_stub_engine, _rec(), _player(seasons=(2024,), low_confidence=True, team_changed=False))
    assert r["situation"]["rookie_or_thin_track_record"] is True
    assert r["situation"]["flag"] is True


def test_team_changer_is_flagged_with_from_and_to(_stub_engine):
    r = _run(_stub_engine, _rec(name="Moved WR"),
             _player(name="Moved WR", team="HOU", seasons=(2025, 2024, 2023),
                     low_confidence=False, team_changed=True, prev_team="NE"))
    s = r["situation"]
    assert s["flag"] is True
    assert s["team_changed"] is True
    assert s["rookie_or_thin_track_record"] is False
    assert s["from_team"] == "NE" and s["to_team"] == "HOU"


def test_from_to_teams_are_none_when_no_team_change(_stub_engine):
    r = _run(_stub_engine, _rec(), _player(team="AAA", team_changed=False, prev_team="AAA"))
    assert r["situation"]["from_team"] is None
    assert r["situation"]["to_team"] is None


def test_situation_and_reach_can_co_occur_independently(_stub_engine):
    # a rookie (situation) whose ADP is also 20 picks past the current pick (reach).
    # current pick 23 -> reach threshold is ADP >= 38.
    rec = _rec(name="Hyped Rookie", adp=50.0)
    player = _player(name="Hyped Rookie", seasons=(), low_confidence=True, adp=50.0)
    _stub_engine["recommendations"] = [rec]
    result = draft_score_engine.compute_draft_score(_state(my_slot=3, picks=22),
                                                    {player["player_id"]: player})
    assert result["reach"]["is_reach"] is True
    assert result["situation"]["flag"] is True
    assert result["situation"]["rookie_or_thin_track_record"] is True
    # two independent blocks -- neither clobbers the other
    assert "reach" in result and "situation" in result
