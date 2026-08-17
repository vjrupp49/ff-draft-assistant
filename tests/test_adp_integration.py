"""
Chunk 17 Task 5 -- regression tests for the ADP integration
(app/services/adp.py, wired into app/services/projections.py). Covers
the two failure modes Chunk 16 found and this chunk fixed: rookies/thin-
history players (flat fallback -> ADP-percentile-derived estimate) and
role-change veterans (silent failure -> detected + blended/flagged) --
plus the caching behavior that respects FantasyFootballCalculator's own
"please do not call this API too frequently" guidance.

None of these tests hit the real FFC API -- `fetch_adp`'s network call is
mocked throughout, per this chunk's brief ("don't hit the real endpoint
on every test run"). The live diagnostic numbers (format choice, sample
size, the 4 traced players' real ADP) are reported in Chunk 17's own
report, not re-verified here on every test run -- that's a one-time
diagnostic finding, not something that needs to stay true for this suite
to pass.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services import adp


# ---------------------------------------------------------------------
# Task 5a: ADP-to-points translation produces sane output for a known
# player / known synthetic inputs (no network needed -- pure functions).
# ---------------------------------------------------------------------

def test_adp_percentile_boundaries():
    # Best possible rank (1st) among N players -> 100th percentile.
    assert adp.adp_percentile(1, 10) == 100.0
    # Worst possible rank (Nth) among N players -> 0th percentile.
    assert adp.adp_percentile(10, 10) == 0.0
    # Middle of a 9-player pool -> exactly the midpoint.
    assert adp.adp_percentile(5, 9) == 50.0
    # Degenerate single-player pool -> neutral 50 (nothing to rank against).
    assert adp.adp_percentile(1, 1) == 50.0


def test_adp_derived_points_maps_percentile_onto_real_scored_distribution():
    # A known, simple scored-points distribution: deciles 10..100.
    scored = {"RB": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]}
    # 100th percentile of that distribution is its max (100.0).
    assert adp.adp_derived_points("RB", 100.0, scored) == 100.0
    # 0th percentile is its min (10.0).
    assert adp.adp_derived_points("RB", 0.0, scored) == 10.0
    # 50th percentile lands in the middle of the distribution.
    mid = adp.adp_derived_points("RB", 50.0, scored)
    assert 45.0 <= mid <= 65.0
    # A position with no scored population at all -> None, not a crash.
    assert adp.adp_derived_points("QB", 50.0, {}) is None


def test_normalize_name_strips_suffixes_and_punctuation():
    # These pairs must normalize to the SAME string, or FFC<->Sleeper name
    # matching silently misses real players (see adp.py's NAME MATCHING note).
    assert adp._normalize_name("Kenneth Walker III") == adp._normalize_name("Kenneth Walker")
    assert adp._normalize_name("Travis Etienne Jr.") == adp._normalize_name("Travis Etienne Jr")
    assert adp._normalize_name("D'Andre Swift") == adp._normalize_name("DAndre Swift")


def test_build_adp_lookup_and_ranks_by_position():
    payload = {
        "players": [
            {"name": "Player One", "position": "RB", "adp": 5.0},
            {"name": "Player Two", "position": "RB", "adp": 2.0},
            {"name": "Player Three", "position": "WR", "adp": 1.0},
        ]
    }
    lookup = adp.build_adp_lookup(payload)
    assert (adp._normalize_name("Player One"), "RB") in lookup
    by_pos = adp.adp_ranks_by_position(payload)
    # RB list should be sorted ascending by adp: "Player Two" (2.0) before "Player One" (5.0).
    assert [p["name"] for p in by_pos["RB"]] == ["Player Two", "Player One"]
    assert len(by_pos["WR"]) == 1


# ---------------------------------------------------------------------
# Task 5b: role-change detection fires correctly on a known traded
# player (pure function, no network).
# ---------------------------------------------------------------------

def test_team_changed_detects_a_real_trade_pattern():
    # Mirrors the real George Pickens case this chunk traced: historical
    # team PIT, current team DAL.
    assert adp.team_changed("PIT", "DAL") is True


def test_team_changed_false_when_same_team():
    assert adp.team_changed("KC", "KC") is False


def test_team_changed_false_when_either_side_unknown():
    # Missing info means "can't tell", not "assume a change" -- a false
    # positive here would incorrectly flag/blend a player who never
    # actually changed teams.
    assert adp.team_changed(None, "DAL") is False
    assert adp.team_changed("PIT", None) is False
    assert adp.team_changed(None, None) is False


# ---------------------------------------------------------------------
# Chunk 18: hardening added after a full-pool audit found zero team
# mismatches (no observed false positives) but a real, evidenced false-
# negative gap the "2qb" primary format alone missed. team_agrees() and
# find_adp_match()'s primary-then-fallback lookup are both pure
# functions, no network needed.
# ---------------------------------------------------------------------

def test_team_agrees_true_when_teams_match():
    assert adp.team_agrees("KC", "KC") is True


def test_team_agrees_false_when_teams_differ():
    # The exact "dangerous case" this chunk's audit hunted for -- a
    # disagreement here is the signal something might be a wrong-player
    # match, not just a stale entry.
    assert adp.team_agrees("PIT", "DAL") is False


def test_team_agrees_true_when_either_side_unknown():
    # Same "can't tell != disagreement" principle as team_changed above.
    assert adp.team_agrees(None, "DAL") is True
    assert adp.team_agrees("PIT", None) is True


def test_find_adp_match_prefers_primary_over_fallback():
    primary_payload = {"players": [{"name": "Same Player", "position": "RB", "adp": 10.0, "team": "KC"}]}
    fallback_payload = {"players": [{"name": "Same Player", "position": "RB", "adp": 5.0, "team": "KC"}]}
    primary_lookup = adp.build_adp_lookup(primary_payload)
    primary_by_pos = adp.adp_ranks_by_position(primary_payload)
    fallback_lookup = adp.build_adp_lookup(fallback_payload)
    fallback_by_pos = adp.adp_ranks_by_position(fallback_payload)

    match = adp.find_adp_match("Same Player", "RB", primary_lookup, primary_by_pos, fallback_lookup, fallback_by_pos)
    assert match is not None
    assert match["source"] == "primary"
    assert match["record"]["adp"] == 10.0  # the PRIMARY entry, not fallback's 5.0


def test_find_adp_match_falls_back_when_not_in_primary():
    # Mirrors the real James Conner case this chunk traced: absent from
    # "2qb" (too small a sample to reach that deep), present in "ppr".
    primary_payload = {"players": [{"name": "Someone Else", "position": "RB", "adp": 10.0, "team": "KC"}]}
    fallback_payload = {"players": [{"name": "Fallback Only Player", "position": "RB", "adp": 171.5, "team": "ARI"}]}
    primary_lookup = adp.build_adp_lookup(primary_payload)
    primary_by_pos = adp.adp_ranks_by_position(primary_payload)
    fallback_lookup = adp.build_adp_lookup(fallback_payload)
    fallback_by_pos = adp.adp_ranks_by_position(fallback_payload)

    match = adp.find_adp_match("Fallback Only Player", "RB", primary_lookup, primary_by_pos, fallback_lookup, fallback_by_pos)
    assert match is not None
    assert match["source"] == "fallback"
    assert match["record"]["team"] == "ARI"


def test_find_adp_match_returns_none_when_absent_from_both():
    primary_payload = {"players": [{"name": "Someone", "position": "RB", "adp": 10.0, "team": "KC"}]}
    fallback_payload = {"players": [{"name": "Someone Else", "position": "RB", "adp": 20.0, "team": "SF"}]}
    primary_lookup = adp.build_adp_lookup(primary_payload)
    primary_by_pos = adp.adp_ranks_by_position(primary_payload)
    fallback_lookup = adp.build_adp_lookup(fallback_payload)
    fallback_by_pos = adp.adp_ranks_by_position(fallback_payload)

    match = adp.find_adp_match("Nobody Home", "RB", primary_lookup, primary_by_pos, fallback_lookup, fallback_by_pos)
    assert match is None


def test_find_adp_match_works_without_a_fallback_dataset():
    # fetch_fallback_adp() returning None (network failure) shouldn't break
    # matching against the primary dataset -- confirms find_adp_match's
    # fallback_lookup=None default path.
    primary_payload = {"players": [{"name": "Solo Player", "position": "WR", "adp": 15.0, "team": "BUF"}]}
    primary_lookup = adp.build_adp_lookup(primary_payload)
    primary_by_pos = adp.adp_ranks_by_position(primary_payload)

    match = adp.find_adp_match("Solo Player", "WR", primary_lookup, primary_by_pos)
    assert match is not None
    assert match["source"] == "primary"


# ---------------------------------------------------------------------
# Task 5c: caching respects FFC's "don't call this too frequently"
# guidance -- the real network call is mocked, never hit for real here.
# ---------------------------------------------------------------------

@pytest.fixture
def isolated_adp_cache(tmp_path, monkeypatch):
    """Points adp.py's cache at a throwaway path so this test can't collide with the real dev cache."""
    cache_path = tmp_path / "adp_cache_test.json"
    monkeypatch.setattr(adp, "ADP_CACHE_PATH", str(cache_path))
    return cache_path


def _fake_response(payload: dict[str, Any]):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    return _Resp()


def test_fetch_adp_uses_cache_on_second_call_without_hitting_network(isolated_adp_cache):
    """
    Two fetch_adp() calls within the TTL window should only hit the
    (mocked) network ONCE -- the second must come from cache. This is the
    actual behavior that respects FFC's rate-limit guidance; asserting
    the mock's call count is what proves the cache is doing its job, not
    just that the function returns something plausible.
    """
    import asyncio

    fake_payload = {
        "status": "Success",
        "meta": {"type": "2 QB", "teams": 10, "total_drafts": 3066},
        "players": [{"name": "Test Player", "position": "RB", "team": "KC", "adp": 12.3}],
    }

    mock_get = AsyncMock(return_value=_fake_response(fake_payload))

    async def run():
        with patch("httpx.AsyncClient.get", mock_get):
            first = await adp.fetch_adp(force_refresh=True)
            second = await adp.fetch_adp()  # should hit the cache, not the network again
        return first, second

    first, second = asyncio.run(run())

    assert first == fake_payload
    assert second == fake_payload
    assert mock_get.call_count == 1, (
        f"expected exactly 1 real network call (first call force-refreshes, second should reuse the cache), "
        f"got {mock_get.call_count} -- the cache isn't respecting FFC's 'don't call too frequently' guidance"
    )
    assert isolated_adp_cache.exists(), "fetch_adp should have written the cache file"


def test_fetch_adp_force_refresh_bypasses_cache(isolated_adp_cache):
    """force_refresh=True must always hit the network, even with a fresh cache -- confirms the escape hatch works."""
    import asyncio

    fake_payload = {"status": "Success", "meta": {}, "players": []}
    mock_get = AsyncMock(return_value=_fake_response(fake_payload))

    async def run():
        with patch("httpx.AsyncClient.get", mock_get):
            await adp.fetch_adp(force_refresh=True)
            await adp.fetch_adp(force_refresh=True)

    asyncio.run(run())
    assert mock_get.call_count == 2
