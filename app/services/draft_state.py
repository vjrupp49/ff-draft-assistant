"""
Draft state: a snake-draft position/pick tracker that works identically for
a hypothetical/simulated draft (draft order isn't locked in for this league
yet) and for a real live draft synced from Sleeper -- one data structure,
two ways to populate it, per the brief for this chunk.

Teams are addressed by DRAFT SLOT (1..num_teams, i.e. "picks Nth in round
1"), not by Sleeper roster_id/user_id -- slot is the only thing that
actually determines pick order in a snake draft, and it's the only thing
we can assume before the league sets a real draft order. `my_slot` is
always an explicit parameter (never inferred), whether the state is
hypothetical or synced from a real draft.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import NUM_TEAMS, ROSTER_POSITIONS


def slot_on_the_clock(pick_no: int, num_teams: int) -> int:
    """Which draft slot (1..num_teams) is on the clock for a given overall pick number, snake order."""
    if pick_no < 1:
        raise ValueError("pick_no is 1-indexed")
    round_no = (pick_no - 1) // num_teams + 1
    pos_in_round = pick_no - (round_no - 1) * num_teams  # 1..num_teams
    if round_no % 2 == 1:
        return pos_in_round
    return num_teams + 1 - pos_in_round


def round_of_pick(pick_no: int, num_teams: int) -> int:
    return (pick_no - 1) // num_teams + 1


def pick_no_for(round_no: int, slot: int, num_teams: int) -> int:
    """Inverse of slot_on_the_clock: the overall pick number for a given (round, slot)."""
    pos_in_round = slot if round_no % 2 == 1 else num_teams + 1 - slot
    return (round_no - 1) * num_teams + pos_in_round


@dataclass(frozen=True)
class DraftPick:
    pick_no: int
    slot: int
    player_id: str


@dataclass
class DraftState:
    my_slot: int
    num_teams: int = NUM_TEAMS
    roster_positions: list[str] = field(default_factory=lambda: list(ROSTER_POSITIONS))
    picks: list[DraftPick] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (1 <= self.my_slot <= self.num_teams):
            raise ValueError(f"my_slot must be within 1..{self.num_teams}, got {self.my_slot}")

    # -- construction from either source -----------------------------------

    @classmethod
    def hypothetical(
        cls,
        my_slot: int,
        picks_so_far: Optional[list[dict[str, Any]]] = None,
        num_teams: int = NUM_TEAMS,
        roster_positions: Optional[list[str]] = None,
    ) -> "DraftState":
        """
        Build state for an assumed draft slot with an invented/hypothetical
        set of picks-so-far (e.g. "what if I'm picking 3rd and these
        players are already gone"). `picks_so_far` items: {pick_no, slot,
        player_id} -- slot is optional and inferred via snake order if
        omitted (assumes picks were made in order, on the clock each time).
        """
        state = cls(my_slot=my_slot, num_teams=num_teams, roster_positions=list(roster_positions or ROSTER_POSITIONS))
        for raw in sorted(picks_so_far or [], key=lambda x: x["pick_no"]):
            slot = raw.get("slot") or slot_on_the_clock(raw["pick_no"], num_teams)
            state.picks.append(DraftPick(pick_no=raw["pick_no"], slot=slot, player_id=raw["player_id"]))
        return state

    @classmethod
    def from_sleeper_picks(
        cls,
        my_slot: int,
        sleeper_picks: list[dict[str, Any]],
        num_teams: int = NUM_TEAMS,
        roster_positions: Optional[list[str]] = None,
    ) -> "DraftState":
        """
        Build state from real picks pulled via
        app.services.sleeper.SleeperClient.get_draft_picks -- Sleeper's
        pick objects already carry `draft_slot`, so this is a direct
        field mapping, no inference needed. `my_slot` still has to be told
        which of the 1..num_teams slots is "mine" (Sleeper's picks don't
        say that -- it's a fact about this app's user, not the draft).
        """
        state = cls(my_slot=my_slot, num_teams=num_teams, roster_positions=list(roster_positions or ROSTER_POSITIONS))
        for raw in sorted(sleeper_picks, key=lambda x: x["pick_no"]):
            state.picks.append(
                DraftPick(pick_no=raw["pick_no"], slot=raw["draft_slot"], player_id=str(raw["player_id"]))
            )
        return state

    # -- derived state --------------------------------------------------

    @property
    def current_pick_no(self) -> int:
        return len(self.picks) + 1

    @property
    def current_round(self) -> int:
        return round_of_pick(self.current_pick_no, self.num_teams)

    @property
    def slot_on_the_clock_now(self) -> int:
        return slot_on_the_clock(self.current_pick_no, self.num_teams)

    @property
    def is_my_turn(self) -> bool:
        return self.slot_on_the_clock_now == self.my_slot

    @property
    def drafted_player_ids(self) -> set[str]:
        return {p.player_id for p in self.picks}

    def roster_player_ids(self, slot: Optional[int] = None) -> list[str]:
        """Player ids picked by a slot so far (defaults to my_slot)."""
        target = self.my_slot if slot is None else slot
        return [p.player_id for p in self.picks if p.slot == target]

    def position_counts(self, slot: Optional[int], players_by_id: dict[str, dict[str, Any]]) -> Counter:
        """Counts of each position drafted so far by a slot (defaults to my_slot)."""
        counts: Counter = Counter()
        for pid in self.roster_player_ids(slot):
            player = players_by_id.get(pid)
            if player:
                counts[player["position"]] += 1
        return counts

    def picks_until_next_turn(self, slot: Optional[int] = None) -> int:
        """How many picks (including this one) happen before `slot` is on the clock again, from current_pick_no."""
        target = self.my_slot if slot is None else slot
        pick_no = self.current_pick_no
        count = 0
        while slot_on_the_clock(pick_no, self.num_teams) != target:
            pick_no += 1
            count += 1
            if count > self.num_teams * 2:  # safety valve, should never trigger
                raise RuntimeError("picks_until_next_turn failed to converge")
        return count

    # -- mutation (used by MCTS to explore forward without touching the original) --

    def add_pick(self, player_id: str, slot: Optional[int] = None) -> "DraftState":
        """Append a pick at the current pick number, in place. Returns self for chaining."""
        pick_slot = self.slot_on_the_clock_now if slot is None else slot
        self.picks.append(DraftPick(pick_no=self.current_pick_no, slot=pick_slot, player_id=player_id))
        return self

    def clone(self) -> "DraftState":
        """Independent copy for MCTS tree branching -- mutating the clone never touches the original."""
        return DraftState(
            my_slot=self.my_slot,
            num_teams=self.num_teams,
            roster_positions=list(self.roster_positions),
            picks=list(self.picks),  # DraftPick is frozen/immutable, shallow copy of the list is enough
        )
