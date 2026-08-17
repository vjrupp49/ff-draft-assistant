"""
Monte Carlo season simulation at the PLAYER level -- the outcome-space
input MCTS (a later chunk) will search over, instead of a single point
estimate.

SCOPE (deliberately bounded -- read this before touching the file):
This simulates each player's own weekly scoring variance and sums it to a
season total, with a lightweight shared "team game script" correlation
between same-team skill players. It does NOT model a schedule, opponent
rosters, weekly matchup resolution, win/loss records, or playoff seeding --
that's a separate, later "playoff odds simulator" (Phase 2). If this file
grows a notion of "Team A plays Team B in week N," that's scope creep --
stop and simplify back to this file's actual job: player/roster outcome
*distributions*, not matchup outcomes.

DISTRIBUTION CHOICE: weekly fantasy points are simulated as log-normal
draws, moment-matched to each player's (weekly mean, weekly stddev) from
app/services/projections.py. Log-normal over a plain Normal because:
  - it's naturally non-negative -- a plain Normal with realistic fantasy
    variance regularly samples negative weeks, which a rostered skill
    player essentially never produces (a real bad week has a hard floor
    near zero; it can't go equally far below the mean the way a boom week
    can go above it)
  - it's right-skewed, matching the actual shape of weekly fantasy scoring
    (a "boom" week can be 3x a player's mean; the downside is bounded)
  - log-space shocks combine additively, which makes injecting a shared
    correlated component simple (see below) without needing a full copula

CORRELATION SIMPLIFICATION (documented -- revisit in Phase 1.5, per the
roadmap's copula item): each player's week-to-week log-space variance is
split into a team-shared component and an individual component via
TEAM_CORRELATION. Same-team players draw the SAME shared shock each
simulated week, so a QB and his own team's WR1 boom and bust together more
often than two unrelated players would. This is a shared-multiplier model,
not a full copula across arbitrary player pairs -- it doesn't model e.g.
negative correlation between a team's two competing RBs splitting touches,
or cross-team correlation from a shootout. That's out of scope here.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.services.projections import ASSUMED_MAX_GAMES

logger = logging.getLogger("ff_draft_assistant.simulation")

DEFAULT_NUM_SIMS = 1000

# Fraction of a player's weekly log-space variance attributed to a shared
# team-level "game script" shock vs. their own idiosyncratic variance.
# 0 = fully independent players (no correlation benefit/cost from
# stacking), 1 = a team's skill players move in lockstep. 0.30 is a
# judgment call, not a fitted number -- documented as a simplification to
# revisit once real weekly data can calibrate it.
TEAM_CORRELATION = 0.30

# Floor to avoid log(0)/degenerate draws for near-zero projections
# (shouldn't happen for real projections, only a defensive minimum).
MIN_WEEKLY_MEAN = 0.5

SIM_CACHE_PATH = Path("data/player_simulations.json")
SIM_CACHE_MAX_AGE_HOURS = 24
DEFAULT_SEED = 42  # reproducible by default; callers can override per-request


def _weekly_mean_stddev(player: dict[str, Any]) -> tuple[float, float, int]:
    """
    Derive (weekly_mean, weekly_stddev, games) for a player from its
    baseline projection record.

    projections.py stores a season-TOTAL stddev (scaled up from a weekly
    figure by sqrt(games), assuming roughly-independent games -- see that
    module's docstring); this inverts that scaling back to a per-week
    figure so we can draw week-by-week. Falls back to ASSUMED_MAX_GAMES for
    players with no games-played info (e.g. low_confidence/rookie records).
    """
    games = player.get("projected_games") or ASSUMED_MAX_GAMES
    games = max(int(games), 1)

    ppg = player.get("projected_ppg")
    if ppg is None:
        total_points = player.get("projected_points") or 0.0
        ppg = total_points / games

    season_stddev = player.get("projected_points_stddev")
    if season_stddev:
        weekly_stddev = season_stddev / (games**0.5)
    else:
        # Only hit if a record is missing spread info entirely (shouldn't
        # happen for real projections) -- assume a moderate 35% CV rather
        # than treating the player as risk-free.
        weekly_stddev = ppg * 0.35

    return max(ppg, MIN_WEEKLY_MEAN), max(weekly_stddev, 0.01), games


def _lognormal_params(weekly_mean: float, weekly_stddev: float) -> tuple[float, float]:
    """Method-of-moments (mu_ln, sigma_ln) so exp(Normal(mu_ln, sigma_ln^2)) has the target mean/stddev."""
    cv = weekly_stddev / weekly_mean
    sigma_ln_sq = np.log(1 + cv**2)
    mu_ln = np.log(weekly_mean) - 0.5 * sigma_ln_sq
    return mu_ln, sigma_ln_sq**0.5


def simulate_players(
    players: list[dict[str, Any]],
    num_sims: int = DEFAULT_NUM_SIMS,
    seed: int | None = DEFAULT_SEED,
) -> dict[str, np.ndarray]:
    """
    Simulate `num_sims` season totals for every player in `players`
    SIMULTANEOUSLY, in one rng context, so correlated same-team draws line
    up across players within a given simulation run -- this is what lets a
    roster-level sum (done by the caller) actually reflect correlation,
    not just concatenate independent player distributions.

    Returns {player_id: season_totals} where season_totals is a NumPy
    array of shape (num_sims,).
    """
    rng = np.random.default_rng(seed)

    by_team: dict[str, list[dict[str, Any]]] = {}
    for p in players:
        team_key = p.get("team") or f"__no_team_{p['player_id']}"
        by_team.setdefault(team_key, []).append(p)

    season_totals: dict[str, np.ndarray] = {}

    for team_key, team_players in by_team.items():
        max_games = max(_weekly_mean_stddev(p)[2] for p in team_players)
        # One shared UNIT (mean 0, sigma 1) team shock per (sim, week),
        # reused by every player on this team -- each player below scales
        # it by their own sigma_ln_shared, since players can have
        # different total variance.
        team_shock_units = rng.standard_normal((num_sims, max_games))

        for p in team_players:
            weekly_mean, weekly_stddev, games = _weekly_mean_stddev(p)
            mu_ln, sigma_ln_total = _lognormal_params(weekly_mean, weekly_stddev)
            sigma_ln_shared = sigma_ln_total * (TEAM_CORRELATION**0.5)
            sigma_ln_idio = sigma_ln_total * ((1 - TEAM_CORRELATION) ** 0.5)

            shared_component = team_shock_units[:, :games] * sigma_ln_shared
            idio_component = rng.standard_normal((num_sims, games)) * sigma_ln_idio

            weekly_log_scores = mu_ln + shared_component + idio_component
            weekly_scores = np.exp(weekly_log_scores)

            season_totals[p["player_id"]] = weekly_scores.sum(axis=1)

    return season_totals


def _summarize(season_totals: np.ndarray) -> dict[str, float]:
    return {
        "mean": round(float(np.mean(season_totals)), 1),
        "median": round(float(np.median(season_totals)), 1),
        "stddev": round(float(np.std(season_totals)), 1),
        "p5": round(float(np.percentile(season_totals, 5)), 1),
        "p95": round(float(np.percentile(season_totals, 95)), 1),
        "min": round(float(np.min(season_totals)), 1),
        "max": round(float(np.max(season_totals)), 1),
    }


def _signature(weekly_mean: float, weekly_stddev: float, games: int, num_sims: int, seed: int | None) -> str:
    """Cache-invalidation key: changes if the underlying projection or sim params change."""
    return f"{weekly_mean:.4f}|{weekly_stddev:.4f}|{games}|{num_sims}|{seed}"


def _load_sim_cache() -> dict[str, Any]:
    if not SIM_CACHE_PATH.exists():
        return {}
    try:
        age_hours = (time.time() - SIM_CACHE_PATH.stat().st_mtime) / 3600
        if age_hours >= SIM_CACHE_MAX_AGE_HOURS:
            return {}
        with SIM_CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sim_cache(cache: dict[str, Any]) -> None:
    SIM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SIM_CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f)


def simulate_player_summary(
    player: dict[str, Any],
    num_sims: int = DEFAULT_NUM_SIMS,
    seed: int | None = DEFAULT_SEED,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Simulated season-outcome summary for a single player, cached to
    SIM_CACHE_PATH (a single player's own simulation is cheap, but this
    keeps repeated hits to the same player's endpoint instant and avoids
    silently drifting seeds across calls). Cache entries are invalidated
    automatically if the player's underlying projection (mean/stddev/games)
    or sim params change -- see `_signature`.

    A single-player simulation has no teammates in play, so
    TEAM_CORRELATION has no visible effect here -- correlation only shows
    up when simulating a roster (see `simulate_roster_summary`).
    """
    player_id = player["player_id"]
    weekly_mean, weekly_stddev, games = _weekly_mean_stddev(player)
    signature = _signature(weekly_mean, weekly_stddev, games, num_sims, seed)

    cache = _load_sim_cache()
    cached_entry = cache.get(player_id)
    if not force_refresh and cached_entry and cached_entry.get("signature") == signature:
        return cached_entry["summary"]

    season_totals = simulate_players([player], num_sims=num_sims, seed=seed)[player_id]
    summary = _summarize(season_totals)

    cache[player_id] = {
        "signature": signature,
        "generated_at": time.time(),
        "num_sims": num_sims,
        "summary": summary,
    }
    _save_sim_cache(cache)

    return summary


def simulate_roster_summary(
    roster_players: list[dict[str, Any]],
    num_sims: int = DEFAULT_NUM_SIMS,
    seed: int | None = DEFAULT_SEED,
) -> dict[str, Any]:
    """
    Simulated season-outcome summary for a candidate roster (sum of its
    players' correlated weekly draws). Not cached -- the space of possible
    rosters is combinatorially large, so this is computed fresh per call;
    the underlying draws are cheap enough (num_sims x games x roster_size
    lognormal samples) to not need it for v1.

    Returns the roster-level summary plus each player's own individual
    summary (drawn from the SAME correlated simulation run, not a separate
    call) so a caller can see how much of the roster's spread is
    attributable to which player.
    """
    if not roster_players:
        return {
            "roster": _summarize(np.zeros(num_sims)),
            "players": {},
            "num_sims": num_sims,
            "team_correlation": TEAM_CORRELATION,
        }

    per_player_totals = simulate_players(roster_players, num_sims=num_sims, seed=seed)
    roster_totals = np.sum(list(per_player_totals.values()), axis=0)

    return {
        "roster": _summarize(roster_totals),
        "players": {
            p["player_id"]: {
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                **_summarize(per_player_totals[p["player_id"]]),
            }
            for p in roster_players
        },
        "num_sims": num_sims,
        "team_correlation": TEAM_CORRELATION,
    }
