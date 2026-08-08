"""
Placeholder opponent-pick model, used by mcts.py to simulate what OTHER
teams do during a rollout.

This is a documented cold-start placeholder (per the project roadmap):
no real behavioral data exists yet for this league's actual drafters.
Phase 1.5 replaces the internals of THIS module with learned per-drafter
tendencies once real draft/season history exists -- draft_state.py and
mcts.py should never need to change when that happens, they only depend on
`pick_probabilities` / `sample_pick`'s signatures, not how the
probabilities are computed.

ADP DATA SOURCE: nfl_data_py has no fantasy-ADP endpoint (`import_draft_picks`
/ `import_draft_values` are the NFL *entry* draft, unrelated to fantasy
draft ADP) and we're not adding a paid ADP API. Instead this uses our own
VBD ranking (app/services/vbd.py) as an ADP PROXY: a player's rank by VBD
under this league's actual scoring/roster stands in for "consensus ADP
rank." This is a real simplification worth naming -- true market ADP
reflects hype/recency effects (rookie buzz, a big preseason game) that a
pure projection-value rank doesn't capture -- but it has one advantage over
generic external ADP: it's already scored under this league's specific
rules (PPR + TE premium + SUPER_FLEX), where generic 1-QB-league market
ADP would misprice QBs for this format anyway.

MODEL: P(team drafts player) is proportional to
    adp_fit(player, pick_no) * positional_need(team, player.position)
- adp_fit peaks when the player's ADP-proxy rank is close to the current
  overall pick number, decaying with distance (teams reach/fall from ADP,
  but rarely by a lot) -- a Gaussian-shaped decay, width ADP_SIGMA.
- positional_need boosts players at positions a team is thin on relative
  to a rough target roster composition, and suppresses (but never fully
  zeroes) positions a team has already over-filled.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

import numpy as np

# How many ADP-proxy ranks a pick can plausibly "reach" or "fall" and still
# get non-negligible probability. Smaller = opponents hew closer to ADP;
# larger = more randomness. A judgment call, not fitted to data.
ADP_SIGMA = 6.0

# Only players within this many ADP-proxy ranks of the current pick are
# considered at all (everyone else's weight would round to ~0 anyway given
# ADP_SIGMA) -- keeps opponent sampling fast during MCTS rollouts instead of
# scoring the entire remaining player pool on every simulated pick.
ADP_WINDOW = 40

# Rough judgment-call target roster composition by the end of a 15-round
# SUPER_FLEX/FLEX-heavy draft (this league has no dedicated TE slot at all,
# 3x FLEX, 1x SUPER_FLEX -- see app/config.py). Not derived from
# roster_positions programmatically because "how many bench RBs is enough"
# is a preference call, not a hard constraint -- documented here as a
# placeholder alongside the rest of this module's placeholder status.
TARGET_ROSTER_COUNTS = {"QB": 2, "RB": 5, "WR": 6, "TE": 2}

NEED_BOOST_STRENGTH = 2.0  # how strongly an unfilled need multiplies pick probability
OVERFILL_PENALTY = 0.25  # how strongly probability decays per player past target at a position
MIN_MULTIPLIER = 0.15  # a position is suppressed once overfull, never driven to exactly 0


def build_adp_proxy_ranks(vbd_ranked_players: list[dict[str, Any]]) -> dict[str, int]:
    """
    `vbd_ranked_players`: players already sorted descending by VBD (as
    returned by app.services.vbd.calculate_vbd). Returns {player_id: rank},
    1-indexed, best player = rank 1 -- our ADP proxy.
    """
    return {p["player_id"]: i + 1 for i, p in enumerate(vbd_ranked_players)}


def _adp_fit(adp_rank: int, pick_no: int, sigma: float = ADP_SIGMA) -> float:
    return float(np.exp(-0.5 * ((adp_rank - pick_no) / sigma) ** 2))


def _positional_need_multiplier(position: str, current_count: int) -> float:
    target = TARGET_ROSTER_COUNTS.get(position, 3)
    if current_count >= target:
        overfill = current_count - target
        return max(MIN_MULTIPLIER, 1.0 - OVERFILL_PENALTY * overfill)
    need_fraction = (target - current_count) / target
    return 1.0 + NEED_BOOST_STRENGTH * need_fraction


def pick_probabilities(
    team_position_counts: Counter,
    available_players: list[dict[str, Any]],
    pick_no: int,
    adp_rank_by_player: dict[str, int],
) -> dict[str, float]:
    """
    Returns {player_id: probability} over `available_players` for what a
    modeled opponent (with `team_position_counts` already drafted) picks
    at `pick_no`. Restricts consideration to players within ADP_WINDOW of
    pick_no for speed (see module docstring) before scoring/normalizing.
    """
    windowed = [
        p for p in available_players
        if abs(adp_rank_by_player.get(p["player_id"], 10**9) - pick_no) <= ADP_WINDOW
    ]
    if not windowed:
        # Nobody left near this pick's ADP window (e.g. very deep in a
        # thin remaining pool) -- fall back to the full available pool
        # rather than returning an empty distribution.
        windowed = available_players
    if not windowed:
        return {}

    weights: dict[str, float] = {}
    for p in windowed:
        adp_rank = adp_rank_by_player.get(p["player_id"], pick_no + ADP_WINDOW)
        w = _adp_fit(adp_rank, pick_no) * _positional_need_multiplier(
            p["position"], team_position_counts.get(p["position"], 0)
        )
        weights[p["player_id"]] = w

    total = sum(weights.values())
    if total <= 0:
        # Degenerate case (shouldn't happen given MIN_MULTIPLIER > 0 and
        # adp_fit > 0 everywhere) -- fall back to uniform over the window.
        n = len(windowed)
        return {p["player_id"]: 1.0 / n for p in windowed}

    return {pid: w / total for pid, w in weights.items()}


def sample_pick(
    rng: np.random.Generator,
    team_position_counts: Counter,
    available_players: list[dict[str, Any]],
    pick_no: int,
    adp_rank_by_player: dict[str, int],
) -> Optional[str]:
    """Samples one player_id per `pick_probabilities`'s distribution. None if no players available."""
    if not available_players:
        return None
    probs = pick_probabilities(team_position_counts, available_players, pick_no, adp_rank_by_player)
    if not probs:
        return None
    player_ids = list(probs.keys())
    p = np.array([probs[pid] for pid in player_ids])
    p = p / p.sum()  # guard against float drift
    return str(rng.choice(player_ids, p=p))
