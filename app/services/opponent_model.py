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

ADP DATA SOURCE (CHUNK 21 -- superseded from the original VBD-proxy
design; see below): app/services/adp.py now pulls real, free, live ADP
from FantasyFootballCalculator (added in Chunk 17 for a different
consumer -- projections.py's point estimates). `build_market_adp_ranks`
below is the PRIMARY signal this module now uses: `projections.py`
attaches each player's real `market_adp` (Chunk 21 addition, reusing the
exact same fetch/matching infra, no duplication) directly onto their
record, and this module just reads it. This directly replaces the
ORIGINAL design (kept below, now used only as an explicit FALLBACK for
the ~78% of the player pool the real ADP market doesn't track at all --
see build_market_adp_ranks):

ORIGINAL DESIGN, CHUNKS 1-20 (retained as `build_adp_proxy_ranks`, now a
fallback, not the primary signal): nfl_data_py has no fantasy-ADP
endpoint (`import_draft_picks`/`import_draft_values` are the NFL *entry*
draft, unrelated to fantasy draft ADP), and at the time this was written
no free fantasy ADP source had been integrated yet -- so this used our
own VBD ranking (app/services/vbd.py) as an ADP PROXY: a player's rank by
VBD under this league's actual scoring/roster stood in for "consensus ADP
rank."

CHUNK 21 ROOT CAUSE -- WHY THE PROXY HAD TO GO (confirmed via a live
150-pick real-draft replay, not assumed): the VBD proxy is a genuinely
poor predictor of when real human opponents actually draft a player --
median distance from the real pick_no was 37 ranks for the VBD proxy vs.
10.5 PICKS for real market ADP (real ADP was the closer predictor in
114/133 = 85.7% of real opponent picks tested). This under-modeled
survival probability is what let a player recommended by this app
sometimes reach dramatically ahead of real market ADP (wasting draft
capital an opponent was never going to force anyway -- e.g. a real Chunk
19 pick of Travis Kelce 85 picks before his real ADP) and sometimes
recommended a player with literally NO real-market ADP entry (functionally
never drafted by real opponents) without any special "safe to leave"
signal to reflect that. The VBD proxy's own real advantage -- it's scored
under this league's exact PPR/TE-premium/SUPER_FLEX rules, where generic
market ADP would misprice QBs for this format -- is why it's kept as the
fallback rather than deleted outright, for the large slice of the pool
real ADP has no opinion on at all.

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
    1-indexed, best player = rank 1 -- our ORIGINAL ADP proxy, now used only
    as `build_market_adp_ranks`'s fallback for players real ADP doesn't
    cover -- see the CHUNK 21 note in the module docstring for why.
    """
    return {p["player_id"]: i + 1 for i, p in enumerate(vbd_ranked_players)}


def build_market_adp_ranks(
    players: list[dict[str, Any]],
    vbd_proxy_ranks: dict[str, int],
) -> dict[str, float]:
    """
    CHUNK 21 -- the new PRIMARY signal this module uses for "when will this
    player actually get picked": each player's real market ADP
    (`market_adp`, attached by projections.py -- see that module's CHUNK 21
    ADDITION note; reuses Chunks 17/18's FantasyFootballCalculator fetch
    and matching, no duplicated logic), falling back to the original
    VBD-based proxy rank (`build_adp_proxy_ranks`) only for players the
    real ADP market has no opinion on at all (Chunk 21 Task 2's audit:
    218/992 players in the real pool had a market match -- the other ~78%,
    almost entirely deep bench/practice-squad-tier players nobody
    realistically drafts, still need SOME signal to rank against each
    other and against positional need).

    Both units are already directly comparable without rescaling: real
    `market_adp` is this league's actual average overall pick number
    (adp.py fetches ADP_FORMAT scaled to app.config.NUM_TEAMS already), and
    the VBD-proxy rank is a 1-indexed ordinal over the same scored-player
    pool -- both are "pick order," just from two different sources, so
    mixing them in one dict (real ADP where we have it, proxy rank where
    we don't) needs no unit conversion for `_adp_fit`'s Gaussian below to
    keep behaving sensibly for both.
    """
    ranks: dict[str, float] = {}
    for p in players:
        pid = p["player_id"]
        market_adp = p.get("market_adp")
        ranks[pid] = float(market_adp) if market_adp is not None else float(vbd_proxy_ranks.get(pid, 10**9))
    return ranks


def _adp_fit(adp_rank: float, pick_no: int, sigma: float = ADP_SIGMA) -> float:
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
    adp_rank_by_player: dict[str, float],
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
    adp_rank_by_player: dict[str, float],
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
