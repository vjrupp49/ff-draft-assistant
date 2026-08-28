"""
CHUNK 56 -- shared "which Sleeper roster is mine" resolution.

CONTEXT: Chunk 55's lineup optimizer surfaced a real gap -- this codebase
has never tracked which Sleeper roster_id/owner_id belongs to Vincent
within a given league (draft_state.py's own docstring is explicit that
draft SLOT, not Sleeper roster_id/user_id, is how "mine" is tracked
everywhere else -- that mechanism only exists during an active draft).
Chunk 55 worked around this for its one endpoint with an explicit
roster_id parameter. This module solves it ONCE, as reusable
infrastructure, so Chunk 57 (Trade Suggester's real value engine),
Chunk 58 (Waiver Suggester), and a future League Dashboard don't each
re-solve the same problem.

MY_SLEEPER_USER_ID: Vincent's Sleeper account user_id, confirmed Chunk
51 when league 2 was discovered via the live API. The SAME account
across every league he's in, so this is one module-level constant, not
a per-league field on app.leagues.LeagueConfig (which would just
duplicate the identical value twice).

VERIFIED DIRECTLY (Chunk 56, not assumed): this user_id resolves to
roster_id=7 in Kiddos (owner display_name "vjrupp4949", team "Dom") and
roster_id=8 in Former Bradley Bums (same display_name) -- confirmed via
a live, read-only call against both real leagues.

CACHING: a small in-memory, per-process dict keyed by league_key. One
read-only Sleeper API call (get_rosters) per league is enough to resolve
this, and the answer doesn't change once a league's rosters exist
(Sleeper allocates roster_id/owner_id pairings at league creation, not
at draft time) -- so there's no reason to re-fetch on every call.
`force_refresh` bypasses the cache for the rare case a league gets
reset/recreated. This is intentionally NOT a disk cache (unlike
players_cache.json etc): the value is tiny, per-process-cheap to
re-derive, and doesn't need to survive a restart the way a
network-heavy fetch does.
"""

from __future__ import annotations

from typing import Any, Optional

from app.leagues import LeagueConfig
from app.services.sleeper import sleeper_client

MY_SLEEPER_USER_ID = "1131040333669957632"  # Chunk 51 -- Vincent's Sleeper account, same for every league

_my_roster_id_cache: dict[str, Optional[int]] = {}


async def resolve_my_roster_id(
    league: LeagueConfig,
    force_refresh: bool = False,
    rosters: Optional[list[dict[str, Any]]] = None,
) -> Optional[int]:
    """
    Returns the Sleeper roster_id owned by MY_SLEEPER_USER_ID within
    `league`, or None if no roster in this league is owned by that
    user_id (a real, surfaced None -- not expected for either real
    league, confirmed directly, but not silently defaulted to
    anything if a live league ever doesn't have a match).

    `rosters`: pass an already-fetched roster list (e.g. from
    `get_rosters_with_mine_flag`) to avoid a second read-only API call
    when the caller already has one. Fetched fresh otherwise.
    """
    if not force_refresh and league.key in _my_roster_id_cache:
        return _my_roster_id_cache[league.key]

    if rosters is None:
        rosters = await sleeper_client.get_rosters(league.league_id)

    roster_id = next((r.get("roster_id") for r in rosters if r.get("owner_id") == MY_SLEEPER_USER_ID), None)
    _my_roster_id_cache[league.key] = roster_id
    return roster_id


async def get_rosters_with_mine_flag(
    league: LeagueConfig, force_refresh_my_roster_id: bool = False
) -> tuple[list[dict[str, Any]], Optional[int]]:
    """
    One read-only get_rosters() call, annotated with `is_mine` on each
    roster dict plus the resolved my_roster_id -- the shared building
    block app/routers/rosters.py (the roster browser) and
    app/routers/lineup.py (Chunk 55, updated this chunk) both use, so
    "which roster is mine" is solved in exactly one place.
    """
    rosters = await sleeper_client.get_rosters(league.league_id)
    my_roster_id = await resolve_my_roster_id(league, force_refresh=force_refresh_my_roster_id, rosters=rosters)
    for r in rosters:
        r["is_mine"] = r.get("roster_id") == my_roster_id
    return rosters, my_roster_id
