"""
Live market ADP (Average Draft Position) from FantasyFootballCalculator's
free, public REST API -- https://fantasyfootballcalculator.com/api/v1/adp/
Chunk 17's fix for the gap Chunk 16 found: the baseline projection pipeline
(projections.py) is 100% backward-looking (nfl_data_py historical stats
only, see that module) with zero forward-looking signal, which silently
buries real starting-caliber rookies at replacement level and leaves
role-change veterans projected 100% on stale, wrong-team history. ADP is
a real market's forward-looking consensus -- this module turns that rank
signal into something the existing points-based VBD pipeline can use.

ATTRIBUTION (per FantasyFootballCalculator's own terms -- free for
personal/commercial use, attribution requested, and "please do not call
this API too frequently"): ADP data provided by FantasyFootballCalculator
(https://fantasyfootballcalculator.com), free ADP REST API, no key
required. See https://help.fantasyfootballcalculator.com/article/42-adp-rest-api

FORMAT DECISION (Chunk 17 Task 1 diagnostic -- verified live, not assumed):
this league is true SUPERFLEX (an optional flex-eligible QB slot). FFC's
API does NOT offer a "superflex" format -- confirmed directly, requesting
it returns {"status": "Error", "errors": ["Invalid format"]}. The closest
available option is "2qb" (MANDATORY 2-QB, a genuinely different format --
every team must roster/start 2 QBs, vs. SUPERFLEX's optional single flex
slot that could go to a QB or a non-QB). Chosen anyway, as an explicitly
documented approximation, not a silent equivalence: "2qb" inflates QB
value somewhat MORE than true SUPERFLEX would (mandatory vs. optional
demand), but this league's entire QB-valuation history (Chunks 9/10/13 --
a real QB glut, then a real QB shortage, both root-caused and fixed) shows
under-pricing QB scarcity is the costlier mistake to repeat here, not
over-pricing it slightly. Plain "ppr" (1-QB assumption) was rejected
despite its larger sample (5,614 drafts vs. "2qb"'s 3,066) specifically
because it would reintroduce exactly the wrong bias at the position this
project has spent the most effort getting right. ADP_FORMAT is a module
constant specifically so this choice is easy to revisit if FFC ever adds
a real superflex format.

SAMPLE SIZE (verified live, Chunk 17 Task 1): 3,066 total "2qb"-format
drafts as of this writing, spanning the current draft season window --
not thin. The 4 players Chunk 16 traced as broken (Omarion Hampton,
George Pickens, Kenneth Walker III, Rico Dowdle) were all present with
ADP values that correctly reflect their CURRENT team/role (e.g. Pickens
shows team=DAL, not the stale PIT his nfl_data_py history is stuck on) --
direct evidence this data actually solves the problem it's being used for,
not just a plausible-sounding source added on faith.

NAME MATCHING (a real, documented limitation, not glossed over): FFC's
API has no shared ID space with Sleeper/gsis (its own `player_id` is
FFC-internal). Matching is by normalized name + position -- lowercased,
suffixes (Jr/Sr/II/III/IV) and periods stripped on both sides, since FFC
formats suffixes inconsistently with Sleeper (e.g. FFC's "Kenneth Walker"
vs. a differently-suffixed Sleeper name would otherwise silently miss).
This is inherently imperfect: a genuine name collision at the same
position (two same-name players) would misattribute an ADP value, though
this is rare enough at the top of any position's draft board to not be a
practical concern for the players this module actually changes behavior
for (see projections.py's usage). Unmatched players simply have no ADP
signal available and fall back to prior behavior -- never a hard failure.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import numpy as np

from app.config import NUM_TEAMS

logger = logging.getLogger("ff_draft_assistant.adp")

ADP_API_BASE = "https://fantasyfootballcalculator.com/api/v1/adp"
ADP_FORMAT = "2qb"  # closest available proxy for true SUPERFLEX -- see module docstring
ADP_YEAR = 2026

ADP_CACHE_PATH = "data/adp_cache.json"
# FFC's own guidance: "the data only updates once per day" and "please do
# not call this API too frequently" -- reusing projections.py's existing
# 24h TTL pattern is a direct match to that cadence, not an arbitrary
# choice.
ADP_CACHE_MAX_AGE_HOURS = 24

_REQUEST_TIMEOUT_SECONDS = 15.0

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)


class ADPError(RuntimeError):
    """Raised when the ADP API can't be reached and no usable cache exists."""


