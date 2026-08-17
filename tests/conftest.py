"""
Shared pytest fixtures for the regression suite (Chunk 15 -- the
project's first automated tests, converting Chunks 9/13/14's manual
harness runs into permanent checks).

`players_by_id` is genuinely expensive to build (pulls/caches nfl_data_py
season stats and scores every player under this league's rules) -- built
ONCE per test session via a session-scoped fixture, not per-test, so the
whole suite stays fast enough to actually get run regularly (see
README's Testing section for why that matters).

Uses `asyncio.run()` directly rather than pytest-asyncio: this project's
async surface here is exactly one call
(`app.services.projections.build_baseline_projections`), so adding a
whole extra test-only dependency for one awaited call isn't worth it --
keeps this suite's only new dependency to plain `pytest`.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.projections import build_baseline_projections


@pytest.fixture(scope="session")
def players_by_id() -> dict[str, dict[str, Any]]:
    projections = asyncio.run(build_baseline_projections())
    return {p["player_id"]: p for p in projections["players"]}
