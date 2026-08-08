"""
Read-only async client for the public Sleeper API.

No auth required (Sleeper's API is free and public). All methods return the
parsed JSON payload as-is (list/dict) unless noted otherwise.

Sleeper asks that `get_all_players` NOT be polled frequently (it's a ~5000
player payload covering every NFL player). We cache it to disk and only
re-fetch once a day — see `get_all_players`.

Docs: https://docs.sleeper.com/
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import (
    PLAYERS_CACHE_MAX_AGE_HOURS,
    PLAYERS_CACHE_PATH,
    SLEEPER_API_BASE,
)

_REQUEST_TIMEOUT_SECONDS = 15.0


class SleeperAPIError(RuntimeError):
    """Raised when the Sleeper API returns an unexpected response."""


class SleeperClient:
    """Thin async wrapper around the Sleeper REST API."""

    def __init__(self, base_url: str = SLEEPER_API_BASE) -> None:
        self._base_url = base_url.rstrip("/")

    async def _get(self, path: str) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                raise SleeperAPIError(f"Request to {url} failed: {exc}") from exc

        if response.status_code != 200:
            raise SleeperAPIError(
                f"GET {url} returned {response.status_code}: {response.text[:500]}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise SleeperAPIError(f"GET {url} returned non-JSON response: {exc}") from exc

    # --- League ------------------------------------------------------

    async def get_league(self, league_id: str) -> dict[str, Any]:
        """League settings, scoring settings, roster_positions, etc."""
        return await self._get(f"/league/{league_id}")

    async def get_rosters(self, league_id: str) -> list[dict[str, Any]]:
        """All rosters (one per team) in the league."""
        return await self._get(f"/league/{league_id}/rosters")

    async def get_users(self, league_id: str) -> list[dict[str, Any]]:
        """All users (managers) in the league."""
        return await self._get(f"/league/{league_id}/users")

    # --- Draft ---------------------------------------------------------

    async def get_draft(self, draft_id: str) -> dict[str, Any]:
        """Draft metadata: status, type, draft_order, settings, etc."""
        return await self._get(f"/draft/{draft_id}")

    async def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """All picks made so far in the draft, in pick order."""
        return await self._get(f"/draft/{draft_id}/picks")

    # --- Players (cached) ------------------------------------------------

    async def get_all_players(
        self,
        cache_path: str | Path = PLAYERS_CACHE_PATH,
        max_age_hours: float = PLAYERS_CACHE_MAX_AGE_HOURS,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Full NFL player dictionary, keyed by player_id (~5000 entries).

        Sleeper explicitly asks this endpoint not be hit frequently, so we
        cache the response to disk and only re-fetch if the cache is missing,
        unreadable, or older than `max_age_hours` (default: once a day).
        """
        cache_file = Path(cache_path)

        if not force_refresh and cache_file.exists():
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                try:
                    with cache_file.open("r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass  # fall through and re-fetch on a corrupt/unreadable cache

        players = await self._get("/players/nfl")

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(players, f)

        return players


# Module-level shared client/instance for convenience.
sleeper_client = SleeperClient()