def _normalize_name(name: str) -> str:
    """Lowercase, drop periods/apostrophes, strip a trailing generational suffix -- see module docstring's NAME MATCHING note."""
    n = name.lower().replace(".", "").replace("'", "")
    n = _SUFFIX_RE.sub("", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n


async def fetch_adp(
    fmt: str = ADP_FORMAT,
    teams: int = NUM_TEAMS,
    year: int = ADP_YEAR,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Returns the raw FFC ADP payload ({"status", "meta", "players": [...]}),
    cached to ADP_CACHE_PATH for up to ADP_CACHE_MAX_AGE_HOURS -- see
    module docstring for why that TTL matches FFC's own update cadence.
    """
    cache_file = Path(ADP_CACHE_PATH)
    if not force_refresh and cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < ADP_CACHE_MAX_AGE_HOURS:
            try:
                with cache_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # fall through and re-fetch on a corrupt/unreadable cache

    url = f"{ADP_API_BASE}/{fmt}?teams={teams}&year={year}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        if cache_file.exists():
            logger.warning("ADP fetch failed (%s); falling back to stale cache", exc)
            with cache_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        raise ADPError(f"Could not fetch ADP from {url} and no cache exists: {exc}") from exc

    if payload.get("status") != "Success":
        raise ADPError(f"FFC ADP API returned an error: {payload.get('errors')}")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f)
    return payload


def build_adp_lookup(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """
    {(normalized_name, position): ffc_player_record} -- keyed by name+position
    (see module docstring's NAME MATCHING note for why position is included
    as a collision guard).
    """
    return {(_normalize_name(p["name"]), p["position"]): p for p in payload.get("players", [])}


def adp_ranks_by_position(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """{position: [ffc_player_records sorted by adp ascending (best first)]}."""
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for p in payload.get("players", []):
        by_pos.setdefault(p["position"], []).append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: p["adp"])
    return by_pos


def adp_percentile(rank_within_position: int, n_at_position: int) -> float:
    """
    Converts a 1-indexed ADP rank (1 = best) among `n_at_position` same-
    position players into a percentile in [0, 100], 100 = best. rank=1 ->
    100, rank=n_at_position -> 0, linear in between. Degenerates to 50.0
    if there's only one player at the position in the ADP pool (nothing
    to rank against).
    """
    if n_at_position <= 1:
        return 50.0
    return 100.0 * (1 - (rank_within_position - 1) / (n_at_position - 1))


# How much of a role-change veteran's projection comes from the ADP-derived
# (forward-looking, knows about the new team) estimate vs. their existing
# stale-context historical projection -- see projections.py's usage and
# Chunk 17's report for the reasoning: leans toward trusting the signal
# that actually knows about the change, without fully discarding the
# player's proven underlying talent level. A documented judgment call
# (project convention -- see portfolio.py's BENCH_DISCOUNT_BASE for the
# same pattern), not fit to data.
ROLE_CHANGE_ADP_BLEND_WEIGHT = 0.65


def team_changed(historical_team: Optional[str], current_team: Optional[str]) -> bool:
    """
    True only when BOTH teams are known and they differ -- a missing
    historical team (some seasons never resolve one, see projections.py's
    _season_player_stats) or missing current team means "we can't tell",
    which this treats as "no change detected" rather than a false
    positive. Pulled out as its own pure function (used by
    projections.py's build_baseline_projections) specifically so it's
    unit-testable without needing the full async pipeline.
    """
    return bool(historical_team and current_team and historical_team != current_team)


def adp_derived_points(
    position: str,
    adp_pct: float,
    scored_points_by_position: dict[str, list[float]],
) -> Optional[float]:
    """
    Maps an ADP percentile onto the EXISTING positional scoring
    distribution already computed from real nfl_data_py-scored players at
    that position -- the same np.percentile mechanism
    projections.py's flat REPLACEMENT_FALLBACK_PERCENTILE already used,
    just driven by a player-specific, real-market percentile instead of
    one flat number for every low-confidence player regardless of actual
    market opinion. Returns None if there's no scored population at this
    position to map onto (shouldn't happen in practice -- QB/RB/WR/TE all
    have plenty of scored veterans -- but fail soft rather than crash).
    """
    pts = scored_points_by_position.get(position)
    if not pts:
        return None
    return float(np.percentile(pts, adp_pct))
