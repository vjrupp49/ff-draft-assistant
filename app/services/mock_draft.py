"""
Full 15-round, 10-team mock draft simulation harness -- Chunk 9's two big
questions before any UI gets built: (A) does the system hold up across a
REAL full draft, not just isolated round-3/round-5 snapshots, and (B)
does the full Draft Score engine actually produce a better final roster
than simpler baselines, tested rigorously rather than assumed?

This is a verification tool, not a new modeling component. "My" team's
picks call the REAL scoring services directly (mcts.py/vbd.py -- the same
code /api/draft-score and /api/mcts/recommend call, not a mock/stub of
them), and the other 9 teams' picks reuse the REAL opponent_model.py
policy, unchanged, for all three strategy variants below -- so the
opponent behavior itself is never the variable under test.

THREE STRATEGIES FOR "MY" TEAM:

1. "draft_score" -- the full pipeline: MCTS (which already incorporates
   simulation + Markowitz risk-adjustment + lineup-awareness in its
   reward, see mcts.py/portfolio.py) picks the top-ranked candidate each
   turn. This is the thing actually being tested.
2. "vbd_only" -- app.services.vbd's replacement-level-adjusted VBD score,
   always take the single best available player. Position/scarcity-aware
   (it already knows this league's SUPER_FLEX/no-dedicated-TE structure
   via vbd.py's starter-allocation logic) but with none of MCTS's
   opponent-aware lookahead, portfolio risk-adjustment, or
   correlation/lineup reasoning. The "smart baseline."
3. "adp_only" -- ranks by RAW projected_points only, always take the
   single best available player. Deliberately NOT the same as
   opponent_model.py's own ADP signal (CHUNK 21: real market ADP where
   available, this league's own VBD-derived proxy as fallback -- using
   either here would make this baseline too close to strategy 2 and
   defeat the comparison). Raw points, with no awareness AT ALL of this
   league's replacement-level scarcity or SUPER_FLEX format, is a
   reasonable stand-in for what a generic, format-blind market-consensus
   ADP would actually produce for a league this unusual -- a genuinely
   "naive" baseline, not just a slightly-worse version of strategy 2.

OPPONENT MODEL SEEDING: each of the three strategy variants for a given
"opponent_seed" gets a FRESH np.random.default_rng(opponent_seed) --
i.e. the same underlying random-number stream feeds every opponent
decision across all three drafts. This does NOT guarantee the other 9
teams draft identically across the three variants (it can't: once "my"
team's own picks diverge between strategies, the pool of players actually
available to each opponent decision diverges too, which is the CORRECT,
expected behavior of a real simulation, not a bug) -- it only removes
*extra*, unrelated randomness from the comparison, so the strategy under
test is the only deliberately-introduced variable.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np

from app.config import NUM_DRAFT_ROUNDS, NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services import opponent_model
from app.services import vbd as vbd_service
from app.services.draft_state import DraftState

STRATEGIES = ("draft_score", "vbd_only", "adp_only")

# MCTS defaults (ITERATIONS=150, ROLLOUT_SIM_COUNT=300) at 15 "my" picks per
# draft x N seeds is affordable (see this chunk's measured timing) -- left
# at the real system's defaults rather than weakened for the harness, so
# Task 1's timing numbers describe genuine draft-day performance, not an
# artificially cheapened stand-in. Override via `mcts_iterations` only if
# a future run of this harness needs to trade accuracy for speed.


def _available_players(players_by_id: dict[str, dict[str, Any]], drafted: set[str]) -> list[dict[str, Any]]:
    return [p for pid, p in players_by_id.items() if pid not in drafted and p.get("position") in vbd_service.FANTASY_POSITIONS]


def _pick_draft_score(
    draft_state: DraftState, players_by_id: dict[str, dict[str, Any]], mcts_iterations: int, seed: Optional[int]
) -> tuple[str, float]:
    # CHUNK 37 FIX: was top_n=1, which silently disabled the Chunk 24
    # ADP-margin tie-break and Chunk 26 adaptive-resolution logic -- both
    # only operate on the already-truncated `top_results` list inside
    # mcts.recommend(), so a length-1 list can never contain 2+ "tied"
    # candidates for either mechanism to act on. Production's real
    # live-draft path (app/services/draft_score_engine.py) was never
    # affected -- it calls recommend(top_n=candidate_breadth), matched
    # here exactly (same constant, not just a coincidentally similar
    # value) so this harness's "draft_score" strategy reflects the same
    # decision logic a real draft actually uses. Root-caused in Chunk 36
    # (found while instrumenting a seed-3 5-QB anomaly); verified there
    # that the fix changes individual seeds' picks but washes out at the
    # 5-seed aggregate median -- re-verified formally, not just assumed,
    # in this chunk's own report.
    t0 = time.perf_counter()
    result = mcts_service.recommend(
        draft_state, players_by_id, top_n=mcts_service.CANDIDATE_BREADTH, iterations=mcts_iterations, seed=seed
    )
    elapsed = time.perf_counter() - t0
    if result["recommendations"]:
        return result["recommendations"][0]["player_id"], elapsed
    # Defensive fallback (shouldn't happen -- candidates_considered would be
    # empty only if the available pool itself were empty): fall back to VBD.
    pid, _ = _pick_vbd_only(draft_state, players_by_id)
    return pid, elapsed


def _pick_vbd_only(draft_state: DraftState, players_by_id: dict[str, dict[str, Any]]) -> tuple[str, float]:
    t0 = time.perf_counter()
    ranked = vbd_service.calculate_vbd(list(players_by_id.values()), drafted_player_ids=draft_state.drafted_player_ids)
    elapsed = time.perf_counter() - t0
    return ranked[0]["player_id"], elapsed


def _pick_adp_only(draft_state: DraftState, players_by_id: dict[str, dict[str, Any]]) -> tuple[str, float]:
    t0 = time.perf_counter()
    available = _available_players(players_by_id, draft_state.drafted_player_ids)
    best = max(available, key=lambda p: p["projected_points"])
    elapsed = time.perf_counter() - t0
    return best["player_id"], elapsed


def _opponent_pick(draft_state: DraftState, players_by_id: dict[str, dict[str, Any]], rng: np.random.Generator) -> Optional[str]:
    """One opponent team's pick, via the real opponent_model.py policy (unchanged across all 3 strategies)."""
    vbd_ranked = vbd_service.calculate_vbd(list(players_by_id.values()), drafted_player_ids=draft_state.drafted_player_ids)
    # CHUNK 21: real market ADP is now the primary opponent-timing signal,
    # VBD-proxy rank kept only as a fallback -- see opponent_model.py.
    vbd_proxy_ranks = opponent_model.build_adp_proxy_ranks(vbd_ranked)
    adp_ranks = opponent_model.build_market_adp_ranks(list(players_by_id.values()), vbd_proxy_ranks)
    available = _available_players(players_by_id, draft_state.drafted_player_ids)
    team_counts = draft_state.position_counts(draft_state.slot_on_the_clock_now, players_by_id)
    return opponent_model.sample_pick(rng, team_counts, available, draft_state.current_pick_no, adp_ranks)


