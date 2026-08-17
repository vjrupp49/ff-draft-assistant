"""
Chunk 26 -- regression guard for a real, pre-existing cross-process
determinism bug found while validating the adaptive-resolution feature.

`app.services.vbd.FANTASY_POSITIONS` / `SUPER_FLEX_ELIGIBLE` used to be
Python `set` literals. `_allocate_starters`'s `combined_pool` is built by
iterating `SUPER_FLEX_ELIGIBLE`, then STABLE-sorted by projected_points --
so any players tied EXACTLY on projected_points (real, not rare: e.g.
ADP-percentile-derived rookie/fallback estimates) had their relative order
-- and therefore which one gets a flex slot vs becomes "replacement
level" -- decided by which position was iterated first, which for a `set`
of strings is HASH-RANDOMIZED per Python process (PYTHONHASHSEED), NOT
tied to any `seed` parameter anywhere in this codebase. Confirmed directly:
the exact same real draft state + `recommend(..., seed=1)` produced
measurably different VBD scores and different top MCTS picks across
separate process invocations before this fix (e.g. Brock Bowers' VBD score
195.3 vs 209.2 for the identical state) -- the same class of bug Chunk 15
fixed ("the same seed never meant the same run"), via a mechanism Chunk
15's own within-one-process testing could never have caught.

This test can only meaningfully catch a REGRESSION back to a `set` (or
`frozenset`, or `dict.keys()`, or any other unordered container) by
actually spawning a separate Python process per check -- an in-process
test would share ONE PYTHONHASHSEED throughout and could pass even with
the bug present. `subprocess` is used deliberately for exactly that
reason, not as a stylistic choice.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

_CHECK_SCRIPT = """
import sys
from app.services.vbd import FANTASY_POSITIONS, SUPER_FLEX_ELIGIBLE
print(type(FANTASY_POSITIONS).__name__, type(SUPER_FLEX_ELIGIBLE).__name__)
"""


def test_fantasy_positions_and_super_flex_eligible_are_ordered_not_a_set():
    """
    Direct guard on the TYPE (not just current behavior) -- the fastest,
    most direct way to prevent a future edit from reintroducing an
    unordered container for either constant, regardless of whether any
    given test run happens to expose the resulting nondeterminism.
    """
    from app.services import vbd as vbd_service

    assert not isinstance(vbd_service.FANTASY_POSITIONS, (set, frozenset)), (
        "FANTASY_POSITIONS must be an ordered collection (tuple/list) -- a `set` reintroduces the "
        "Chunk 26 cross-process nondeterminism bug (hash-randomized iteration order feeding into "
        "_allocate_starters' stable sort tie-break)."
    )
    assert not isinstance(vbd_service.SUPER_FLEX_ELIGIBLE, (set, frozenset)), (
        "SUPER_FLEX_ELIGIBLE must be an ordered collection (tuple/list) -- see FANTASY_POSITIONS' "
        "assertion above for why."
    )


def test_calculate_vbd_is_reproducible_across_separate_processes():
    """
    Runs the exact real-draft VBD computation from Chunk 26's own
    diagnostic (pick 39's pre-pick state, a case that genuinely surfaced
    the bug live) in 3 SEPARATE Python processes and confirms every one
    produces the identical result -- an in-process assertion cannot catch
    this class of bug (see module docstring).
    """
    script = """
import asyncio, json, sys
sys.path.insert(0, r"{repo_root}")
from app.services.vbd import calculate_vbd
from app.services.projections import build_baseline_projections

async def main():
    payload = await build_baseline_projections()
    players_by_id = {{p["player_id"]: p for p in payload["players"]}}
    with open(r"{fixture}") as f:
        raw = json.load(f)
    drafted = {{str(p["player_id"]) for p in raw if p["pick_no"] < 39}}
    vbd_full = calculate_vbd(list(players_by_id.values()), drafted_player_ids=drafted)
    print(vbd_full[0]["name"], vbd_full[0]["vbd"])

asyncio.run(main())
""".format(
        repo_root=str(REPO_ROOT),
        fixture=str(REPO_ROOT / "tests" / "fixtures" / "chunk22_real_draft_picks.json"),
    )

    outputs = []
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        outputs.append(result.stdout.strip())

    assert len(set(outputs)) == 1, (
        f"calculate_vbd produced DIFFERENT results across separate process invocations for the "
        f"identical real draft state -- the Chunk 26 hash-randomization bug may have regressed. "
        f"Outputs seen: {outputs}"
    )
