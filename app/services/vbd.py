"""
Value-Based Drafting (VBD/VORP) engine for this league's actual roster
structure (app/config.py ROSTER_POSITIONS -- the corrected override, not
Sleeper's stale reported roster).

Replacement level is computed by simulating which players would actually be
rostered as starters given this league's real slot structure (10 teams,
1 QB + 2 RB + 2 WR dedicated, 3 FLEX (RB/WR/TE-eligible), 1 SUPER_FLEX
(QB/RB/WR/TE-eligible), 0 dedicated TE slot), rather than assuming a
textbook 1-QB league's replacement ranks:

  1. Fill each position's dedicated (non-flex) slots first, across all
     teams, with the top projected players at that position. (TE has no
     dedicated slot in this league, so this step seats 0 TEs.)
  2. Fill all FLEX + SUPER_FLEX slots together as ONE combined greedy pass
     over every remaining player (any position), best-points-first, capped
     so at most `super_flex_slots` of the picks are QBs (a QB can only ever
     occupy a SUPER_FLEX slot, never a plain FLEX slot; RB/WR/TE fit
     either, so which specific slot type they land in doesn't affect total
     value and isn't tracked separately). Filling SUPER_FLEX and FLEX as
     two *separate* passes (SUPER_FLEX first) was tried and rejected here --
     it systematically under-fills QBs whenever a handful of elite leftover
     non-QBs outscore the marginal backup QB (and in this league *every*
     TE is "leftover", since there's no dedicated TE slot at all) grab the
     SUPER_FLEX slots first, starving out backup QBs that could have used
     those same slots while the non-QBs would have been just as happy in a
     plain FLEX slot. Combining both slot types into one pass with only the
     QB cap as a constraint is the value-maximizing assignment (this is a
     partition-matroid: independent sets are exactly "≤ super_flex_slots
     QBs, ≤ flex_slots + super_flex_slots total" -- greedy-by-value is
     provably optimal for that structure).
  3. Replacement level for a position = the projected points of the best
     remaining (non-started) player at that position after steps 1-2 --
     i.e. the best player still on the wire once every team's starting
     lineup is accounted for.

This lets QB replacement level land wherever the real point distribution
plus SUPER_FLEX demand actually puts it (in practice, close to ~2 QBs/team
worth of demand, since QB is usually the highest-value use of a SUPER_FLEX
slot in this scoring system) rather than hardcoding that assumption -- it
falls out of the simulation instead of being baked in.

Designed to be called again mid-draft with a `drafted_player_ids` set to
recalculate replacement level against the shrinking remaining player pool.
A full "scarcity as live decay function" model -- factoring in which
specific roster slots are already filled on which teams, not just which
players are gone -- is a later chunk; this is deliberately structured so
that upgrade is additive rather than a rewrite (swap what feeds
`drafted_player_ids` / add a per-team slot-tracking layer on top).

ALSO EXPORTED: `allocate_roster_starters`, which reuses this exact same
allocation algorithm (see `_allocate_starters`) to answer a different but
closely related question -- not "which players are startable somewhere
across the whole league" (used above for replacement level), but "which
of THIS ONE roster's own players occupy ITS starting lineup." Chunk 6
added this: app/services/portfolio.py's roster valuation had no concept
of a starting lineup at all (it summed every rostered player's simulated
points equally), so Shapley attribution built on top of it couldn't see
real positional need (a same-value player joining an already-deep
position scored the same as one filling a real starting gap). Reusing
this module's already-solved SUPER_FLEX/FLEX allocation logic -- rather
than reimplementing a second copy of it -- is exactly what
`_allocate_starters` being factored out as a shared core (parameterized by
how many slots to fill, not hardcoded to league-wide demand) makes
possible.

CHUNK 20 ADDITION -- `allocate_roster_starters_with_flex_ranks`: a real
live draft (Chunk 19) found that being classified "starter" via the
shared FLEX+SUPER_FLEX pool carries ZERO signal about how many
SAME-POSITION teammates are ALSO sharing that same small pool of slots --
a roster with 4 TEs each individually "starting" in that pool is treated
identically to one with 4 different positions each holding one slot, even
though the former is a much less diversified, riskier construction.
Confirmed this is NOT a league-wide replacement-level problem (Task 1 of
that chunk's investigation found QB/TE replacement levels correctly
reflect this league's real SUPER_FLEX/TE-premium scoring, not an error)
-- it's specifically a ROSTER-level gap, so this addition only affects
`allocate_roster_starters`'s callers (portfolio.py/shapley.py/mcts.py),
never `compute_replacement_levels`'s league-wide math above.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.config import NUM_TEAMS, ROSTER_POSITIONS

# CHUNK 26 FIX: these MUST be an ordered collection (tuple), not a `set`.
# Discovered via Chunk 26's own validation work: `_allocate_starters`'s
# `combined_pool` is built by iterating SUPER_FLEX_ELIGIBLE, then
# STABLE-sorted by projected_points -- any players tied EXACTLY on
# projected_points (real, not rare -- e.g. ADP-percentile-derived
# rookie/fallback estimates) have their relative order (and therefore
# which one gets a flex slot vs becomes "replacement level") decided by
# which position was iterated first, which for a `set` of strings is
# HASH-RANDOMIZED per Python process (PYTHONHASHSEED), not tied to
# `recommend()`'s own `seed` parameter at all. Confirmed directly: the
# exact same real draft state + seed=1 produced measurably different VBD
# scores (e.g. Brock Bowers 195.3 vs 209.2) and different MCTS top picks
# across separate process runs with PYTHONHASHSEED unset, and became
# perfectly reproducible once these became tuples. This is the same class
# of bug Chunk 15 fixed ("the same seed never meant the same run") via a
# different mechanism Chunk 15's own within-one-process testing could
# never have caught. Membership tests (`x in FANTASY_POSITIONS`) and
# iteration both work identically on a tuple; no other set-specific
# operation (union/intersection/etc) is used anywhere on these.
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")
SUPER_FLEX_ELIGIBLE = ("QB", "RB", "WR", "TE")


def _slot_counts() -> dict[str, int]:
    """Per-team slot counts from ROSTER_POSITIONS, e.g. {'QB':1,'RB':2,'WR':2,'FLEX':3,'SUPER_FLEX':1,'BN':6}."""
    counts: dict[str, int] = {}
    for slot in ROSTER_POSITIONS:
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def _allocate_starters(
    by_position: dict[str, list[dict[str, Any]]],
    slot_needs: dict[str, int],
) -> tuple[set[str], dict[str, int]]:
    """
    Shared starter-allocation core (see module docstring). `by_position`
    must already be grouped by position and sorted DESCENDING by
    projected_points within each position. `slot_needs` gives how many
    dedicated QB/RB/WR/TE slots plus FLEX/SUPER_FLEX slots need filling --
    already scaled to however many teams' worth of demand this call
    represents (`compute_replacement_levels` scales by NUM_TEAMS for
    league-wide demand; `allocate_roster_starters` uses raw per-team
    counts for a single roster's own lineup). The allocation algorithm
    (dedicated slots first, then one combined FLEX+SUPER_FLEX pass capped
    by QB eligibility -- see module docstring for why that must be one
    pass, not two) is identical either way; only the slot quantities
    differ.

    Returns (started_ids, flex_rank_by_id):
      - started_ids: the set of player_ids that would occupy a starting slot.
      - flex_rank_by_id: for players SPECIFICALLY seated via the shared
        FLEX+SUPER_FLEX pool (step 2 below) -- NOT the dedicated-slot
        starters from step 1, who never compete with a same-position
        teammate for their slot -- their 1-indexed rank (1 = best) among
        OTHER SAME-POSITION players also seated via that same shared pool.
        Added in Chunk 20 for the FLEX_CONCENTRATION_DISCOUNT this
        function's callers use (see portfolio.py) -- see this module's
        docstring for why this is tracked separately from the dedicated
        slots, which have no analogous concentration risk (there's only
        ever one player total per dedicated slot, structurally).
    """
    started_ids: set[str] = set()

    # Step 1: dedicated (non-flex) slots.
    remaining: dict[str, list[dict]] = {}
    for pos, players in by_position.items():
        need = slot_needs.get(pos, 0)
        started_ids.update(p["player_id"] for p in players[:need])
        remaining[pos] = players[need:]

    # Step 2: FLEX + SUPER_FLEX slots filled together as one combined greedy
    # pass: best-points-first across all remaining players of any position,
    # capped so at most `super_flex_slots` of the seats taken are QBs (the
    # only slot type a QB can occupy).
    flex_slots = slot_needs.get("FLEX", 0)
    super_flex_slots = slot_needs.get("SUPER_FLEX", 0)
    total_flexible_slots = flex_slots + super_flex_slots

    combined_pool: list[dict] = []
    for pos in SUPER_FLEX_ELIGIBLE:  # QB, RB, WR, TE
        combined_pool.extend(remaining.get(pos, []))
    combined_pool.sort(key=lambda p: p["projected_points"], reverse=True)

    qb_seated = 0
    flex_started: set[str] = set()
    flex_rank_by_id: dict[str, int] = {}
    flex_position_counts: dict[str, int] = {}
    for p in combined_pool:
        if len(flex_started) >= total_flexible_slots:
            break
        if p["position"] == "QB":
            if qb_seated >= super_flex_slots:
                continue  # no SUPER_FLEX slot left that could hold another QB
            qb_seated += 1
        flex_started.add(p["player_id"])
        flex_position_counts[p["position"]] = flex_position_counts.get(p["position"], 0) + 1
        flex_rank_by_id[p["player_id"]] = flex_position_counts[p["position"]]

    started_ids.update(flex_started)
    return started_ids, flex_rank_by_id


def _league_slot_needs(slot_counts: dict[str, int]) -> dict[str, int]:
    """Per-position/flex slot counts scaled to league-wide (all NUM_TEAMS teams') demand."""
    needs = {pos: slot_counts.get(pos, 0) * NUM_TEAMS for pos in FANTASY_POSITIONS}
    needs["FLEX"] = slot_counts.get("FLEX", 0) * NUM_TEAMS
    needs["SUPER_FLEX"] = slot_counts.get("SUPER_FLEX", 0) * NUM_TEAMS
    return needs


def compute_replacement_levels(
    projections: Iterable[dict[str, Any]],
    drafted_player_ids: set[str] | None = None,
) -> dict[str, float]:
    """
    Returns {position: replacement_level_points} for QB/RB/WR/TE, computed
    against the remaining (undrafted) player pool.

    `drafted_player_ids`: player_ids to exclude from the pool entirely
    (already off the board this draft). Safe to pass a growing set across
    repeated calls as a draft progresses.
    """
    drafted = drafted_player_ids or set()
    slot_counts = _slot_counts()

    by_position: dict[str, list[dict]] = {pos: [] for pos in FANTASY_POSITIONS}
    for p in projections:
        pos = p.get("position")
        if pos not in by_position:
            continue
        if p.get("player_id") in drafted:
            continue
        by_position[pos].append(p)

    for pos in by_position:
        by_position[pos].sort(key=lambda p: p["projected_points"], reverse=True)

    started_ids, _flex_ranks = _allocate_starters(by_position, _league_slot_needs(slot_counts))

    remaining = {
        pos: [p for p in players if p["player_id"] not in started_ids]
        for pos, players in by_position.items()
    }

    # Replacement level = best remaining (non-started) player left at each position.
    replacement_levels: dict[str, float] = {}
    for pos, players in remaining.items():
        if players:
            replacement_levels[pos] = players[0]["projected_points"]
        elif by_position[pos]:
            # Pool for this position is fully rostered (e.g. very deep into a
            # draft) -- fall back to the last started player's value rather
            # than crashing or returning a nonsensical 0.
            replacement_levels[pos] = by_position[pos][-1]["projected_points"]
        else:
            replacement_levels[pos] = 0.0

    return replacement_levels


def allocate_roster_starters(roster_players: Iterable[dict[str, Any]]) -> set[str]:
    """
    Given a SINGLE roster (not the league-wide draft pool), returns the
    set of player_ids that would occupy one of THIS roster's own starting
    slots (QB/RB/WR/FLEX/SUPER_FLEX per app/config.py ROSTER_POSITIONS),
    using the exact same allocation algorithm as `compute_replacement_levels`
    -- just with this one team's own slot counts (not scaled by NUM_TEAMS,
    since we're filling one team's lineup, not modeling league-wide
    demand). Anyone in `roster_players` but not in the returned set is
    bench.

    If the roster has fewer players than starting slots at some position
    (a mid-draft partial roster, or a thin bench), everyone eligible ends
    up started -- there's nobody left to be bench yet, which is the
    correct behavior for a roster still being built.
    """
    started_ids, _flex_ranks = allocate_roster_starters_with_flex_ranks(roster_players)
    return started_ids


def allocate_roster_starters_with_flex_ranks(
    roster_players: Iterable[dict[str, Any]],
) -> tuple[set[str], dict[str, int]]:
    """
    Chunk 20: same allocation as `allocate_roster_starters`, but ALSO
    returns flex_rank_by_id -- see `_allocate_starters`'s docstring for
    exactly what this tracks (a starter's rank among same-position
    teammates ALSO sharing the FLEX+SUPER_FLEX pool, used by
    portfolio.py's FLEX_CONCENTRATION_DISCOUNT). A separate function from
    `allocate_roster_starters` so that function's existing simple
    set-only API (used throughout the codebase since Chunk 6) never
    changes -- only callers that actually need the new detail
    (portfolio.py, shapley.py, mcts.py's roster-aware rollout policy)
    call this one instead.
    """
    slot_counts = _slot_counts()
    roster_slot_needs = {pos: slot_counts.get(pos, 0) for pos in FANTASY_POSITIONS}
    roster_slot_needs["FLEX"] = slot_counts.get("FLEX", 0)
    roster_slot_needs["SUPER_FLEX"] = slot_counts.get("SUPER_FLEX", 0)

    by_position: dict[str, list[dict]] = {pos: [] for pos in FANTASY_POSITIONS}
    for p in roster_players:
        pos = p.get("position")
        if pos in by_position:
            by_position[pos].append(p)

    for pos in by_position:
        by_position[pos].sort(key=lambda p: p["projected_points"], reverse=True)

    return _allocate_starters(by_position, roster_slot_needs)


def calculate_vbd(
    projections: Iterable[dict[str, Any]],
    drafted_player_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    VBD score per undrafted QB/RB/WR/TE player = projected_points minus that
    position's replacement level (see `compute_replacement_levels`), sorted
    descending by vbd. This is our first real draft-board ordering, using
    the projection's point estimate only -- uncertainty gets folded in once
    Monte Carlo simulation lands in a later chunk.

    Uses the point estimate only for now; safe to re-call with an updated
    `drafted_player_ids` as a draft progresses (recomputes replacement
    level from the remaining pool fresh each call, nothing is cached here).
    """
    projections = [p for p in projections if p.get("position") in FANTASY_POSITIONS]
    replacement_levels = compute_replacement_levels(projections, drafted_player_ids)

    drafted = drafted_player_ids or set()
    out: list[dict[str, Any]] = []
    for p in projections:
        if p["player_id"] in drafted:
            continue
        replacement = replacement_levels.get(p["position"], 0.0)
        out.append(
            {
                **p,
                "replacement_level": round(replacement, 1),
                "vbd": round(p["projected_points"] - replacement, 1),
            }
        )

    out.sort(key=lambda p: p["vbd"], reverse=True)
    return out
