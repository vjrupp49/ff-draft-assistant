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

CHUNK 18 AUDIT + HARDENING (full-pool, not a handful of examples --
confirmed directly, not assumed): ran this module's actual matching
logic across the real ~992-player Sleeper pool against the real live
"2qb" dataset. Results:
  - Match rate: 188/992 Sleeper players (19.0%) found a match -- expected
    to be low, since most of the 992 include deep bench/practice-squad
    players nobody drafts at all, not a red flag by itself. 188/220 FFC
    entries (85.5%) matched back to a Sleeper player.
  - Structural collision check: ZERO (name, position) keys collided
    between two different real players on EITHER side of the join --
    directly rules out the "two people, one ADP slot" mechanism this
    audit was most worried about, for the CURRENT real NFL player pool
    (a snapshot-in-time fact, not a permanent guarantee -- see
    team_agrees below for the ongoing safety net).
  - Task 2 (false positives -- the dangerous case): ZERO team
    mismatches across all 188 matched pairs (Sleeper's live current
    team vs. FFC's reported team agreed every single time), even though
    team was NOT used as part of the match criteria at the time of this
    audit. Strong, independent evidence the name-based matching isn't
    silently misattributing players -- not proof it never could, but no
    observed failures across the full real pool.
  - Task 3 (false negatives): 40 real, fantasy-relevant players
    (generously thresholded, e.g. James Conner at 218.8 proj points, a
    real starting RB1) had NO match in "2qb" at all. Root-caused, not
    assumed: "2qb"'s ADP range tops out around pick 174 (its total_drafts,
    3,066, is meaningfully smaller than "ppr"'s 5,614) -- it simply
    doesn't have the sample depth "ppr" does. Spot-checked directly: of 7
    sample misses, "ppr" recovered 2 (James Conner ADP=171.5, T.J.
    Hockenson ADP=154.1); the other 5 (Njoku, Fields, Engram, Kmet,
    Freiermuth) were absent from BOTH datasets -- real committee/depth-
    chart uncertainty the market itself hasn't consolidated around yet,
    not a bug to fix here.

HARDENING IMPLEMENTED (scoped to what the audit evidence actually
supports, not a speculative rewrite):
  1. ADP_FALLBACK_FORMAT ("ppr") + build_layered_adp_lookup / find_adp_match:
     recovers real, evidenced false negatives like the Conner/Hockenson
     case above. "2qb" (this league's actual format approximation) always
     wins when both datasets have an entry -- the fallback only fires
     when the primary format has none.
  2. team_agrees(): a forward-looking safety net for the exact risk this
     chunk's brief calls out (a wrong player silently matched, no flag) --
     NOT a fix to an observed failure (Task 2 found zero), but a
     near-zero-cost defensive check now that a SECOND, less-curated
     fallback dataset is also in play. projections.py surfaces a
     disagreement in confidence_note rather than silently discarding the
     match (a stale FFC entry post-trade is plausible and shouldn't just
     get thrown away), matching this chunk's "flag, don't blindly reject"
     guidance.
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
ADP_FALLBACK_FORMAT = "ppr"  # Chunk 18: deeper sample, recovers real "2qb"-only-missing false negatives -- see module docstring
ADP_YEAR = 2026

ADP_CACHE_PATH = "data/adp_cache.json"
ADP_FALLBACK_CACHE_PATH = "data/adp_fallback_cache.json"
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
    cache_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Returns the raw FFC ADP payload ({"status", "meta", "players": [...]}),
    cached to `cache_path` (defaults to ADP_CACHE_PATH, the primary-format
    cache) for up to ADP_CACHE_MAX_AGE_HOURS -- see module docstring for
    why that TTL matches FFC's own update cadence. `cache_path` is
    parameterized (not hardcoded to ADP_CACHE_PATH) so the Chunk 18
    fallback fetch (a different format, "ppr") gets its own cache file
    rather than colliding with the primary "2qb" one.

    `cache_path` defaults to None (resolved to the CURRENT value of
    module-level ADP_CACHE_PATH inside the function body), not directly
    to ADP_CACHE_PATH as the parameter default -- a default bound at
    function-definition time would freeze in the value ADP_CACHE_PATH had
    at import time, silently ignoring any later `monkeypatch.setattr(adp,
    "ADP_CACHE_PATH", ...)` (exactly what tests/test_adp_integration.py's
    isolated_adp_cache fixture does -- found this the hard way when
    adding this parameter broke that pre-existing test).
    """
    cache_file = Path(cache_path if cache_path is not None else ADP_CACHE_PATH)
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


async def fetch_fallback_adp(force_refresh: bool = False) -> Optional[dict[str, Any]]:
    """
    Chunk 18: fetches ADP_FALLBACK_FORMAT ("ppr") for the deeper-sample
    false-negative recovery described in the module docstring. Returns
    None (not raises) on failure -- the fallback is explicitly optional;
    losing it just means fewer recovered matches, not a broken pipeline.
    """
    try:
        return await fetch_adp(fmt=ADP_FALLBACK_FORMAT, force_refresh=force_refresh, cache_path=ADP_FALLBACK_CACHE_PATH)
    except ADPError as exc:
        logger.warning("ADP fallback (%s) fetch failed, continuing without it: %s", ADP_FALLBACK_FORMAT, exc)
        return None


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


# CHUNK 31 FIX: nfl_data_py's historical stats (both the original dead
# release AND Chunk 30's current replacement -- checked directly, still
# "LA") use "LA" for the Rams; Sleeper's live player data (this function's
# `current_team` argument) uses "LAR". A naive string comparison flagged
# EVERY current Rams player as team_changed=True -- confirmed directly
# during Chunk 29's sanity check (Puka Nacua, Matthew Stafford, Kyren
# Williams all showed "Team changed (LA -> LAR)" despite never leaving the
# team), and this was the single largest contributor to an implausible
# ~24% (240/992) team_changed rate. Checked for other aliasing pairs the
# same way (diffing the FULL abbreviation sets both nfl_data_py's current
# source and Sleeper actually use): LA/LAR is the only mismatch found --
# every other team abbreviation matches exactly on both sides. Separately
# confirmed `team_agrees()` below (Sleeper vs FFC's ADP data) is NOT at
# equivalent risk -- FFC already uses "LAR", matching Sleeper.
TEAM_ABBREVIATION_ALIASES = {"LA": "LAR"}


def _normalize_team(team: Optional[str]) -> Optional[str]:
    """Canonicalizes a team abbreviation before comparison -- see
    TEAM_ABBREVIATION_ALIASES above for the one confirmed real-world case."""
    if team is None:
        return None
    return TEAM_ABBREVIATION_ALIASES.get(team, team)


def team_changed(historical_team: Optional[str], current_team: Optional[str]) -> bool:
    """
    True only when BOTH teams are known and they differ -- a missing
    historical team (some seasons never resolve one, see projections.py's
    _season_player_stats) or missing current team means "we can't tell",
    which this treats as "no change detected" rather than a false
    positive. Pulled out as its own pure function (used by
    projections.py's build_baseline_projections) specifically so it's
    unit-testable without needing the full async pipeline.

    CHUNK 31: both sides are normalized via _normalize_team before
    comparing, so a real team's OWN differing abbreviation conventions
    across data sources (see TEAM_ABBREVIATION_ALIASES) doesn't read as a
    trade.
    """
    historical_team = _normalize_team(historical_team)
    current_team = _normalize_team(current_team)
    return bool(historical_team and current_team and historical_team != current_team)


def team_agrees(sleeper_team: Optional[str], ffc_team: Optional[str]) -> bool:
    """
    Chunk 18 hardening -- see module docstring's TEAM AGREEMENT note.
    True when both teams are known and match, OR when either side is
    unknown (can't tell, not a disagreement). False is the "suspicious,
    surface it" signal: Chunk 18's full-pool audit found zero real
    instances of this firing, so it's a forward-looking safety net for
    the exact "wrong player silently matched" risk this project's brief
    calls out, not a fix to an observed failure.
    """
    if not sleeper_team or not ffc_team:
        return True
    return sleeper_team == ffc_team


def find_adp_match(
    name: str,
    position: str,
    primary_lookup: dict[tuple[str, str], dict[str, Any]],
    primary_by_position: dict[str, list[dict[str, Any]]],
    fallback_lookup: Optional[dict[tuple[str, str], dict[str, Any]]] = None,
    fallback_by_position: Optional[dict[str, list[dict[str, Any]]]] = None,
) -> Optional[dict[str, Any]]:
    """
    Chunk 18: looks up a player in the primary (ADP_FORMAT, "2qb") ADP
    data first, falling back to ADP_FALLBACK_FORMAT ("ppr") only if the
    primary has no entry -- see module docstring for the evidenced
    false-negative gap this recovers (e.g. James Conner, T.J. Hockenson).
    "2qb" always wins when both have an entry, since it's this league's
    actual format approximation (see ADP_FORMAT's own reasoning).

    Returns None if not found in either, else
    {"record": ffc_player_record, "source": "primary"|"fallback",
     "percentile": float in [0,100]}.
    """
    key = (_normalize_name(name), position)
    sources = [(primary_lookup, primary_by_position, "primary")]
    if fallback_lookup is not None:
        sources.append((fallback_lookup, fallback_by_position or {}, "fallback"))

    for lookup, by_position, source in sources:
        record = lookup.get(key)
        if record is None:
            continue
        ranked = by_position.get(position, [])
        try:
            rank = next(i for i, p in enumerate(ranked, start=1) if p is record)
        except StopIteration:
            continue  # shouldn't happen (record came from this same lookup) -- fail soft, try next source
        return {"record": record, "source": source, "percentile": adp_percentile(rank, len(ranked))}
    return None


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
