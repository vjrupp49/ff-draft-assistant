"""
Live-draft control + streaming: start/stop a watched draft session (real
Sleeper or a mock replay), and the WebSocket clients stream tiered updates
from. See app/services/draft_live.py for the tiered-recompute design.

Deliberately split from the WebSocket itself: starting/stopping a session
is a REST action (so the frontend, or a test script, can kick one off
with a single POST and not worry about connection lifecycle), while
`/ws/draft-live` is purely for streaming -- connecting doesn't start
anything, it just attaches to whatever session (if any) is running and
immediately gets a snapshot.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.config import NUM_TEAMS
from app.services import draft_live
from app.services import mcts as mcts_service

router = APIRouter()


class StartLiveRequest(BaseModel):
    my_slot: int = Field(..., ge=1)
    num_teams: int = Field(default=NUM_TEAMS)
    expensive_threshold: int = Field(
        default=draft_live.DEFAULT_EXPENSIVE_THRESHOLD,
        ge=0,
        description="Run the full Draft Score recompute once picks-until-your-turn drops to this many (0 = only on your exact turn).",
    )
    watch_draft_id: Optional[str] = Field(
        default=None,
        description=(
            "\"Sleeper Mock\" watch mode: poll THIS Sleeper draft (one you started yourself) instead of "
            "your real league draft. Omit for the normal live path. Validated read-only via "
            "/api/live/inspect-draft first -- can't be a real league draft or an already-finished one."
        ),
    )


class StartMockRequest(StartLiveRequest):
    seed: int = Field(default=1)
    delay_seconds: float = Field(default=draft_live.DEFAULT_MOCK_DELAY_SECONDS, ge=0, le=10)
    mcts_iterations: int = Field(default=mcts_service.ITERATIONS, ge=1, le=1000)


@router.get("/api/live/inspect-draft")
async def inspect_draft(
    draft_id: str = Query(..., description="Sleeper draft ID to pre-check for the 'Sleeper Mock' watch mode"),
    my_slot: Optional[int] = Query(default=None, ge=1, description="Override the auto-detected slot"),
) -> dict[str, Any]:
    """Read-only pre-flight: is this Sleeper mock watchable, which slot is mine, any format warnings."""
    return await draft_live.inspect_sleeper_draft(draft_id, my_slot_override=my_slot)


@router.post("/api/live/start-live")
async def start_live(request: StartLiveRequest) -> dict[str, Any]:
    manager = draft_live.get_manager()
    session_warnings: list[str] = []
    num_teams = request.num_teams
    my_slot = request.my_slot

    if request.watch_draft_id:
        info = await draft_live.inspect_sleeper_draft(request.watch_draft_id, my_slot_override=request.my_slot)
        if not info.get("ok"):
            raise HTTPException(status_code=400, detail=info.get("error") or "That draft can't be watched.")
        num_teams = info["num_teams"]
        my_slot = info["my_slot"]
        session_warnings = info.get("format_warnings") or []

    await manager.start_live(
        my_slot=my_slot,
        num_teams=num_teams,
        expensive_threshold=request.expensive_threshold,
        watch_draft_id=request.watch_draft_id,
        session_warnings=session_warnings,
    )
    return manager.snapshot()


@router.post("/api/live/start-mock")
async def start_mock(request: StartMockRequest) -> dict[str, Any]:
    manager = draft_live.get_manager()
    await manager.start_mock(
        my_slot=request.my_slot,
        num_teams=request.num_teams,
        seed=request.seed,
        delay_seconds=request.delay_seconds,
        expensive_threshold=request.expensive_threshold,
        mcts_iterations=request.mcts_iterations,
    )
    return manager.snapshot()


@router.post("/api/live/stop")
async def stop_live() -> dict[str, Any]:
    manager = draft_live.get_manager()
    await manager.stop()
    return manager.snapshot()


@router.get("/api/live/status")
async def live_status() -> dict[str, Any]:
    return draft_live.get_manager().snapshot()


@router.websocket("/ws/draft-live")
async def ws_draft_live(websocket: WebSocket) -> None:
    manager = draft_live.get_manager()
    await websocket.accept()
    await manager.register(websocket)
    try:
        while True:
            # This connection is receive-only from the frontend's perspective
            # (all state changes happen via the REST start/stop endpoints) --
            # just wait for a disconnect. recv() also lets us notice a dead
            # socket promptly instead of only on the next broadcast attempt.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(websocket)
