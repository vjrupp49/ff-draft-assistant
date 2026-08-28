"""
CHUNK 54 -- per-league "target" (starred) player persistence for the
Draft Outlook view ("who am I trying to get at the third pick").

MECHANISM CHOSEN: a single flat JSON file (data/draft_targets.json), keyed
by league_key -> list of player_ids. No database, no ORM, no migrations --
this project is an explicitly personal, zero-cost, single-user tool (the
same framing app/services/draft_live.py's own docstring uses), and
target-marking is low-frequency, low-volume (at most a few dozen
player_ids per league), so reading/writing the whole small file on every
change is simple and plenty fast. A module-level lock serializes writes
(this app can have multiple concurrent requests via FastAPI's async
event loop even though it's single-user) so two near-simultaneous
star/unstar clicks can't race and clobber each other's write.

WHY THIS FILE IS *NOT* GITIGNORED, UNLIKE THIS PROJECT'S OTHER data/*.json
FILES: players_cache.json, baseline_projections.json, adp_cache.json etc.
are all regenerable caches of external API data (Sleeper/nflverse/FFC) --
losing one just costs a re-fetch. This file holds genuine user input
(which players Vincent actually wants to target) with no way to
regenerate it if lost, so it's tracked in git like ordinary project state
rather than treated as disposable cache -- see .gitignore's Chunk 54 note.

Scoped per league_key so Kiddos' targets never leak into Former Bradley
Bums' view or vice versa (each league gets its own list in the same file).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

TARGETS_PATH = Path("data/draft_targets.json")
_lock = threading.Lock()


def _load() -> dict[str, list[str]]:
    if not TARGETS_PATH.exists():
        return {}
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = json.load(f)
    return {league_key: list(player_ids) for league_key, player_ids in raw.items()}


def _save(data: dict[str, list[str]]) -> None:
    TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TARGETS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp_path.replace(TARGETS_PATH)  # atomic swap on the same filesystem, avoids a torn write


def get_targets(league_key: str) -> list[str]:
    """Ordered list of targeted player_ids for one league (empty list if none set yet)."""
    with _lock:
        data = _load()
    return list(data.get(league_key, []))


def add_target(league_key: str, player_id: str) -> list[str]:
    """Stars `player_id` for `league_key`. Idempotent -- adding an already-starred player is a no-op."""
    with _lock:
        data = _load()
        ids = data.setdefault(league_key, [])
        if player_id not in ids:
            ids.append(player_id)
        _save(data)
        return list(ids)


def remove_target(league_key: str, player_id: str) -> list[str]:
    """Unstars `player_id` for `league_key`. Idempotent -- removing an already-absent player is a no-op."""
    with _lock:
        data = _load()
        ids = data.get(league_key, [])
        if player_id in ids:
            ids.remove(player_id)
        data[league_key] = ids
        _save(data)
        return list(ids)