def run_mock_draft(
    my_slot: int,
    strategy: str,
    opponent_seed: int,
    players_by_id: dict[str, dict[str, Any]],
    num_teams: int = NUM_TEAMS,
    num_rounds: int = NUM_DRAFT_ROUNDS,
    mcts_iterations: int = mcts_service.ITERATIONS,
) -> dict[str, Any]:
    """
    Simulates one complete `num_rounds`-round, `num_teams`-team snake
    draft. "My" team (draft slot `my_slot`) picks using `strategy`; every
    other team picks via the real opponent_model.py policy, seeded from
    `opponent_seed`.

    Returns {my_roster_ids, pick_log (timing + player per MY pick),
    all_picks (full draft history), strategy, opponent_seed}.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}', must be one of {STRATEGIES}")

    draft_state = DraftState(my_slot=my_slot, num_teams=num_teams, roster_positions=list(ROSTER_POSITIONS))
    opponent_rng = np.random.default_rng(opponent_seed)
    total_picks = num_teams * num_rounds

    pick_log: list[dict[str, Any]] = []
    all_picks: list[dict[str, Any]] = []

    for _ in range(total_picks):
        if draft_state.is_my_turn:
            if strategy == "draft_score":
                pid, elapsed = _pick_draft_score(draft_state, players_by_id, mcts_iterations, seed=opponent_seed)
            elif strategy == "vbd_only":
                pid, elapsed = _pick_vbd_only(draft_state, players_by_id)
            else:  # adp_only
                pid, elapsed = _pick_adp_only(draft_state, players_by_id)

            pick_log.append(
                {
                    "pick_no": draft_state.current_pick_no,
                    "round": draft_state.current_round,
                    "player_id": pid,
                    "name": players_by_id.get(pid, {}).get("name"),
                    "position": players_by_id.get(pid, {}).get("position"),
                    "elapsed_seconds": round(elapsed, 4),
                }
            )
        else:
            pid = _opponent_pick(draft_state, players_by_id, opponent_rng)
            if pid is None:
                break  # pool exhausted -- shouldn't happen at 150 picks out of ~980 players

        all_picks.append(
            {
                "pick_no": draft_state.current_pick_no,
                "slot": draft_state.slot_on_the_clock_now,
                "player_id": pid,
                "name": players_by_id.get(pid, {}).get("name"),
                "position": players_by_id.get(pid, {}).get("position"),
            }
        )
        draft_state.add_pick(pid)

    return {
        "strategy": strategy,
        "opponent_seed": opponent_seed,
        "my_slot": my_slot,
        "my_roster_ids": draft_state.roster_player_ids(),
        "pick_log": pick_log,
        "all_picks": all_picks,
        "total_picks_made": len(draft_state.picks),
    }
