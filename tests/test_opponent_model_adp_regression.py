"""
Chunk 21 -- regression tests for wiring opponent_model.py's pick-timing
model to REAL market ADP (app/services/adp.py, via projections.py's new
`market_adp`/`market_adp_stdev` fields) instead of relying solely on the
original self-referential VBD-based proxy.

USER FEEDBACK THAT TRIGGERED THIS: after a live draft (Chunk 19), two
symptoms -- the app sometimes reached for a player who'd almost certainly
still be there many rounds later, and sometimes recommended an obscure
player with no real market presence at all, without any special "safe to
leave for later" signal.

ROOT CAUSE (Chunk 21 Tasks 1-4, confirmed via code trace + a live 150-pick
real-draft replay, not assumed): opponent_model.py's `sample_pick` (used
by mcts.py's rollout to model "will this player survive to my next turn")
was scored against `build_adp_proxy_ranks` -- a rank derived from this
league's own VBD, not real market behavior. Directly measured against
Chunk 19's real draft: median distance between the VBD-proxy's predicted
rank and a real opponent's actual pick_no was 37 ranks; real market ADP
(already being fetched for a DIFFERENT purpose, projections.py's point
estimates -- Chunks 17/18) was only 10.5 picks off, and was the closer
predictor in 114/133 (85.7%) of real opponent picks tested. Crucially,
Task 4 found the "expected value of waiting" CONCEPT already existed here
(that's the whole point of mcts.py's tree+rollout design, see that
module's docstring) -- it was just reasoning over an inaccurate survival
signal, not missing a mechanism.

`fixtures/chunk19_real_draft_picks.json` is the same real 150-pick history
used by test_flex_concentration_regression.py (Chunk 20) -- reused here
for a genuinely different check: NOT roster construction, but whether the
model's pick-timing signal actually predicts real human opponent behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services import opponent_model
from app.services import vbd as vbd_service

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chunk19_real_draft_picks.json"
MY_SLOT = 10  # the real Chunk 19 dry run's draft slot


def _load_real_picks() -> list[dict[str, Any]]:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Unit tests for build_market_adp_ranks -- pure function, no network, no
# simulation needed.
# ---------------------------------------------------------------------

def test_build_market_adp_ranks_prefers_real_adp_over_vbd_proxy():
    players = [
        {"player_id": "a", "market_adp": 12.5},
        {"player_id": "b", "market_adp": None},
    ]
    # Deliberately misleading VBD-proxy ranks (opposite of what real ADP
    # says for "a") -- real ADP must win whenever it's present.
    vbd_proxy_ranks = {"a": 300, "b": 7}
    ranks = opponent_model.build_market_adp_ranks(players, vbd_proxy_ranks)
    assert ranks["a"] == 12.5
    assert ranks["b"] == 7.0  # no real match -- falls back to the VBD proxy


def test_build_market_adp_ranks_handles_no_fallback_entry_without_crashing():
    players = [{"player_id": "c", "market_adp": None}]
    ranks = opponent_model.build_market_adp_ranks(players, {})  # empty fallback dict
    assert ranks["c"] == float(10**9)  # effectively "far away" -- must not raise


# ---------------------------------------------------------------------
# Real-data regression: market_adp is actually attached to real players by
# the projections pipeline (guards against projections.py's Chunk 21
# addition silently breaking).
# ---------------------------------------------------------------------

def test_market_adp_attached_to_a_known_elite_real_player(players_by_id: dict[str, dict[str, Any]]) -> None:
    by_name = {p["name"]: p for p in players_by_id.values()}
    josh_allen = by_name.get("Josh Allen")
    assert josh_allen is not None
    assert josh_allen.get("market_adp") is not None, (
        "Josh Allen (an elite, universally-rostered real QB1) should have a real "
        "FFC ADP match -- if this is None, projections.py's Chunk 21 market_adp "
        "attachment may be broken."
    )
    assert josh_allen["market_adp"] < 10  # real elite QB1s go in the first ~10 picks


# ---------------------------------------------------------------------
# Real-draft regression: real market ADP predicts real opponent pick
# timing meaningfully better than the old VBD-only proxy -- the core
# Chunk 21 Task 2 finding, locked in as a permanent guard against silently
# regressing back to (or below) the old proxy-only behavior.
# ---------------------------------------------------------------------

def test_market_adp_beats_vbd_proxy_at_predicting_real_opponent_pick_timing(
    players_by_id: dict[str, dict[str, Any]],
) -> None:
    real_picks = _load_real_picks()
    real_picks.sort(key=lambda p: p["pick_no"])
    # Every 5th real opponent pick -- a representative sample across the
    # whole draft without re-running calculate_vbd 135 times in a unit test.
    sample_picks = [p for i, p in enumerate(real_picks) if p["draft_slot"] != MY_SLOT and i % 5 == 0]
    assert len(sample_picks) >= 15  # meaningful sample size

    proxy_distances = []
    market_distances = []
    for pick in sample_picks:
        pick_no = pick["pick_no"]
        actual_pid = str(pick["player_id"])
        if actual_pid not in players_by_id:
            continue
        picks_before = [p for p in real_picks if p["pick_no"] < pick_no]
        drafted_ids = {str(p["player_id"]) for p in picks_before}

        all_players = list(players_by_id.values())
        vbd_ranked = vbd_service.calculate_vbd(all_players, drafted_player_ids=drafted_ids)
        vbd_proxy_ranks = opponent_model.build_adp_proxy_ranks(vbd_ranked)
        market_ranks = opponent_model.build_market_adp_ranks(all_players, vbd_proxy_ranks)

        proxy_val = vbd_proxy_ranks.get(actual_pid)
        market_val = market_ranks.get(actual_pid)
        if proxy_val is not None:
            proxy_distances.append(abs(proxy_val - pick_no))
        if market_val is not None:
            market_distances.append(abs(market_val - pick_no))

    assert proxy_distances and market_distances
    proxy_median = sorted(proxy_distances)[len(proxy_distances) // 2]
    market_median = sorted(market_distances)[len(market_distances) // 2]
    assert market_median < proxy_median, (
        f"market-ADP-primary ranks (median distance from real pick_no: {market_median}) should predict "
        f"real opponent pick timing meaningfully better than the old VBD-only proxy (median distance: "
        f"{proxy_median}) -- Chunk 21 Task 2 found real ADP was the closer predictor in 114/133 real "
        "opponent picks. If this regresses, opponent_model.py may have silently reverted to (or fallen "
        "below) the pre-Chunk-21 proxy-only behavior."
    )
