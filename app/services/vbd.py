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
"""

from __future__ import annotations

from typing import Any, Iterable

from app.config import NUM_TEAMS, ROSTER_POSITIONS

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE"}
SUPER_FLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}


def _slot_counts() -> dict[str, int]:
    """Per-team slot counts from ROSTER_POSITIONS, e.g. {'QB':1,'RB':2,'WR':2,'FLEX':3,'SUPER_FLEX':1,'BN':6}."""
    counts: dict[str, int] = {}
    for slot in ROSTER_POSITIONS:
        counts[slot] = counts.get(slot, 0) + 1
    return counts


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

    # Step 1: dedicated (non-flex) slots.
    dedicated_needed = {pos: slot_counts.get(pos, 0) * NUM_TEAMS for pos in by_position}
    remaining: dict[str, list[dict]] = {
        pos: players[dedicated_needed[pos]:] for pos, players in by_position.items()
    }

    # Step 2: FLEX + SUPER_FLEX slots filled together as one combined greedy
    # pass (see module docstring for why this must NOT be two separate
    # passes): best-points-first across all remaining players of any
    # position, capped so at most `super_flex_slots` of the seats taken are
    # QBs (the only slot type a QB can occupy).
    flex_slots = slot_counts.get("FLEX", 0) * NUM_TEAMS
    super_flex_slots = slot_counts.get("SUPER_FLEX", 0) * NUM_TEAMS
    total_flexible_slots = flex_slots + super_flex_slots

    combined_pool: list[dict] = []
    for pos in SUPER_FLEX_ELIGIBLE:  # QB, RB, WR, TE
        combined_pool.extend(remaining[pos])
    combined_pool.sort(key=lambda p: p["projected_points"], reverse=True)

    started_ids: set[str] = set()
    qb_seated = 0
    for p in combined_pool:
        if len(started_ids) >= total_flexible_slots:
            break
        if p["position"] == "QB":
            if qb_seated >= super_flex_slots:
                continue  # no SUPER_FLEX slot left that could hold another QB
            qb_seated += 1
        started_ids.add(p["player_id"])

    remaining = {
        pos: [p for p in players if p["player_id"] not in started_ids]
        for pos, players in remaining.items()
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
