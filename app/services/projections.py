"""
Baseline fantasy-point projections, built primarily from historical
nfl_data_py stats and scored using this league's actual scoring settings
(app/config.py — full PPR + TE reception premium + this league's
passing/rushing rates), with live market ADP (app/services/adp.py,
Chunk 17) now blended in for the two cases nfl_data_py's stats alone
can't handle: players with no usable history (rookies) and players whose
history reflects a team/role they've since left.

This is the "dumb but honest" baseline the later Monte Carlo / MCTS /
Shapley draft-score engine builds on top of — a per-player point estimate
*and* a spread, not just a single number.

CHUNK 16 FINDING -- WHY ADP GOT ADDED: an audit found this pipeline was
100% backward-looking with zero forward-looking signal of any kind (no
blend existed here before Chunk 17, despite some project notes implying
otherwise — see that chunk's report). Concretely: a real 2025 first-round
rookie RB (Omarion Hampton) was buried at overall rank 597/992 purely for
lacking nfl_data_py history, and a traded veteran (George Pickens, PIT ->
DAL) was silently projected 100% on his old team's stats with no flag at
all. CHUNK 17 FIX: app/services/adp.py pulls free, live ADP from
FantasyFootballCalculator (see that module for the full diagnostic —
format choice, sample size, name-matching limitations) and this module
uses it to replace the flat rookie fallback with a player-specific
market-derived estimate, and to detect + blend/flag role-change veterans.
Established veterans on the same team are deliberately left untouched —
Chunk 16 found that case was already fine, so this doesn't touch it.

FANTASYPROS_EXTENSION_POINT (still true, unrelated to Chunk 17's ADP
addition): FantasyPros' projections API requires an emailed request for a
free key (approval-gated, not instant) and isn't wired in yet for that
reason. Once a key is approved, a second projection source could still be
blended in here alongside ADP. Do not add it without flagging the
key/cost to the user first.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import nfl_data_py as nfl
import numpy as np
import pandas as pd

from app.config import SCORING
from app.services import adp
from app.services.sleeper import sleeper_client

logger = logging.getLogger("ff_draft_assistant.projections")

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}

# nflverse (nfl_data_py's data source) publishes a season's stats sometime
# after that season wraps, and this is not always in sync with "the current
# real-world year" — so we probe backward from PREFERRED_MOST_RECENT_SEASON
# rather than assuming it's published, and use whichever of the last few
# seasons actually respond, weighting the most recent one found the
# heaviest. As of building this chunk, the 2025 season was not yet
# published upstream, so 2024/2023/2022 were used — bump
# PREFERRED_MOST_RECENT_SEASON once nflverse catches up; no other code
# changes needed.
PREFERRED_MOST_RECENT_SEASON = 2025
SEASONS_TO_PROBE = 4
MAX_SEASONS_USED = 3
RECENCY_WEIGHTS = [0.5, 0.3, 0.2]  # most-recent-first; renormalized if fewer seasons found

ASSUMED_MAX_GAMES = 17  # NFL regular season length

PROJECTIONS_CACHE_PATH = "data/baseline_projections.json"
PROJECTIONS_CACHE_MAX_AGE_HOURS = 24

# Rough floor used only for players with zero usable history (rookies,
# practice-squad/limited-snap players): the Nth percentile of *scored*
# players at that position. Not a substitute for the real replacement-level
# calculation in app/services/vbd.py (which uses actual roster-slot math) —
# just keeps rookies from showing up as literal 0.0 and getting buried.
REPLACEMENT_FALLBACK_PERCENTILE = 25


class ProjectionError(RuntimeError):
    """Raised when we can't build projections at all (e.g. no data sources reachable)."""


def _score_row(row: pd.Series, position: str) -> float:
    """Fantasy points for one week/season stat row, per this league's SCORING."""
    pts = (
        row.get("passing_yards", 0) * SCORING["pass_yd"]
        + row.get("passing_tds", 0) * SCORING["pass_td"]
        + row.get("interceptions", 0) * SCORING["pass_int"]
        + row.get("rushing_yards", 0) * SCORING["rush_yd"]
        + row.get("rushing_tds", 0) * SCORING["rush_td"]
        + row.get("receptions", 0) * SCORING["rec"]
        + row.get("receiving_yards", 0) * SCORING["rec_yd"]
        + row.get("receiving_tds", 0) * SCORING["rec_td"]
    )
    if position == "TE":
        pts += row.get("receptions", 0) * SCORING["te_premium_bonus"]
    return float(pts)


