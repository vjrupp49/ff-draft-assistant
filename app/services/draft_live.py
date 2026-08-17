"""
Live-draft tiered recompute manager -- the thing that makes the frontend
(Chunk 11) feel reactive without recomputing the expensive Draft Score
(MCTS + portfolio + Shapley) after every single opponent pick.

TWO TIERS, one draft_state (app.services.draft_state, Chunk 4 -- reused,
not rebuilt):
  1. CHEAP: after every new pick (from either driver below), broadcast a
     plain VBD board (app.services.vbd -- no simulation, no MCTS) plus
     how many picks remain until the user is on the clock. Always cheap
     enough to do on every pick, which is what keeps the live feed
     feeling alive between the user's own turns.
  2. EXPENSIVE: only when picks_until_your_turn <= expensive_threshold
     (configurable, default 2) -- including when it's already the user's
     turn (threshold check naturally covers 0) -- run the real
     app.services.draft_score_engine computation (MCTS + Shapley) and
     broadcast it. A "recalculating" message is broadcast the moment this
     tier starts, before the (multi-second) computation finishes, so the
     frontend can show a live "thinking" state rather than looking frozen.

     SUBTLETY (found by actually running this, not just describing it --
     see this chunk's verification notes): mcts.recommend() requires a
     state where it's LITERALLY the user's turn (its tree root is "my
     candidate picks right now"); calling it early, while opponent picks
     are still pending, raised an uncaught ValueError that silently killed
     the driver task. Since "within 1-2 picks" is explicitly what this
     tier is supposed to cover, `_run_expensive` provisionally simulates
     the intervening opponent pick(s) (same opponent_model policy used for
     real opponent turns) on a CLONE before invoking MCTS -- never
     mutating the real shared draft_state -- and marks the result
     `is_provisional: true`. The very next real pick re-triggers this tier
     fresh, correcting (or confirming) the guess once real information
     arrives.

TWO DRIVERS feed picks into the SAME tiered pipeline, deliberately not two
separate systems (same principle draft_state.py itself established in
Chunk 4 for hypothetical-vs-live construction):
  - LIVE: polls the real Sleeper draft (app.services.sleeper), same
    poll-and-dedupe-by-pick_no approach as the original Chunk 1 /ws/draft
    endpoint.
  - MOCK: replays a simulated draft using app.services.mock_draft's exact
    opponent-picking approach (app.services.opponent_model, unchanged)
    for the other 9 teams, and the REAL expensive tier's own top
    recommendation to auto-play the user's own picks -- this is what lets
    a full mock draft visibly flow through the live UI for testing
    (Chunk 9's harness ran headless; this drives the same underlying
    services through the visible pipeline instead).

Synchronous/CPU-bound work (MCTS, Shapley) is run via `asyncio.to_thread`
so it can't block the event loop -- otherwise a single expensive
recompute would freeze WebSocket delivery to every connected client for
its multi-second duration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import numpy as np
from fastapi import WebSocket

from app.config import NUM_DRAFT_ROUNDS, NUM_TEAMS, ROSTER_POSITIONS, SLEEPER_DRAFT_ID
from app.services import draft_score_engine
from app.services import mcts as mcts_service
from app.services import opponent_model
from app.services import vbd as vbd_service
from app.services.draft_state import DraftState
from app.services.projections import build_baseline_projections
from app.services.sleeper import SleeperAPIError, sleeper_client

logger = logging.getLogger("ff_draft_assistant.draft_live")

DEFAULT_EXPENSIVE_THRESHOLD = 2  # "within 1-2 picks" per the brief
DEFAULT_MOCK_DELAY_SECONDS = 1.5  # pacing so a mock draft is watchable, not instant
LIVE_POLL_INTERVAL_SECONDS = 3  # matches the original Chunk 1 /ws/draft cadence
CHEAP_BOARD_SIZE = 8


class DraftLiveManager:
    """
    Single shared instance (module-level singleton, see `get_manager`) --
    this is a personal, single-user tool (per Chunk 1's framing), so one
    active watched draft at a time is the right model, not per-connection
    state.
    """

    def __init__(self) -> None:
        self.draft_state: Optional[DraftState] = None
        self.players_by_id: dict[str, dict[str, Any]] = {}
        self.connections: set[WebSocket] = set()

        self.mode: Optional[str] = None  # "live" | "mock"
        self.status: str = "idle"  # idle | waiting | running | complete | error
        self.expensive_threshold: int = DEFAULT_EXPENSIVE_THRESHOLD

        self.last_pick_event: Optional[dict[str, Any]] = None
        self.last_draft_score: Optional[dict[str, Any]] = None
        self.is_recalculating: bool = False

        self.cheap_update_count: int = 0
        self.expensive_update_count: int = 0

        self._driver_task: Optional[asyncio.Task] = None

    # -- connection management ------------------------------------------

    async def register(self, ws: WebSocket) -> None:
        self.connections.add(ws)
        await self._send(ws, self.snapshot())

    def unregister(self, ws: WebSocket) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            try:
                await self._send(ws, message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.discard(ws)

    @staticmethod
    async def _send(ws: WebSocket, message: dict[str, Any]) -> None:
        await ws.send_json(message)

    def snapshot(self) -> dict[str, Any]:
        """Sent immediately to a newly-connected client so it isn't blank until the next pick."""
        base: dict[str, Any] = {
            "type": "snapshot",
            "mode": self.mode,
            "status": self.status,
            "expensive_threshold": self.expensive_threshold,
            "cheap_update_count": self.cheap_update_count,
            "expensive_update_count": self.expensive_update_count,
            "is_recalculating": self.is_recalculating,
            "last_pick_event": self.last_pick_event,
            "last_draft_score": self.last_draft_score,
        }
        if self.draft_state is not None:
            base.update(
                {
                    "my_slot": self.draft_state.my_slot,
                    "num_teams": self.draft_state.num_teams,
                    "current_pick_no": self.draft_state.current_pick_no,
                    "current_round": self.draft_state.current_round,
                    "is_my_turn": self.draft_state.is_my_turn,
                    "picks_until_your_turn": self.draft_state.picks_until_next_turn(),
                }
            )
        return base

    # -- starting a session ----------------------------------------------

    async def start_live(self, my_slot: int, num_teams: int = NUM_TEAMS, expensive_threshold: int = DEFAULT_EXPENSIVE_THRESHOLD) -> None:
        await self.stop()
        projections = await build_baseline_projections()
        self.players_by_id = {p["player_id"]: p for p in projections["players"]}
        self.draft_state = DraftState(my_slot=my_slot, num_teams=num_teams, roster_positions=list(ROSTER_POSITIONS))
        self.mode = "live"
        self.status = "waiting"
        self.expensive_threshold = expensive_threshold
        self._reset_counters()
        self._driver_task = asyncio.create_task(self._run_live_driver())
        await self.broadcast(self.snapshot())

    async def start_mock(
        self,
        my_slot: int,
        num_teams: int = NUM_TEAMS,
        seed: int = 1,
        delay_seconds: float = DEFAULT_MOCK_DELAY_SECONDS,
        expensive_threshold: int = DEFAULT_EXPENSIVE_THRESHOLD,
        mcts_iterations: int = mcts_service.ITERATIONS,
    ) -> None:
        await self.stop()
        projections = await build_baseline_projections()
        self.players_by_id = {p["player_id"]: p for p in projections["players"]}
        self.draft_state = DraftState(my_slot=my_slot, num_teams=num_teams, roster_positions=list(ROSTER_POSITIONS))
        self.mode = "mock"
        self.status = "running"
        self.expensive_threshold = expensive_threshold
        self._reset_counters()
        self._driver_task = asyncio.create_task(
            self._run_mock_driver(seed=seed, delay_seconds=delay_seconds, mcts_iterations=mcts_iterations)
        )
        await self.broadcast(self.snapshot())

    async def stop(self) -> None:
        if self._driver_task is not None:
            self._driver_task.cancel()
            self._driver_task = None
        self.status = "idle"

    def _reset_counters(self) -> None:
        self.last_pick_event = None
        self.last_draft_score = None
        self.is_recalculating = False
        self.cheap_update_count = 0
        self.expensive_update_count = 0

    # -- shared pick-processing pipeline (both drivers funnel through this) --

    def _cheap_board(self) -> list[dict[str, Any]]:
        ranked = vbd_service.calculate_vbd(
            list(self.players_by_id.values()), drafted_player_ids=self.draft_state.drafted_player_ids
        )
        return [
            {"player_id": p["player_id"], "name": p["name"], "position": p["position"], "team": p.get("team"), "vbd": p["vbd"]}
            for p in ranked[:CHEAP_BOARD_SIZE]
        ]

    async def _record_pick(self, player_id: str) -> dict[str, Any]:
        """Appends one pick and broadcasts the CHEAP tier update. Does not, by itself, trigger the expensive tier."""
        state = self.draft_state
        assert state is not None
        slot = state.slot_on_the_clock_now
        pick_no = state.current_pick_no
        is_my_pick = slot == state.my_slot
        player = self.players_by_id.get(player_id, {})

        state.add_pick(player_id)

        event = {
            "type": "pick",
            "pick_no": pick_no,
            "round": ((pick_no - 1) // state.num_teams) + 1,
            "slot": slot,
            "is_my_pick": is_my_pick,
            "player": {
                "player_id": player_id,
                "name": player.get("name"),
                "position": player.get("position"),
                "team": player.get("team"),
            },
            "picks_until_your_turn": state.picks_until_next_turn(),
            "is_my_turn": state.is_my_turn,
            "current_pick_no": state.current_pick_no,
            "current_round": state.current_round,
            "cheap_board": self._cheap_board(),
        }
        self.last_pick_event = event
        self.cheap_update_count += 1
        await self.broadcast(event)
        return event

    async def _maybe_run_expensive(self) -> Optional[dict[str, Any]]:
        assert self.draft_state is not None
        if self.draft_state.picks_until_next_turn() <= self.expensive_threshold:
            return await self._run_expensive()
        return None

    async def _run_expensive(self, mcts_iterations: int = mcts_service.ITERATIONS) -> dict[str, Any]:
        assert self.draft_state is not None
        state = self.draft_state
        self.is_recalculating = True
        await self.broadcast({"type": "recalculating", "picks_until_your_turn": state.picks_until_next_turn()})

        # mcts.recommend() requires a state where it's LITERALLY the
        # deciding player's turn (its tree root is "my candidate picks
        # right now") -- but this tier is deliberately triggered EARLY too
        # (picks_until_your_turn within expensive_threshold, not just 0),
        # so there can still be 1+ opponent picks left before it's
        # actually our turn. We can't know those for certain yet, so we
        # provisionally simulate them (the same opponent_model policy used
        # for real opponent picks) on a CLONE -- never mutating the real
        # shared draft_state -- and label the result "provisional". The
        # very next real pick re-triggers this tier fresh anyway, which
        # naturally corrects (or confirms) the guess once real information
        # arrives -- this is what lets the "recalculating" state start
        # before the user's exact turn without ever running MCTS against
        # an invalid/mismatched state.
        eval_state = state
        is_provisional = False
        if not eval_state.is_my_turn:
            eval_state = eval_state.clone()
            rng = np.random.default_rng()
            guard = 0
            while not eval_state.is_my_turn and guard < eval_state.num_teams * 2:
                pid = self._opponent_pick(rng, state=eval_state)
                if pid is None:
                    break
                eval_state.add_pick(pid)
                guard += 1
            is_provisional = True

        try:
            result = await asyncio.to_thread(
                draft_score_engine.compute_draft_score,
                eval_state,
                self.players_by_id,
                iterations=mcts_iterations,
            )
        except draft_score_engine.DraftScoreError as exc:
            logger.warning("Expensive recompute failed: %s", exc)
            self.is_recalculating = False
            await self.broadcast({"type": "error", "message": str(exc)})
            return {}

        payload = {
            "type": "draft_score",
            "current_pick_no": state.current_pick_no,
            "current_round": state.current_round,
            "is_my_turn": state.is_my_turn,
            "picks_until_your_turn": state.picks_until_next_turn(),
            "is_provisional": is_provisional,
            **result,
        }
        self.last_draft_score = payload
        self.expensive_update_count += 1
        self.is_recalculating = False
        await self.broadcast(payload)
        return payload

    # -- LIVE driver: poll the real Sleeper draft -----------------------

    async def _run_live_driver(self) -> None:
        seen_pick_nos: set[int] = set()
        try:
            while True:
                try:
                    picks = await sleeper_client.get_draft_picks(SLEEPER_DRAFT_ID)
                except SleeperAPIError as exc:
                    logger.warning("Live draft poll failed: %s", exc)
                    await asyncio.sleep(LIVE_POLL_INTERVAL_SECONDS)
                    continue

                if picks and self.status == "waiting":
                    self.status = "running"

                new_picks = [p for p in picks if p.get("pick_no") not in seen_pick_nos]
                new_picks.sort(key=lambda p: p.get("pick_no", 0))

                for raw in new_picks:
                    seen_pick_nos.add(raw["pick_no"])
                    # Sleeper's picks may not land in strict pick_no order across
                    # polls; our draft_state only ever appends "the next pick",
                    # so skip anything that doesn't match what we expect next
                    # (should be rare -- Sleeper picks are normally sequential).
                    if raw["pick_no"] != self.draft_state.current_pick_no:
                        continue
                    await self._record_pick(str(raw["player_id"]))
                    await self._maybe_run_expensive()

                await asyncio.sleep(LIVE_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass

    # -- MOCK driver: replay a simulated draft through the same pipeline --

    def _opponent_pick(self, rng: np.random.Generator, state: Optional[DraftState] = None) -> Optional[str]:
        state = state if state is not None else self.draft_state
        assert state is not None
        all_players = list(self.players_by_id.values())
        vbd_ranked = vbd_service.calculate_vbd(all_players, drafted_player_ids=state.drafted_player_ids)
        # CHUNK 21: real market ADP is now the primary opponent-timing
        # signal, VBD-proxy rank kept only as a fallback -- see
        # opponent_model.py's module docstring.
        vbd_proxy_ranks = opponent_model.build_adp_proxy_ranks(vbd_ranked)
        adp_ranks = opponent_model.build_market_adp_ranks(all_players, vbd_proxy_ranks)
        available = [p for p in all_players if p["player_id"] not in state.drafted_player_ids and p["position"] in vbd_service.FANTASY_POSITIONS]
        team_counts = state.position_counts(state.slot_on_the_clock_now, self.players_by_id)
        return opponent_model.sample_pick(rng, team_counts, available, state.current_pick_no, adp_ranks)

    async def _run_mock_driver(self, seed: int, delay_seconds: float, mcts_iterations: int) -> None:
        assert self.draft_state is not None
        rng = np.random.default_rng(seed)
        total_picks = self.draft_state.num_teams * NUM_DRAFT_ROUNDS

        try:
            while len(self.draft_state.picks) < total_picks:
                if self.draft_state.is_my_turn:
                    # Run the expensive tier first (this IS the decision, not
                    # just a status update) and auto-play its own top pick --
                    # the same engine a real user would be shown, deciding for
                    # itself so the mock draft can play out unattended.
                    result = await self._run_expensive(mcts_iterations=mcts_iterations)
                    draft_score = result.get("draft_score") if result else None
                    if not draft_score:
                        pid = self._opponent_pick(rng)  # defensive fallback, shouldn't trigger
                    else:
                        pid = draft_score["player_id"]
                    if pid is None:
                        break
                    await self._record_pick(pid)
                else:
                    pid = self._opponent_pick(rng)
                    if pid is None:
                        break
                    await self._record_pick(pid)
                    await self._maybe_run_expensive()

                await asyncio.sleep(delay_seconds)

            self.status = "complete"
            await self.broadcast({"type": "draft_complete", "my_roster": self.draft_state.roster_player_ids()})
        except asyncio.CancelledError:
            pass


_manager: Optional[DraftLiveManager] = None


def get_manager() -> DraftLiveManager:
    global _manager
    if _manager is None:
        _manager = DraftLiveManager()
    return _manager
