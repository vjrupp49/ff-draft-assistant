"""FastAPI entrypoint for the FF Draft Assistant."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    DRAFT_POLL_INTERVAL_SECONDS,
    LEAGUE_NAME,
    NUM_DRAFT_ROUNDS,
    NUM_TEAMS,
    ROSTER_POSITIONS,
    SLEEPER_DRAFT_ID,
    SLEEPER_LEAGUE_ID,
)
from app.routers.draft_score import router as draft_score_router
from app.routers.live import router as live_router
from app.routers.mcts import router as mcts_router
from app.routers.portfolio import router as portfolio_router
from app.routers.rankings import router as rankings_router
from app.routers.shapley import router as shapley_router
from app.routers.simulate import router as simulate_router
from app.services.sleeper import SleeperAPIError, sleeper_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ff_draft_assistant")

app = FastAPI(title="FF Draft Assistant")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(rankings_router)
app.include_router(simulate_router)
app.include_router(mcts_router)
app.include_router(portfolio_router)
app.include_router(shapley_router)
app.include_router(draft_score_router)
app.include_router(live_router)


@app.get("/")
async def root() -> FileResponse:
    """Placeholder landing page."""
    return FileResponse("app/templates/index.html")


@app.get("/api/league-check")
async def league_check() -> JSONResponse:
    """
    Pulls live data from Sleeper for the configured league/draft and returns
    it next to our manual roster override, so both the live Sleeper
    connection and the override can be visually confirmed at a glance.
    """
    try:
        league = await sleeper_client.get_league(SLEEPER_LEAGUE_ID)
        rosters = await sleeper_client.get_rosters(SLEEPER_LEAGUE_ID)
        users = await sleeper_client.get_users(SLEEPER_LEAGUE_ID)
        draft = await sleeper_client.get_draft(SLEEPER_DRAFT_ID)
    except SleeperAPIError as exc:
        logger.error("Sleeper league-check failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return JSONResponse(
        content={
            "sleeper_live": {
                "league_name": league.get("name"),
                "league_id": league.get("league_id"),
                "total_rosters": league.get("total_rosters"),
                "status": league.get("status"),
                "season": league.get("season"),
                "roster_positions_from_sleeper": league.get("roster_positions"),
                "scoring_settings_from_sleeper": league.get("scoring_settings"),
                "num_rosters_returned": len(rosters),
                "num_users_returned": len(users),
                "draft_id": draft.get("draft_id"),
                "draft_status": draft.get("status"),
                "draft_type": draft.get("type"),
            },
            "manual_override_in_effect": {
                "league_name": LEAGUE_NAME,
                "num_teams": NUM_TEAMS,
                "roster_positions": ROSTER_POSITIONS,
                "num_draft_rounds": NUM_DRAFT_ROUNDS,
                "note": (
                    "roster_positions_from_sleeper above reflects Sleeper's "
                    "STALE league settings (still shows a required TE slot "
                    "and only 2 FLEX spots). roster_positions under this key "
                    "is the corrected, hardcoded override actually in effect "
                    "for this league (TE slot removed, 3rd FLEX added in its "
                    "place) — see app/config.py for why."
                ),
            },
        }
    )


@app.websocket("/ws/draft")
async def ws_draft(websocket: WebSocket) -> None:
    """
    Streams newly-made draft picks to the client as JSON.

    Polls Sleeper's get_draft_picks every DRAFT_POLL_INTERVAL_SECONDS and
    tracks which picks have already been sent (by pick_no) so this
    connection never resends a pick it already pushed.
    """
    await websocket.accept()
    seen_pick_nos: set[int] = set()
    logger.info("Draft websocket client connected")

    try:
        while True:
            try:
                picks = await sleeper_client.get_draft_picks(SLEEPER_DRAFT_ID)
            except SleeperAPIError as exc:
                logger.warning("Sleeper draft-picks poll failed: %s", exc)
                await asyncio.sleep(DRAFT_POLL_INTERVAL_SECONDS)
                continue

            new_picks = [
                pick for pick in picks if pick.get("pick_no") not in seen_pick_nos
            ]
            new_picks.sort(key=lambda pick: pick.get("pick_no", 0))

            for pick in new_picks:
                seen_pick_nos.add(pick["pick_no"])
                await websocket.send_json(pick)

            await asyncio.sleep(DRAFT_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.info("Draft websocket client disconnected")