def _load_sleeper_to_gsis_map() -> dict[str, str]:
    """
    Sleeper's own player payload has a `gsis_id` field, but it's frequently
    None even for established, currently-rostered players (e.g. James Cook,
    BUF's starting RB, has gsis_id=None in Sleeper's data) -- relying on it
    alone silently drops real players into the "no history" fallback path.
    nfl_data_py's `import_ids()` maintains a proper ID crosswalk across
    Sleeper/gsis/ESPN/Yahoo/etc. and is far more complete; use it as the
    primary join, with Sleeper's own field as a fallback for anyone missing
    from the crosswalk.
    """
    ids_df = nfl.import_ids()
    sub = ids_df[["sleeper_id", "gsis_id"]].dropna(subset=["sleeper_id", "gsis_id"])
    return {
        str(int(row.sleeper_id)): str(row.gsis_id).strip() for row in sub.itertuples()
    }


def _probe_available_seasons() -> dict[int, pd.DataFrame]:
    """
    Try seasons back from PREFERRED_MOST_RECENT_SEASON until MAX_SEASONS_USED
    are found. Returns {year: regular-season weekly stat rows}, most recent
    first in iteration but returned as a plain dict (caller sorts as needed).
    """
    frames: dict[int, pd.DataFrame] = {}
    for year in (PREFERRED_MOST_RECENT_SEASON - i for i in range(SEASONS_TO_PROBE)):
        try:
            df = nfl.import_weekly_data([year])
        except Exception as exc:  # nfl_data_py surfaces plain urllib HTTPError etc.
            logger.info("Season %s not available from nfl_data_py yet (%s)", year, exc)
            continue
        df = df[df["season_type"] == "REG"]
        if df.empty:
            continue
        frames[year] = df
        if len(frames) >= MAX_SEASONS_USED:
            break

    if not frames:
        raise ProjectionError(
            "No seasons of weekly data available from nfl_data_py "
            f"(tried {PREFERRED_MOST_RECENT_SEASON} down to "
            f"{PREFERRED_MOST_RECENT_SEASON - SEASONS_TO_PROBE + 1})"
        )
    return frames


def _season_player_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-player, per-season games/ppg/weekly-stddev for one season's weekly
    rows -- plus (Chunk 17) that season's LAST team ("recent_team", sorted
    by week so an in-season trade resolves to wherever the player finished
    the season), which projections.py uses downstream to detect a team
    change vs. Sleeper's current roster (role-change veteran detection,
    see build_baseline_projections).
    """
    df = df[df["position"].isin(FANTASY_POSITIONS)].copy()
    df["week_points"] = df.apply(lambda r: _score_row(r, r["position"]), axis=1)
    df = df.sort_values("week")
    grouped = (
        df.groupby(["player_id", "position", "player_display_name"])
        .agg(
            games=("week_points", "count"),
            ppg=("week_points", "mean"),
            weekly_std=("week_points", "std"),
            season_team=("recent_team", "last"),
        )
        .reset_index()
    )
    grouped["weekly_std"] = grouped["weekly_std"].fillna(0.0)  # single-game seasons -> no variance signal
    return grouped


def _combine_seasons(season_stats: dict[int, pd.DataFrame]) -> dict[str, dict]:
    """Merge per-season summaries across seasons, keyed by nfl_data_py's gsis-style player_id."""
    years_sorted = sorted(season_stats.keys(), reverse=True)
    weights = RECENCY_WEIGHTS[: len(years_sorted)]

    combined: dict[str, dict] = {}
    for year, weight in zip(years_sorted, weights):
        for _, row in season_stats[year].iterrows():
            pid = str(row["player_id"]).strip()
            entry = combined.setdefault(pid, {"position": row["position"], "name": row["player_display_name"], "seasons": {}})
            entry["seasons"][year] = {
                "weight": weight,
                "games": int(row["games"]),
                "ppg": float(row["ppg"]),
                "weekly_std": float(row["weekly_std"]),
                "team": row["season_team"] if pd.notna(row["season_team"]) else None,
            }
            if row["player_display_name"]:
                entry["name"] = row["player_display_name"]
    return combined


