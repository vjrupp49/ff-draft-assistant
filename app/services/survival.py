"""
CHUNK 54 -- "likely available at pick N" board-risk estimate for the
Draft Outlook view.

DELIBERATE REUSE, NOT NEW MODELING: this Monte Carlo replays draft
trajectories forward from a state to a target pick number, sampling
EVERY intervening pick via app.services.opponent_model.sample_pick --
the exact same real-market-ADP-driven function app/services/mcts.py's
own rollouts (`_advance_opponents`) and app/services/draft_live.py's mock
driver (`_opponent_pick`) already use and that Chunks 21/32/41 built and
validated (see opponent_model.py's module docstring for the real-ADP
root-cause evidence, and docs/handoff/V4_chunks_31-.md for prior
empirical survival-rate work using this exact same sampling function).
No new probability model is introduced here.

Also mirrors mcts.py's `recommend()` precedent for how adp_ranks gets
computed: ONCE, before any picks are sampled (not refreshed pick-by-pick
the way draft_live.py's real-time board does) -- market_adp itself is
static per player regardless of drafted state, and the VBD-based
fallback proxy (only used for the ~78% of the pool with no real market
ADP entry) isn't worth refreshing thousands of times over for a
pre-draft browsing estimate.

SIMPLIFICATION, stated explicitly: every pick in the simulated window
(including picks that would fall on "my" own slot) is sampled via the
SAME opponent_model logic. This is a pre-draft BOARD-RISK browsing
estimate, not a decision recommendation (that's what /api/draft-score's
real MCTS search is for) -- before the draft has even started there is
no real signal for what "I" would actually do on my own future turns, so
this doesn't try to guess it. This means survival estimates for a pick
number deep enough that it falls after one of "my" own hypothetical
earlier picks are a rough approximation (a real me might draft
differently than the ADP+need model), which is an acceptable, explicitly
flagged limitation for a "what's likely still around" browsing tool.

NOT run inside MCTS, and deliberately NOT a fresh full MCTS search per
pick number: no tree search, no portfolio/Shapley evaluation, no
risk-adjustment -- just the cheap opponent-sampling loop already proven
out elsewhere, run standalone for `num_replays` independent trajectories.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.services.draft_state import DraftState
from app.services.opponent_model import build_adp_proxy_ranks, build_market_adp_ranks, sample_pick
from app.services.vbd import FANTASY_POSITIONS, calculate_vbd

DEFAULT_NUM_REPLAYS = 300


def estimate_survival_probabilities(
    state: DraftState,
    players_by_id: dict[str, dict[str, Any]],
    target_pick_no: int,
    num_replays: int = DEFAULT_NUM_REPLAYS,
    seed: Optional[int] = None,
) -> dict[str, float]:
    """
    Returns {player_id: P(still undrafted at target_pick_no)} for every
    player not already drafted in `state`. If target_pick_no is already
    on the clock or past (<= state.current_pick_no), this is trivial (no
    simulation needed): 1.0 for everyone undrafted, 0.0 for anyone
    already picked.
    """
    already_drafted = state.drafted_player_ids
    candidate_ids = [pid for pid in players_by_id if pid not in already_drafted]

    if target_pick_no <= state.current_pick_no:
        return {pid: 1.0 for pid in candidate_ids}

    all_players = list(players_by_id.values())
    # Computed ONCE, mirroring mcts.py's recommend() -- see module docstring.
    vbd_full = calculate_vbd(all_players, drafted_player_ids=already_drafted)
    vbd_proxy_ranks = build_adp_proxy_ranks(vbd_full)
    adp_ranks = build_market_adp_ranks(all_players, vbd_proxy_ranks)

    rng = np.random.default_rng(seed)
    num_picks_to_sim = target_pick_no - state.current_pick_no
    survive_counts = {pid: 0 for pid in candidate_ids}

    for _ in range(num_replays):
        sim_state = state.clone()
        for _ in range(num_picks_to_sim):
            available = [
                p for p in all_players
                if p["player_id"] not in sim_state.drafted_player_ids and p["position"] in FANTASY_POSITIONS
            ]
            if not available:
                break
            team_counts = sim_state.position_counts(sim_state.slot_on_the_clock_now, players_by_id)
            pick = sample_pick(rng, team_counts, available, sim_state.current_pick_no, adp_ranks)
            if pick is None:
                break
            sim_state.add_pick(pick)

        drafted_this_replay = sim_state.drafted_player_ids
        for pid in candidate_ids:
            if pid not in drafted_this_replay:
                survive_counts[pid] += 1

    return {pid: count / num_replays for pid, count in survive_counts.items()}
