"""
Chunk 26 -- regression tests for adaptive tie resolution
(app/services/mcts.py's `_adaptively_resolve_tie`), and for reordering the
decision logic so it runs BEFORE the Chunk 24 ADP-margin tie-break, which
is now a fallback for genuinely-tied candidates only.

Chunk 25's diagnostic found `within_noise_of_leader` groups are often a
BUDGET-DILUTION artifact (recommend()'s ITERATIONS split across up to
CANDIDATE_BREADTH root candidates), not genuine indifference -- a
well-powered re-test shed at least the weakest member from all 6 traced
tied groups, and fully resolved 2 of 6. It also found the well-powered
winner does NOT reliably match what the ADP-margin tie-break would pick
(0/2 agreement on the cleanly-resolved cases), and surfaced a real bug:
at pick 122, the tied group was {Jerry Jeudy, David Njoku, Evan Engram}
-- Njoku/Engram have no real market_adp match, so Jeudy (the only matched
candidate) won the tie-break BY DEFAULT even though a fair re-test showed
Jeudy was the single WORST option in the group (z=18.31 behind Engram).

`fixtures/chunk22_real_draft_picks.json` (Chunk 24's fixture, reused) is
the real 150-pick history from the Chunk 22 dry run (my_slot=2) -- these 6
picks are the exact ones Chunks 25-26 traced.

CHUNK 30 CORRECTION (found live, root-caused, not silently patched): all
six picks' expected top-name/adaptive/tie-break values below were re-pinned
after Chunk 30 migrated projections.py off nfl_data_py's dead stats source
(stuck on 2022-2024 data) onto current 2025 data. Real, meaningful value
shifts (e.g. Alvin Kamara's and James Conner's real 2025 season-ending
knee injuries now correctly lowering their projections -- see Chunk 30's
report) changed which candidates are even in each pick's tied group, so
several of these outcomes moved. Verified each new outcome directly (real
ADP alignment, roster context, no LA/LAR-bug involvement beyond what
Chunk 29 already found and explicitly deferred) before repinning -- not a
blind re-recording of whatever the code now outputs. Pick 122 specifically
no longer reproduces the original Jeudy/Njoku/Engram tied group at all
(the board composition shifted enough that an unrelated QB now leads) --
its test is loosened to the actual regression signature (Jeudy must never
win by default) rather than requiring that exact now-gone scenario to
still exist; the general no-match-fallback MECHANISM is separately covered
by this file's synthetic unit tests below, which don't depend on live
data and are unaffected by this migration.

CHUNK 31 CORRECTION (LA/LAR team-abbreviation fix, isolated from the Chunk
30 migration above -- this is the exact "no LA/LAR-bug involvement beyond
what Chunk 29 already found and explicitly deferred" caveat Chunk 30
flagged): fixing app/services/adp.py's team_changed() (nflverse's "LA" vs
Sleeper's "LAR" for the Rams were being compared as literally different
teams) stopped incorrectly flagging every current Rams player as a
role-change veteran -- which stops incorrectly blending their projection
65% toward an ADP-derived estimate. Kyren Williams was directly affected:
his projected_points was wrongly suppressed from his real 277.8 to a
blended 177.3 under the bug (confirmed by directly re-running the same
blend math with the pre-fix team_changed() output). That 100-point
understatement was hiding his true value at picks 39/82 below. Re-verified
directly (not a blind re-recording) before repinning:
  - Pick 39: Kyren Williams (real, unsuppressed value 277.8) now
    outranks Josh Jacobs (242.0, unaffected -- GB isn't an aliased
    abbreviation) outright via adaptive resolution alone, so the ADP
    tie-break fallback no longer fires here either (`adp_tie_break_applied`
    flips True -> False). See test_adp_margin_tiebreak_regression.py's own
    matching correction for the mirror of this same root cause.
  - Pick 82: still correctly resolves to Travis Kelce, but Kyren
    Williams' restored true value now makes it a genuine near-tie at this
    decision point where it previously wasn't one, so adaptive resolution
    now engages (`adaptive_resolution_applied` flips False -> True) even
    though the winner is unchanged.

CHUNK 33 CORRECTION (TE bench-discount recalibration, BENCH_DISCOUNT_DECAY
["TE"] 1.0 -> 0.3 -- see portfolio.py's CHUNK 33 FIX note): pick 82 flips
again, this time the WINNER, not just the tie-break mechanics. Root-caused
directly (not assumed) by re-instrumenting this exact decision: before
this fix, MCTS's own rollout continuation could stockpile 2nd/3rd bench
TEs later in a "take Kelce now" rollout at a flat 0.25 contributed value
each regardless of how many were already stashed, inflating that branch's
average simulated reward. With the fix, that same speculative TE-stacking
future is correctly discounted harder per additional bench TE, so
Kelce's branch reward drops relative to Tony Pollard's (real ADP 83.4 --
a tight, genuinely at-risk margin, unaffected by anything TE-related).
Re-verified directly: at pick 82 (0 TEs on the roster yet), Pollard now
leads 2156.4 vs Kelce's 2106.3 (combined stderr ~6.3, a real z~8 gap, not
noise -- `within_noise_of_leader` is False for Kelce). This is the
INTENDED effect of the fix (discouraging speculative TE depth throughout
the rollout's simulated future, not just at the literal current pick),
not a side-effect bug -- Kelce remains a defensible, closely-valued pick,
just no longer the confident leader once the old bench-TE-stacking
assumption is removed.

CHUNK 38 CORRECTION (vbd.py's `_allocate_starters` FLEX+SUPER_FLEX pool now
ranked by within-position percentile, not raw points -- see vbd.py's own
CHUNK 38 FIX docstring): re-verified every pick below directly (probe
scripts, not assumed) against BOTH the league-wide VBD ranking (old raw
vs new percentile) and this roster's own starter allocation. Two clearly
different effects showed up:

  - Picks 79/102/122: the WINNER is unchanged (Tony Pollard / Matthew
    Stafford / Matthew Stafford, same as before) -- only WHICH tie-
    resolution mechanism fires flipped, because the fix legitimately
    changed the league-wide VBD landscape (confirmed: TE/extra-QB glut
    that used to crowd top8 VBD at these exact picks -- e.g. pick 102's
    old top8 held FOUR tight ends -- is gone in the new ranking, replaced
    by real RB/WR representation, exactly this chunk's intended fix).
    That shifted some candidates from "needs the ADP-margin fallback to
    break a genuine near-tie" to "resolves outright via adaptive
    resolution alone" (pick 102) or vice versa (pick 79), and pick 122's
    Stafford win went from "needed adaptive resolution to separate from
    a near-tied group" to "wins decisively, nothing to resolve." Same
    final recommendation both ways -- re-pinned below as benign mechanism
    changes, the same class of update Chunk 24/26/30/31 all made when a
    genuine value shift altered a tie WITHOUT altering the winner.

  - Picks 59/39: the WINNER changed (Zay Flowers -> Jared Goff; Kyren
    Williams -> Jared Goff) -- and this is NOT the same benign case.
    Directly confirmed Jared Goff was ALREADY the #1 league-wide-VBD
    player at both picks under the OLD raw-points logic too (pick 59:
    214.2 old vs 214.2 new, identical; pick 39: 181.5 old vs 183.3 new,
    nearly identical) -- so this isn't root-candidate selection changing.
    What changed: my roster in this real-draft replay already holds TWO
    elite QBs very early (Jalen Hurts 326.6, Lamar Jackson 306.3 --
    genuine history from the fixture, unrelated to this chunk), so a 3rd
    similarly-elite QB (Goff, 308.9) only provides marginal incremental
    STARTING value (~+2.6 pts, swapping out Jackson) despite a huge raw-
    VBD edge, while Flowers/Williams would fill a genuinely unmet WR/RB
    starting need. Under the OLD system, MCTS's rollout-simulated reward
    evidently discounted that 3rd-QB-stacking branch enough to let
    Flowers/Williams win the actual search despite trailing on raw VBD;
    under the NEW percentile-based allocation (used deep inside every
    rollout's roster-aware reward, not just the league-wide VBD calc),
    that discount is weaker, letting Goff's raw dominance flow through.
    This looks like the SAME underlying QB-elevation pathology this arc
    is fighting, resurfacing through a different pathway (rollout-level
    roster-construction reward, not the league-wide replacement-level
    path Chunk 36 traced) -- NOT confirmed to be Track B's wait-value bug,
    but a real, open side effect of THIS chunk's own fix. Deliberately
    NOT re-pinned to "Goff" here (that would be asserting he's correct
    without evidence) -- marked `xfail` instead, pending a decision in
    the follow-up planning chat on whether the roster-level degenerate
    n<=1 -> 100.0 percentile case needs its own follow-up fix. See the
    Chunk 38 report for the full evidence trail.

CHUNK 39 CORRECTION (the roster-level degenerate-percentile follow-up fix
Chunk 38 deferred: `_allocate_starters` now accepts an optional stable,
externally-computed `percentile_lookup` table -- built ONCE per
`recommend()` call against the FULL player universe via vbd.py's new
`compute_league_wide_percentiles` -- instead of recomputing percentile
from whatever tiny same-position pool happens to be on one roster in one
rollout branch; see vbd.py's own CHUNK 39 FIX docstring note): directly
confirmed the diagnosis first (not assumed) -- instrumenting a real
`recommend()` call at pick 59 found 18.3% of all roster-level QB
allocation calls during that single search hit the exact degenerate n=1
case, and the fix is independently validated correct via controlled
synthetic tests (see tests/_scratch_c39_step3_synthetic.py in the Chunk
39 report). BUT its measured effect on THIS file's 6 traced real-draft-
replay picks required real self-correction, twice, to report honestly:

An in-process check first (mis-)read pick 59 as fixed (Flowers's raw
mcts_score, 1736.7, IS now higher than Goff's, 1733.7) before a closer
look at the ACTUAL post-tiebreak recommendation order caught that Goff
still wins the FINAL recommendation regardless (a genuine near-tie, z~0.5,
that engages Chunk 24's separate, pre-existing ADP-margin tiebreak, which
promotes Goff on real-market-urgency grounds unrelated to roster fit --
a distinct, narrower open question this chunk doesn't own or fix).

Then, apparent flips at picks 79/82 (Tony Pollard -> Courtland Sutton)
were INITIALLY attributed to this chunk's fix (a plausible-sounding
story: stable percentile surfacing WR value more reliably). A rigorous
`git stash` negative control -- running this exact test file against
PURE, UNMODIFIED Chunk 38 code (this chunk's changes stashed out
entirely), against TODAY's live data -- proved that story WRONG: picks
79, 82, 39, AND 102 all show the EXACT SAME behavior under pure Chunk 38
code as under this chunk's fix (Sutton wins 79/82, Kyren Williams
resolves cleanly at 39, adaptive_resolution_applied is False at 102) --
this chunk's code changes are not the cause. This project's projections/
ADP data is live and updates over time (see projections.py/adp.py) --
the real explanation is DATA DRIFT since Chunk 38's original pins were
set in an earlier session, not any code change made here. Confirmed
further: an in-process negative control (forcing `percentile_lookup=None`
via monkeypatch, no git stash needed) at pick 59 ALSO produced BYTE-
IDENTICAL scores to the fix-active run (1733.7/1736.7 either way) --
this chunk's fix has NO measurable effect on pick 59's outcome at all,
even though the mechanism it targets is real and independently confirmed.

HONEST BOTTOM LINE for these 6 traced picks: the fix is correct and
validated in isolation (synthetic tests, direct instrumentation showing
it fires often in real rollouts), but produces ZERO measurable change to
any of these 6 specific real-draft-replay outcomes -- pick 39's
resolution and picks 79/82/102's current values are all data drift,
present identically with or without this chunk's code; pick 59 remains
unresolved (Goff still wins) with or without the fix. Re-pinned below to
match TODAY's actual data-drift-affected behavior (needed regardless of
this chunk, since the OLD Chunk-38-era pins no longer match live data
under EITHER code version) -- explicitly documented as data drift, not a
code-driven re-pin, the first time this file has needed that distinction.
Pick 59 kept `xfail`, re-reasoned to reflect the fix's real (null) effect
on this specific case rather than falsely claiming partial credit.

CHUNK 60 UPDATE -- ADP-MARGIN TIE-BREAK FIX (signed margin -> absolute
distance; see app/services/mcts.py's CHUNK 60 FIX notes). This changes
two of the pinned picks, for two DIFFERENT reasons -- both confirmed by
running a git worktree at commit 0250519 (Chunk 41, last time these were
pinned) against today's freshly-refreshed live data:

  - Pick 59: xfail REMOVED, now passes as (Zay Flowers, True, False).
    The Chunk 39 xfail above documented Goff winning via the ADP-margin
    tie-break -- which is precisely the signed-margin bug Chunk 60 fixed.
    Goff (real ADP 24.9, 34 picks overdue at pick 59) beat Flowers only
    because 24.9-62 = -37.1 is more negative than 41.8-62 = -20.2. On
    absolute distance (37.1 vs 20.2) the tie-break no longer fires and
    Flowers -- the higher raw mcts_score AND the genuine WR starting
    need -- wins outright. The "QB-elevation pathology resurfacing
    through the ADP tie-break" that Chunk 38/39 flagged at this pick is
    gone. (Still a data-fragile ~3pt near-tie at seed=1; noted on the pin.)

  - Pick 82: CODE-DRIVEN re-pin (Courtland Sutton -> Tony Pollard),
    NOT data drift. The tied group {Pollard, Sutton} is now broken by
    absolute distance to the next turn (pick 99): Pollard (ADP 82.9,
    |dist| 16.1) is promoted over the marginally-more-overdue Sutton
    (ADP 79.8, |dist| 19.2). Pre-Chunk-60 (signed), min(-16.1, -19.2)
    picked Sutton, who was already the leader, so nothing reordered.
    Both are legitimate within-noise at-risk near-ties (score 2139.5 vs
    2140.7); this is a low-stakes flip and, in isolation, signed was
    arguably marginally better here (lower ADP = likelier gone) -- but
    the aggregate multi-seed sweep in the Chunk 60 report shows the
    absolute-distance rule is net WR-positive / QB-negative across full
    drafts, and it fixes the clearly-wrong signed behavior at pick 59
    and at Chunk 41 point 2 (Maye/Adams). Flagged for the planning chat.

  - Picks 39/79/102/122: pick 102 also drifted (Matthew Stafford ->
    Sam Darnold, all three fields) but that is pure DATA drift --
    identical on the Chunk-41 commit. 39/79/122 still match their pins.

CHUNK 62 UPDATE -- BATCH-DECOUPLED SE IN _adaptively_resolve_tie (Chunk 61
root-caused "Track B" to that pass falsely resolving genuine near-ties
with an overconfident within-run Welford stderr; Chunk 62 replaces it
with a between-batch SE -- 6 independent 100-iteration batches, SE from
the scatter of the per-batch means. See app/services/mcts.py's CHUNK 62
FIX section). This moves FOUR pins here -- all CODE-DRIVEN, confirmed by a
git-stash negative control (OLD mcts.py matches every one of these on
today's data; the new estimator is the only thing that changes them). No
new failure is a Track B regression -- in every case the tied group is
dominated by would-start players and the change moves toward a
higher-value or genuinely-on-the-bubble pick:

  - Pick 59: same winner (Zay Flowers); adp_tie_break_applied False -> True.
    Honest SE keeps {Flowers, Goff} tied instead of falsely resolving to
    Flowers, so the ADP tie-break runs -- and picks Flowers anyway.

  - Pick 79: winner Courtland Sutton -> Tony Pollard. OLD falsely resolved
    to Sutton alone; honest SE keeps a 4-way tie (Pollard/Sutton/Meyers/
    RJ Harvey, ALL would-start, Pollard & Sutton dead even on score). ADP
    tie-break picks Pollard, whose real ADP (82.9) is right on the next
    turn (82). Consistent with Chunk 60's abs-distance rule.

  - Pick 82: same winner (Tony Pollard); adp_tie_break_applied True ->
    False. Pollard's lead over Sutton clears the honest SE bar, so
    adaptive resolution resolves him directly and the tie-break is
    skipped. OLD reached Pollard via the tie-break.

  - Pick 102: winner Sam Darnold -> Zach Charbonnet. This is an
    IMPROVEMENT -- OLD falsely resolved to Sam Darnold (a would_start=False
    QB with a LOWER base mcts_score than Charbonnet), the exact
    false-confidence failure Chunk 62 targets. Honest SE keeps the 3-way
    tie; Charbonnet (would_start=True RB, highest base score) stays leader.

  - Picks 39/122: unchanged, re-verified.

CHUNK 63/64 UPDATE -- pure DATA DRIFT re-pin of picks 59, 82, 102. Chunk
63's latency benchmark ran build_baseline_projections(force_refresh=True),
replacing the Aug-29 baseline_projections.json that Chunk 62 pinned
against with an Aug-30 one. The recommend() code path is byte-identical to
Chunk 62's commit (0678080) -- confirmed by a git-stash negative control
(stashing all five Chunk-64 feature files, which touch draft_live/live/the
frontend and NOTHING in recommend()'s import graph, reproduces every
drifted value exactly). 59: same winner, adp_tie_break flag drift only.
82: (Tony Pollard, T, T) -> (Courtland Sutton, T, F). 102: (Zach
Charbonnet, T, F) -> (Jordan Addison, F, F). 79/39/122 still match. This
file's pins have now drifted on 3 of the last 4 chunks that touched live
data -- flagged for the planning chat: consider loosening these
real-draft-replay params to name-only, or accepting a near-every-chunk
re-pin here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import NUM_TEAMS, ROSTER_POSITIONS
from app.services import mcts as mcts_service
from app.services.draft_state import DraftState

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chunk22_real_draft_picks.json"
MY_SLOT = 2
SEED = 1


def _load_real_picks() -> list[dict[str, Any]]:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _state_before_pick(pick_no: int, real_picks: list[dict[str, Any]]) -> DraftState:
    picks_before = [p for p in real_picks if p["pick_no"] < pick_no]
    state = DraftState.from_sleeper_picks(
        my_slot=MY_SLOT, sleeper_picks=picks_before, num_teams=NUM_TEAMS, roster_positions=list(ROSTER_POSITIONS)
    )
    assert state.current_pick_no == pick_no
    assert state.is_my_turn
    return state


# ---------------------------------------------------------------------
# The headline regression guard: pick 122's default-promotion bug.
# CHUNK 30: loosened to the actual bug signature (see module docstring) --
# the specific Jeudy/Njoku/Engram tied group no longer occurs at this pick
# with current data, but "Jeudy must never win by default" still holds and
# is still the thing worth guarding directly against real data, alongside
# the data-independent synthetic unit tests below.
# ---------------------------------------------------------------------

def test_pick_122_no_longer_promotes_unmatched_group_default_by_default(
    players_by_id: dict[str, dict[str, Any]],
) -> None:
    """
    Jerry Jeudy must never be the top recommendation here again: adaptive
    resolution correctly sheds him (a well-powered re-test found him
    significantly worse, z=18.31, than David Njoku/Evan Engram) BEFORE the
    ADP tie-break ever sees the group -- so the tie-break never gets a
    chance to promote him just for being the only candidate with real ADP
    data.
    """
    real_picks = _load_real_picks()
    state = _state_before_pick(122, real_picks)

    result = mcts_service.recommend(state, players_by_id, seed=SEED)
    top = result["recommendations"][0]

    assert top["name"] != "Jerry Jeudy", (
        f"pick 122: Jerry Jeudy must not be promoted by default just for being the sole real-ADP-matched "
        f"candidate in an otherwise-unmatched tied group -- got {top['name']} instead, or the bug has "
        "regressed if this is Jeudy again"
    )


# ---------------------------------------------------------------------
# Real-draft replay: locks in the exact per-pick behavior observed at
# seed=1 across all 6 of Chunk 25's traced decision points.
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "pick_no,expected_top_name,expect_adaptive_applied,expect_adp_tie_break_applied",
    [
        # CHUNK 60 RE-PIN -- xfail REMOVED, now passes. The Chunk 39 xfail
        # documented Jared Goff winning this pick via the ADP-margin
        # tie-break "on real-market-urgency grounds unrelated to roster
        # fit." That was exactly the SIGNED-margin bug Chunk 60 fixed:
        # Goff (real ADP 24.9, already 34 picks overdue at pick 59) beat
        # Zay Flowers (ADP 41.8) only because -37.1 is more negative than
        # -20.2. With the fix on absolute distance to the next turn
        # (Goff |24.9-62|=37.1 vs Flowers |41.8-62|=20.2), the tie-break
        # no longer fires -- Flowers, the pre-tie-break leader by raw
        # mcts_score (1736.7 vs 1733.7) and the pick that fills a genuine
        # WR starting need, wins outright. adp_tie_break_applied is now
        # False. CAVEAT: that ~3pt score gap is a data-fragile near-tie
        # (seeds 2/3 land on D'Andre Swift) -- if live data drift flips
        # Flowers/Goff back this may need re-examination, but pinning to
        # today's real seed=1 behavior is correct per this file's practice.
        # CHUNK 62 RE-PIN -- CODE-DRIVEN (git-stash negative control: OLD mcts.py
        # matches every pin below on today's data; the new batch-decoupled SE in
        # _adaptively_resolve_tie is what moves them). Same top name (Zay Flowers),
        # but adp_tie_break_applied flips False -> True: the honest between-batch SE
        # now leaves {Zay Flowers, Jared Goff} genuinely tied instead of falsely
        # resolving to Flowers, so the ADP-margin tie-break (Chunk 60, abs-distance)
        # runs -- and picks Flowers anyway (|41.8-62|=20.2 < Goff's |24.9-62|=37.1).
        # Same winner, mechanism now the designed one. See the module docstring's
        # CHUNK 62 UPDATE.
        # CHUNK 63/64 RE-PIN -- DATA DRIFT (not code-driven). Chunk 63's latency
        # benchmark called build_baseline_projections(force_refresh=True), moving
        # baseline_projections.json from the Aug-29 snapshot Chunk 62 pinned against
        # to an Aug-30 one. Same winner (Zay Flowers); adp_tie_break_applied drifts
        # True -> False (the {Flowers, Goff} near-tie now resolves via adaptive
        # resolution alone at 400 iters). Confirmed code-independent: git-stash of
        # every Chunk 64 file -> byte-identical result.
        (59, "Zay Flowers", True, False),
        # CHUNK 62 RE-PIN -- CODE-DRIVEN. Winner Courtland Sutton -> Tony Pollard.
        # OLD adaptive resolution falsely resolved this to Sutton alone; the honest
        # SE keeps a 4-way tie {Pollard, Sutton, Meyers, RJ Harvey} -- ALL four
        # would-start (not a Track B bench-over-starter case) -- and Pollard/Sutton
        # are dead even on mcts_score. Falls through to the ADP-margin tie-break,
        # which picks Pollard: his real ADP (82.9) sits almost exactly on the next
        # turn (82), |diff|=0.9, the single most on-the-bubble candidate. Consistent
        # with Chunk 60's abs-distance decision. See CHUNK 62 UPDATE.
        (79, "Tony Pollard", True, True),
        (39, "Kyren Williams", True, False),   # DATA DRIFT, not code-driven -- confirmed via git-stash negative control this pick ALSO resolves cleanly to Kyren Williams under pure Chunk 38 code today, unrelated to this chunk's fix -- see module docstring's CHUNK 39 CORRECTION. CHUNK 60/62: still matches on both OLD and new code with today's data.
        # CHUNK 63/64 RE-PIN -- DATA DRIFT (Chunk 63's force_refresh; see pick 59
        # above). Chunk 62 had this at (Tony Pollard, True, True) -- its batch-SE
        # keeps {Pollard, Sutton} tied and the abs-distance ADP tie-break picked
        # Pollard on the Aug-29 data. On the Aug-30 data the tied group still forms
        # but adaptive resolution now settles it on Sutton directly (adp_tie_break
        # False, 500 iters) -- the Chunk 62 mechanism is intact, the ADPs relative
        # to the next turn just moved. git-stash of every Chunk 64 file ->
        # byte-identical (Courtland Sutton, True, False). Both are legitimate
        # within-noise near-ties, all would-start; not a Track B regression.
        (82, "Courtland Sutton", True, False),
        # CHUNK 63/64 RE-PIN -- DATA DRIFT (Chunk 63's force_refresh). Chunk 62 had
        # (Zach Charbonnet, True, False) off a 3-way {Charbonnet, Stafford, Darnold}
        # tie. On the Aug-30 data there's no tie at all here -- Jordan Addison
        # (would-start WR) separates in the base 150 iterations (adaptive_applied
        # False, 0 adaptive iters). git-stash of every Chunk 64 file ->
        # byte-identical (Jordan Addison, False, False).
        (102, "Jordan Addison", False, False),
        (122, "Matthew Stafford", False, False),  # CHUNK 38: still resolves decisively after the base 150 iterations -- unaffected by Chunk 39. CHUNK 60/62: re-verified, still matches under today's data.
    ],
)
def test_adaptive_resolution_replay_matches_expected_behavior(
    pick_no: int,
    expected_top_name: str,
    expect_adaptive_applied: bool,
    expect_adp_tie_break_applied: bool,
    players_by_id: dict[str, dict[str, Any]],
) -> None:
    real_picks = _load_real_picks()
    state = _state_before_pick(pick_no, real_picks)

    result = mcts_service.recommend(state, players_by_id, seed=SEED)
    top = result["recommendations"][0]

    assert top["name"] == expected_top_name, (
        f"pick {pick_no}: expected top recommendation {expected_top_name}, got {top['name']}"
    )
    assert result["adaptive_resolution_applied"] is expect_adaptive_applied
    assert result["adp_tie_break_applied"] is expect_adp_tie_break_applied


def test_adaptive_resolution_can_stop_early_before_the_iteration_cap(
    players_by_id: dict[str, dict[str, Any]],
) -> None:
    """
    CHUNK 30: re-pinned to pick 59. CHUNK 63/64: xfail REMOVED -- it was
    XPASSing. On the Aug-30 data, pick 59's adaptive resolution genuinely
    stops early (400 of the 600-iteration budget at seed=1), so this pick
    once again demonstrates early-stopping directly, which is the whole
    point of this test. (It XFAILed from Chunk 60-62 because the tie ran
    the full budget then; it's data-dependent whether a given near-tie
    separates within budget, and this one currently does.)
    """
    real_picks = _load_real_picks()
    state = _state_before_pick(59, real_picks)

    result = mcts_service.recommend(state, players_by_id, seed=SEED)

    assert result["adaptive_resolution_applied"] is True
    assert 0 < result["adaptive_iterations_used"] < mcts_service.ADAPTIVE_RESOLUTION_MAX_ITERATIONS, (
        f"expected adaptive resolution to stop early (before the "
        f"{mcts_service.ADAPTIVE_RESOLUTION_MAX_ITERATIONS}-iteration cap) once pick 59's group resolved, "
        f"got {result['adaptive_iterations_used']} iterations used"
    )