def _finalize_player(entry: dict) -> dict:
    """Recency-weighted point estimate + spread for one player from its combined season data."""
    seasons = entry["seasons"]
    weight_sum = sum(s["weight"] for s in seasons.values())
    norm_weights = {yr: s["weight"] / weight_sum for yr, s in seasons.items()}

    weighted_ppg = sum(norm_weights[yr] * seasons[yr]["ppg"] for yr in seasons)
    weighted_games = sum(norm_weights[yr] * seasons[yr]["games"] for yr in seasons)
    projected_games = min(ASSUMED_MAX_GAMES, round(weighted_games)) if weighted_games > 0 else 0
    projected_points = weighted_ppg * projected_games

    # Spread = within-season (week-to-week) variance blended with between-season
    # (year-to-year) variance, both recency-weighted. Not a full Bayesian
    # posterior (that's a later chunk) — just enough to know "this player's
    # estimate is shaky" vs. "this player is a metronome."
    within_season_std = sum(norm_weights[yr] * seasons[yr]["weekly_std"] for yr in seasons)
    if len(seasons) >= 2:
        between_season_var = sum(
            norm_weights[yr] * (seasons[yr]["ppg"] - weighted_ppg) ** 2 for yr in seasons
        )
        stddev_ppg = (within_season_std**2 + between_season_var) ** 0.5
    else:
        stddev_ppg = within_season_std

    # Scale a per-game stddev up to a season-total stddev assuming
    # roughly-independent game-to-game outcomes (sqrt(n) rule of thumb).
    projected_points_stddev = stddev_ppg * (projected_games**0.5) if projected_games else 0.0

    # Chunk 17: team from the MOST RECENT season used (not necessarily the
    # most heavily weighted -- most recent is what matters for detecting
    # "have they since changed teams", the question build_baseline_projections
    # asks downstream). None if that season's rows never resolved a team.
    most_recent_year = max(seasons.keys())
    most_recent_team = seasons[most_recent_year]["team"]

    return {
        "position": entry["position"],
        "name": entry["name"],
        "seasons_used": sorted(seasons.keys(), reverse=True),
        "games_by_season": {str(yr): seasons[yr]["games"] for yr in seasons},
        "projected_games": projected_games,
        "projected_ppg": round(weighted_ppg, 2),
        "projected_points": round(projected_points, 1),
        "projected_points_stddev": round(projected_points_stddev, 1),
        "low_confidence": False,
        "confidence_note": None,
        "most_recent_historical_team": most_recent_team,
    }


