"""
Chunk 30 -- regression guard for the nfl_data_py stats migration
(app/services/projections.py's `_fetch_weekly_stats`).

ROOT CAUSE (Chunk 29, confirmed directly, not assumed): nfl_data_py's
`import_weekly_data` fetches from nflverse-data's "player_stats" GitHub
release, whose last real asset is player_stats_2024.parquet (published May
2025) -- nflverse rebuilt their stats pipeline in 2025 and moved current
data to a NEW release, "stats_player", which nfl_data_py 0.3.3 (latest on
PyPI) was never updated to point at. This meant every projection for every
established veteran was silently stuck on data up to 2 real seasons stale
-- concretely, Alvin Kamara's and James Conner's real 2025 season-ending
knee injuries (confirmed directly via nfl_data_py's own still-working
`import_injuries` endpoint) were completely invisible to this pipeline.

Chunk 30 migrated the fetch to nflverse's current release directly (see
projections.py's CHUNK 30 FIX note for why a direct fetch was chosen over
`nflreadpy`). These tests guard against silently regressing back to the
dead source.
"""
from __future__ import annotations

from typing import Any


def test_seasons_used_includes_a_current_season(players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    A direct, self-documenting freshness check that doesn't need updating
    as real stats keep accumulating year over year (unlike a hardcoded
    points threshold, which WILL eventually go stale on its own terms --
    see test_kamara_2025_injury_reduces_his_projection below for that
    tradeoff made deliberately, not by oversight). `players_by_id` (the
    conftest fixture) doesn't carry the top-level payload's own
    `seasons_used` field directly, so this checks a real player's own
    most-recently-used season instead, which is guaranteed present for
    anyone with usable history.
    """
    kamara = next((p for p in players_by_id.values() if p["name"] == "Alvin Kamara"), None)
    assert kamara is not None, "Alvin Kamara not found in players_by_id -- unexpected, investigate separately"
    most_recent_season_used = max(int(yr) for yr in kamara["games_by_season"].keys())
    assert most_recent_season_used >= 2025, (
        f"expected the most recent season used to be 2025 or later, got {most_recent_season_used} -- "
        "this is the exact symptom of regressing back to nfl_data_py's dead stats source (see module docstring)"
    )


def test_kamara_2025_injury_reduces_his_projection(players_by_id: dict[str, dict[str, Any]]) -> None:
    """
    Alvin Kamara's real 2025 season ended early due to a knee injury
    (confirmed directly via nfl_data_py's `import_injuries` endpoint during
    Chunk 29's diagnostic -- "Out" from week 13 onward). This must show up
    as a real, reduced games-played figure for that season, and a
    meaningfully lower total projection than the pre-migration, stale-data
    value (247.0). The 200-point threshold has real margin below the old
    value and above the new one (167.2 at the time of writing) -- unlike
    the season-freshness check above, THIS number is calibrated to today's
    real data and will legitimately need revisiting as future seasons
    accumulate; that's expected, not a maintenance failure.
    """
    kamara = next((p for p in players_by_id.values() if p["name"] == "Alvin Kamara"), None)
    assert kamara is not None

    games_2025 = kamara["games_by_season"].get("2025")
    assert games_2025 is not None, "expected a 2025 entry in games_by_season -- 2025 data isn't flowing through"
    assert games_2025 < 17, (
        f"expected Kamara's 2025 season to show fewer than a full 17 games (he missed significant time to a real "
        f"knee injury), got {games_2025} -- either the injury isn't reflected or this is stale pre-injury data"
    )

    assert kamara["projected_points"] < 200.0, (
        f"expected Kamara's projection to reflect his real 2025 decline/injury (well below the pre-migration "
        f"stale-data value of 247.0), got {kamara['projected_points']} -- the migration may have regressed"
    )
