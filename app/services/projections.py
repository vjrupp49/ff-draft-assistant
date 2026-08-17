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

CHUNK 21 ADDITION -- `market_adp`/`market_adp_stdev` ON EVERY PLAYER:
Chunks 17/18 only ever called `_find_adp_match` for the two point-estimate
cases above (low_confidence rookies, team_changed veterans) -- established
veterans never got their real ADP looked up or stored anywhere, because
nothing needed it yet. Chunk 21 found a second, genuinely different
consumer for the SAME already-fetched FFC data: app/services/opponent_model.py's
"will this player still be there next turn" pick-timing model, which was
using a self-referential VBD-based rank as an ADP PROXY instead (see that
module's own former docstring) -- confirmed, via a live-draft replay, to be
a ~4x worse predictor of real opponent pick timing than this same real ADP
data already being fetched right here. This loop attaches the raw
`adp`/`stdev` fields to EVERY player (reusing the exact same
adp_lookup/adp_by_position/_find_adp_match built above -- no new fetch, no
duplicated matching logic), purely additive: it does not touch
projected_points for anyone, including the two cases above.
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

# CHUNK 26: kept as a tuple (not a `set`), matching vbd.py's own constant
# of the same name -- see that module's comment for why order matters for
# a sibling constant (SUPER_FLEX_ELIGIBLE) with the exact same hash-
# randomization risk; harmless here since both usages are membership tests,
# but there's no reason for this and vbd.py's copy to differ in kind.
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")

# nflverse publishes a season's stats sometime after that season wraps, and
# this is not always in sync with "the current real-world year" — so we
# probe backward from PREFERRED_MOST_RECENT_SEASON rather than assuming
# it's published, and use whichever of the last few seasons actually
# respond, weighting the most recent one found the heaviest. Bump
# PREFERRED_MOST_RECENT_SEASON once a new season wraps; no other code
# changes needed.
#
# CHUNK 30 FIX -- STALE DATA SOURCE, ROOT-CAUSED (Chunk 29) AND FIXED: this
# module used to call nfl_data_py's `import_weekly_data`, which fetches
# from nflverse-data's "player_stats" GitHub release. That release's last
# asset is player_stats_2024.parquet (published May 2025) -- nflverse
# rebuilt their entire stats pipeline in 2025 (new schema, confirmed via a
# direct diff against the old one -- see _fetch_weekly_stats below) and
# moved it to a NEW release, "stats_player", which nfl_data_py 0.3.3 (the
# latest release on PyPI) was never updated to point at. Confirmed directly
# via nfl_data_py's own GitHub issues (#140, #144, both closed) that the
# maintainers consider this permanent, not a lag -- they explicitly
# recommend `nflreadpy` (their newer successor package) instead of a patch
# to this one. This meant every projection for every established veteran
# was silently stuck on data up to 2 real seasons stale, with ZERO
# visibility into anything that happened since (e.g. Alvin Kamara's and
# James Conner's real 2025 season-ending knee injuries, confirmed directly
# via nfl_data_py's own -- still-working -- `import_injuries` endpoint,
# were completely invisible to this pipeline before this fix).
#
# FIX CHOICE (nflreadpy vs. a direct fetch against the new release,
# evaluated before picking): nflreadpy's own PyPI listing marks it
# "Lifecycle: experimental", and its primary dependency is `polars`, not
# pandas (pandas support is an optional extra) -- adopting it would add six
# new transitive dependencies (polars, pydantic, pydantic-settings, tqdm,
# platformdirs, requests) for a young, still-changing package, in a project
# that has otherwise stayed deliberately dependency-light. A direct fetch
# against nflverse's new, CONFIRMED-current release URL needs zero new
# dependencies (pandas + fastparquet are already installed, transitively
# via nfl_data_py, which is kept for `import_ids()` -- unaffected by this
# migration, verified directly) and the actual schema change is small and
# fully audited (see _fetch_weekly_stats). The tradeoff, named honestly:
# we now own noticing if nflverse renames things again, rather than
# outsourcing that to a maintained package -- an acceptable trade given
# this fix doubles as the exact runbook for detecting and re-fixing that
# if it recurs.
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


# CHUNK 30: nflverse's CURRENT weekly player-stats release (superseding
# nfl_data_py's dead "player_stats" release -- see the CHUNK 30 FIX note
# above PREFERRED_MOST_RECENT_SEASON). Same asset-per-year layout
# nfl_data_py's own `import_weekly_data` used internally, just pointed at
# the release nflverse actually maintains now.
WEEKLY_STATS_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.parquet"

# CHUNK 30: the only columns this module actually reads (_score_row,
# _season_player_stats) that nflverse renamed in the 2025 schema rewrite --
# confirmed by diffing the full old-release (2024) vs new-release (2025)
# column sets directly, not assumed from the GitHub issue thread alone.
# `dakota` was also renamed (-> passing_cpoe) but is never read here, so
# it's intentionally left out of this map. Remaps INCOMING columns back to
# the names the rest of this module already expects, so _score_row/
# _season_player_stats need no changes at all.
WEEKLY_STATS_COLUMN_REMAP = {
    "team": "recent_team",
    "passing_interceptions": "interceptions",
}


def _fetch_weekly_stats(year: int) -> pd.DataFrame:
    """Fetches one season's weekly player stats directly from nflverse's
    current release (see CHUNK 30 FIX note above), remapped to the column
    names this module's existing processing functions expect."""
    df = pd.read_parquet(WEEKLY_STATS_URL_TEMPLATE.format(year=year), engine="auto")
    return df.rename(columns=WEEKLY_STATS_COLUMN_REMAP)


def _probe_available_seasons() -> dict[int, pd.DataFrame]:
    """
    Try seasons back from PREFERRED_MOST_RECENT_SEASON until MAX_SEASONS_USED
    are found. Returns {year: regular-season weekly stat rows}, most recent
    first in iteration but returned as a plain dict (caller sorts as needed).
    """
    frames: dict[int, pd.DataFrame] = {}
    for year in (PREFERRED_MOST_RECENT_SEASON - i for i in range(SEASONS_TO_PROBE)):
        try:
            df = _fetch_weekly_stats(year)
        except Exception as exc:  # HTTP errors, missing-asset, etc.
            logger.info("Season %s not available yet (%s)", year, exc)
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

    # CHUNK 18: a second, deeper-sample fallback dataset (ADP_FALLBACK_FORMAT,
    # "ppr") -- recovers real, evidenced false negatives the primary "2qb"
    # format's smaller sample misses (see adp.py's CHUNK 18 AUDIT note for
    # the concrete Conner/Hockenson case that motivated this). Optional --
    # None here just means fewer recovered matches, not a broken pipeline.
    adp_fallback_payload = await adp.fetch_fallback_adp() if adp_payload else None

    adp_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    adp_by_position: dict[str, list[dict[str, Any]]] = {}
    adp_fallback_lookup: Optional[dict[tuple[str, str], dict[str, Any]]] = None
    adp_fallback_by_position: Optional[dict[str, list[dict[str, Any]]]] = None
    if adp_payload:
        adp_lookup = adp.build_adp_lookup(adp_payload)
        adp_by_position = adp.adp_ranks_by_position(adp_payload)
    if adp_fallback_payload:
        adp_fallback_lookup = adp.build_adp_lookup(adp_fallback_payload)
        adp_fallback_by_position = adp.adp_ranks_by_position(adp_fallback_payload)

    def _find_adp_match(name: str, position: str) -> Optional[dict[str, Any]]:
        """
        Looks up a player's ADP match (primary "2qb" first, "ppr" fallback
        second -- see adp.find_adp_match), returning the full match info
        (record/source/percentile) so callers can also check team
        agreement (Chunk 18 hardening) rather than just a bare percentile.
        """
        return adp.find_adp_match(name, position, adp_lookup, adp_by_position, adp_fallback_lookup, adp_fallback_by_position)

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
                match = _find_adp_match(record["name"], position)
                if match is not None:
                    # CHUNK 18 hardening: surface (never silently discard --
                    # a stale FFC entry right after a very recent trade is
                    # plausible and the match is still likely correct) a
                    # disagreement between Sleeper's live team and FFC's
                    # reported team for this match. Chunk 18's full-pool
                    # audit found zero real instances of this; it's a
                    # forward-looking safety net, not a fix to an observed
                    # failure -- see adp.py's team_agrees docstring.
                    ffc_team_agrees = adp.team_agrees(base["team"], match["record"].get("team"))
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
                    adp_pts = adp.adp_derived_points(position, match["percentile"], scored_points_by_position)
                    if adp_pts is not None:
                        blended = adp.ROLE_CHANGE_ADP_BLEND_WEIGHT * adp_pts + (1 - adp.ROLE_CHANGE_ADP_BLEND_WEIGHT) * stale_points
                        record["projected_points"] = round(blended, 1)
                        source_note = "" if match["source"] == "primary" else f" (via {adp.ADP_FALLBACK_FORMAT}-format fallback -- not found in {adp.ADP_FORMAT})"
                        team_note = (
                            "" if ffc_team_agrees else
                            f" CAUTION: ADP source reports team={match['record'].get('team')}, disagreeing with "
                            f"Sleeper's team={base['team']} -- verify this is the same player, not a name collision."
                        )
                        record["confidence_note"] = (
                            f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                            "usable nfl_data_py season -- historical stats reflect the OLD team/role. Blended "
                            f"{adp.ROLE_CHANGE_ADP_BLEND_WEIGHT:.0%} live market ADP-derived estimate{source_note} with "
                            f"{1 - adp.ROLE_CHANGE_ADP_BLEND_WEIGHT:.0%} the stale historical projection "
                            f"({stale_points:.1f} pts pre-blend).{team_note}"
                        )
                        record["adp_team_agrees"] = ffc_team_agrees
                    else:
                        record["confidence_note"] = (
                            f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                            "usable nfl_data_py season, but no ADP data was available to blend -- "
                            "projected_points still reflects the OLD team/role, unadjusted."
                        )
                else:
                    record["confidence_note"] = (
                        f"Team changed ({historical_team} -> {base['team']}) since this player's most recent "
                        "usable nfl_data_py season, and this player wasn't found in the live ADP data (checked "
                        f"both {adp.ADP_FORMAT} and {adp.ADP_FALLBACK_FORMAT} formats) -- "
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
            match = _find_adp_match(record["name"], record["position"])
            adp_pts = adp.adp_derived_points(record["position"], match["percentile"], scored_points_by_position) if match is not None else None
            if adp_pts is not None:
                record["projected_points"] = round(adp_pts, 1)
                # Tighter than the flat-fallback band below -- a real market
                # percentile is more informative than "we genuinely don't
                # know", though still wider than an established player's
                # real multi-season spread (see adp.py's ROLE_CHANGE_ADP_BLEND_WEIGHT
                # docstring for the equivalent judgment call on the blend side).
                record["projected_points_stddev"] = round(adp_pts * 0.35, 1)
                # CHUNK 18 hardening: same team-agreement surfacing as the
                # role-change path (see that block's comment) -- checked
                # against this player's current Sleeper team, since a
                # rookie has no historical team to compare against.
                ffc_team_agrees = adp.team_agrees(record["team"], match["record"].get("team"))
                source_note = "" if match["source"] == "primary" else f" (via {adp.ADP_FALLBACK_FORMAT}-format fallback -- not found in {adp.ADP_FORMAT})"
                team_note = (
                    "" if ffc_team_agrees else
                    f" CAUTION: ADP source reports team={match['record'].get('team')}, disagreeing with "
                    f"Sleeper's team={record['team']} -- verify this is the same player, not a name collision."
                )
                record["adp_team_agrees"] = ffc_team_agrees
                record["confidence_note"] = (
                    "No usable prior-season stats (rookie or very limited snaps) — projected_points is derived "
                    f"from this player's live market ADP percentile ({match['percentile']:.0f}th among {record['position']}s)"
                    f"{source_note} mapped onto the real scored-player distribution at that position, "
                    f"not a flat fallback.{team_note}"
                )
            else:
                fallback = fallback_by_position.get(record["position"], 0.0)
                record["projected_points"] = round(fallback, 1)
                # Wide, arbitrary uncertainty band (50% of the fallback estimate) —
                # we genuinely don't know, and this should read as "wide" relative
                # to a real multi-season player's spread.
                record["projected_points_stddev"] = round(fallback * 0.5, 1)

    # CHUNK 21: attach real market ADP to EVERY player (not just the
    # low_confidence/team_changed subsets handled above) -- see the module
    # docstring's CHUNK 21 ADDITION note. Reuses the same lookup/closure
    # built above; None for the ~78% of the pool the real ADP market
    # doesn't track at all (see opponent_model.py's build_market_adp_ranks
    # for how that's handled downstream).
    for record in players_out:
        market_match = _find_adp_match(record["name"], record["position"])
        record["market_adp"] = market_match["record"]["adp"] if market_match else None
        record["market_adp_stdev"] = market_match["record"].get("stdev") if market_match else None

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