async def build_baseline_projections(force_refresh: bool = False) -> dict[str, Any]:
    """
    Build (or load from cache) baseline projections for every fantasy-relevant
    (QB/RB/WR/TE, currently on an NFL roster) player known to Sleeper.

    Cache lives at PROJECTIONS_CACHE_PATH and is reused for up to
    PROJECTIONS_CACHE_MAX_AGE_HOURS so a server restart doesn't force a
    recompute (nfl_data_py pulls are remote fetches + a Sleeper players pull,
    not instant).
    """
    cache_file = Path(PROJECTIONS_CACHE_PATH)
    if not force_refresh and cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < PROJECTIONS_CACHE_MAX_AGE_HOURS:
            try:
                with cache_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # fall through and rebuild on a corrupt/unreadable cache

    season_frames = _probe_available_seasons()
    season_stats = {year: _season_player_stats(df) for year, df in season_frames.items()}
    combined = _combine_seasons(season_stats)
    finalized_by_gsis = {pid: _finalize_player(entry) for pid, entry in combined.items()}

    # Sleeper is the source of truth for "who is a current, draftable NFL
    # player" (including 2025-draft-class rookies with zero nfl_data_py
    # history yet) and for the player_id used elsewhere in this app (draft
    # picks/rosters are keyed by Sleeper's player_id, not gsis_id).
    sleeper_players = await sleeper_client.get_all_players()
    sleeper_to_gsis = _load_sleeper_to_gsis_map()

    # CHUNK 17: live market ADP (app/services/adp.py) -- the forward-looking
    # signal Chunk 16 found this pipeline entirely lacked. Fetched once per
    # build (itself cached 24h, see adp.py), used below for both failure
    # modes Chunk 16 traced: rookies/thin-history players (ADP replaces the
    # flat positional-percentile fallback with a player-specific one) and
    # role-change veterans (ADP blends with their stale-context historical
    # projection once a team change is detected). A missing ADP fetch is
    # non-fatal -- this pipeline predates ADP entirely and degrades to
    # Chunk 16-era behavior (flat fallback, unflagged role-change) rather
    # than failing outright, since projections must still build even if
    # FFC is briefly unreachable.
    adp_payload: Optional[dict[str, Any]] = None
    try:
        adp_payload = await adp.fetch_adp()
    except adp.ADPError as exc:
        logger.warning("ADP fetch failed, falling back to Chunk 16-era behavior (no ADP signal): %s", exc)

    adp_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    adp_by_position: dict[str, list[dict[str, Any]]] = {}
    if adp_payload:
        adp_lookup = adp.build_adp_lookup(adp_payload)
        adp_by_position = adp.adp_ranks_by_position(adp_payload)

    def _adp_percentile_for(name: str, position: str) -> Optional[float]:
        """Looks up a player's ADP-derived percentile within their position, or None if not found in the ADP data."""
        key = (adp._normalize_name(name), position)
        ffc_player = adp_lookup.get(key)
        if ffc_player is None:
            return None
        ranked = adp_by_position.get(position, [])
        try:
            rank = next(i for i, p in enumerate(ranked, start=1) if p is ffc_player)
        except StopIteration:
            return None
        return adp.adp_percentile(rank, len(ranked))

    players_out: list[dict[str, Any]] = []
    scored_points_by_position: dict[str, list[float]] = {}

    for sleeper_pid, p in sleeper_players.items():
        position = p.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        if p.get("team") is None:
            continue  # not currently on an NFL roster (free agent/retired/etc.) -> not draft-relevant

        gsis_id = sleeper_to_gsis.get(sleeper_pid) or (p.get("gsis_id") or "").strip() or None
        hist = finalized_by_gsis.get(gsis_id) if gsis_id else None

        base = {
            "player_id": sleeper_pid,
            "gsis_id": gsis_id or None,
            "name": p.get("full_name"),
            "position": position,
            "team": p.get("team"),
        }

        if hist:
            record = {**base, **{k: v for k, v in hist.items() if k not in ("position",)}}
            record["name"] = base["name"] or hist["name"]

            # CHUNK 17: role-change detection -- Chunk 16's more dangerous
            # failure mode, because it produces a normal-looking number
            # with no flag at all. Compares Sleeper's CURRENT team (live,
            # correct) against the team from this player's MOST RECENT
            # historical season (see _finalize_player). Left untouched
            # (team_changed stays False, no ADP blend) for the "same team,
            # established veteran" case Chunk 16 found was already fine --
            # not introducing risk where there was no problem, per this
            # chunk's brief.
            historical_team = record.get("most_recent_historical_team")
            has_team_changed = adp.team_changed(historical_team, base["team"])
            record["team_changed"] = has_team_changed

            if has_team_changed:
                adp_pct = _adp_percentile_for(record["name"], position)
                if adp_pct is not None:
                    stale_points = record["projected_points"]
                    # scored_points_by_position isn't fully built yet at this
                    # point in the loop (it's populated incrementally, same
                    # as this player's own contribution below) -- fine here
                    # since adp_derived_points only needs the OTHER already-
                    # scored veterans' distribution shape, not this exact
                    # player's own value, and by the time most role-change
                    # veterans are hit there's already a healthy population
                    # (Sleeper's dict iteration order isn't position-grouped,
                    # but 100s of established players land before any given
                    # one in practice). A second pass isn't worth the added
                    # complexity for this non-degenerate a case.
                    adp_pts = adp.adp_derived_points(position, adp_pct, scored_points_by_position)
                    if adp_pts is not None:
                        blended = adp.ROLE_CHANGE_ADP_BLEND_WEIGHT * adp_pts + (1 - adp.ROLE_CHANGE_ADP_BLEND_WEIGHT) * stale_points
                        record["projected_points"] = round(blended, 1)
                        record["confidence_note"] = (
                            f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                            "usable nfl_data_py season -- historical stats reflect the OLD team/role. Blended "
                            f"{adp.ROLE_CHANGE_ADP_BLEND_WEIGHT:.0%} live market ADP-derived estimate with "
                            f"{1 - adp.ROLE_CHANGE_ADP_BLEND_WEIGHT:.0%} the stale historical projection "
                            f"({stale_points:.1f} pts pre-blend)."
                        )
                    else:
                        record["confidence_note"] = (
                            f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                            "usable nfl_data_py season, but no ADP data was available to blend -- "
                            "projected_points still reflects the OLD team/role, unadjusted."
                        )
                else:
                    record["confidence_note"] = (
                        f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                        "usable nfl_data_py season, and this player wasn't found in the live ADP data -- "
                        "projected_points still reflects the OLD team/role, unadjusted."
                    )

            scored_points_by_position.setdefault(position, []).append(record["projected_points"])
        else:
            record = {
                **base,
                "seasons_used": [],
                "games_by_season": {},
                "projected_games": None,
                "projected_ppg": None,
                "projected_points": None,  # filled in the fallback pass below
                "projected_points_stddev": None,
                "low_confidence": True,
                "team_changed": False,
                "confidence_note": (
                    "No usable prior-season stats (rookie or very limited "
                    "snaps) — projected_points is a replacement-level "
                    f"fallback (position's {REPLACEMENT_FALLBACK_PERCENTILE}th "
                    "percentile among scored players), not a real projection."
                ),
            }

        players_out.append(record)

    fallback_by_position = {
        pos: float(np.percentile(pts, REPLACEMENT_FALLBACK_PERCENTILE))
        for pos, pts in scored_points_by_position.items()
        if pts
    }
    for record in players_out:
        if record["low_confidence"]:
            # CHUNK 17: prefer a live-ADP-derived, player-specific estimate
            # over the old flat positional-percentile fallback -- this is
            # the fix for Chunk 16's rookie/thin-history finding (a real
            # starting-caliber rookie buried at replacement level
            # regardless of actual market opinion). Falls back to the
            # original flat percentile only if this player has no ADP
            # entry either (still-obscure depth players).
            adp_pct = _adp_percentile_for(record["name"], record["position"])
            adp_pts = adp.adp_derived_points(record["position"], adp_pct, scored_points_by_position) if adp_pct is not None else None
            if adp_pts is not None:
                record["projected_points"] = round(adp_pts, 1)
                # Tighter than the flat-fallback band below -- a real market
                # percentile is more informative than "we genuinely don't
                # know", though still wider than an established player's
                # real multi-season spread (see adp.py's ROLE_CHANGE_ADP_BLEND_WEIGHT
                # docstring for the equivalent judgment call on the blend side).
                record["projected_points_stddev"] = round(adp_pts * 0.35, 1)
                record["confidence_note"] = (
                    "No usable prior-season stats (rookie or very limited snaps) — projected_points is derived "
                    f"from this player's live market ADP percentile ({adp_pct:.0f}th among {record['position']}s) "
                    "mapped onto the real scored-player distribution at that position, not a flat fallback."
                )
            else:
                fallback = fallback_by_position.get(record["position"], 0.0)
                record["projected_points"] = round(fallback, 1)
                # Wide, arbitrary uncertainty band (50% of the fallback estimate) —
                # we genuinely don't know, and this should read as "wide" relative
                # to a real multi-season player's spread.
                record["projected_points_stddev"] = round(fallback * 0.5, 1)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seasons_used": sorted(season_frames.keys(), reverse=True),
        "recency_weights": RECENCY_WEIGHTS[: len(season_frames)],
        "num_players": len(players_out),
        "players": players_out,
    }

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f)

    return payload
