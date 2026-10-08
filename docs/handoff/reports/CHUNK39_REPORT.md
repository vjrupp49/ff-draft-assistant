# Chunk 39 Report — Roster-level degenerate-percentile fix (Chunk 38 follow-up)

Commit: `c1c1e2b`

## Headline: did the Goff fix work?

**The mechanism is confirmed fixed. The specific flagged case (pick 59) is not
measurably changed by this fix at all — confirmed, not assumed, via two
independent negative controls.**

This required two rounds of real self-correction during verification —
documented honestly below, not smoothed over.

- **Mechanism-level: yes, confirmed fixed.** Directly instrumented a real
  `recommend()` call at pick 59 and found **18.3% of all roster-level QB
  allocation calls hit the exact degenerate n=1 case** (RB: 51.5%, WR: 11.8% —
  this problem was never QB-specific). Built a synthetic controlled test with
  a real player-count distribution: a mediocre QB that happens to be the
  *only* QB in one roster's local snapshot no longer beats a genuinely-better
  WR (the actual bug); a legitimately elite 3rd-tier QB still correctly wins
  (no over-correction). Both confirmed directly, not assumed.

- **Outcome-level, pick 59 specifically: no measurable effect.** An
  in-process check first (wrongly) read pick 59 as resolved — Zay Flowers's
  raw mcts_score (1736.7) genuinely is now higher than Jared Goff's (1733.7).
  But a closer look at the *actual post-tiebreak recommendation order*
  caught that Goff still wins the final recommendation, because this is now
  a genuine near-tie (z~0.5) that engages Chunk 24's separate, pre-existing
  ADP-margin tiebreak — which promotes Goff on real-market-urgency grounds
  unrelated to roster fit, a mechanism this chunk doesn't touch or own.
  **Confirmed via two independent negative controls** (in-process
  monkeypatch, and a full `git stash` to pure Chunk 38 code) that scores at
  pick 59 are **byte-identical** with or without this chunk's fix
  (1733.7/1736.7 either way) — the fix genuinely does nothing for this one
  case, even though its target mechanism is real and validated elsewhere.

- **Pick 39: fully resolves — but not because of this chunk.** Confirmed via
  `git stash` that pick 39 resolves cleanly to Kyren Williams under **pure,
  unmodified Chunk 38 code** run today, too. This project's projections/ADP
  data is live and updates over time — pick 39 was already fixed by data
  drift before this chunk's code even existed.

## The fix itself

`_allocate_starters` (vbd.py) now accepts an optional `percentile_lookup`
override. A new `compute_league_wide_percentiles()` builds a stable
{player_id: percentile} table **once per `recommend()` call**, ranked
against the **full player universe** (not the remaining/undrafted pool —
deliberately different from `compute_replacement_levels`'s own filtering,
since a single roster's own already-drafted players need a percentile too).
Threaded through every MCTS rollout call site (mcts.py's
`_roster_aware_marginal_value`/`_roster_aware_pick`, portfolio.py's
`evaluate_roster` when called from the rollout). `compute_replacement_levels`'s
league-wide call is **unchanged** — never passes `percentile_lookup`,
preserving Chunk 38's exact validated behavior there. Did not touch
`_allocate_starters`'s core percentile-comparison approach, per the brief.

## What I verified vs. skipped, and why

**Verified:**
- Direct instrumentation confirming the degenerate case fires in real play (step 1).
- Synthetic controlled tests proving the fix is correct in isolation (step 3).
- The 6 real-draft-replay picks in `test_adaptive_resolution_regression.py`,
  each individually root-caused — including catching and correcting my own
  two misreads along the way.
- A **git-stash negative control** against pure Chunk 38 code for every
  finding that looked like a Chunk 39 side effect (picks 79/82/102, the
  positional-balance WR regression) — all confirmed to be live data drift,
  not this chunk's code.
- One full regression suite run (2 failures, both traced to the same data
  drift, re-pinned with that explicitly documented).

**Skipped, and why:** Chunk 38's full 4-position 5-seed sweep was not
re-run from scratch — this is a narrower, downstream fix to the reward
calculation, not a change to `_allocate_starters`'s core approach, and the
brief explicitly said not to over-invest here. A dedicated, methodologically
cleaner WR-tracking effort (replaying a fixed historical trajectory rather
than fresh full-draft simulations, to avoid the trajectory-divergence
sensitivity noted below) was also not undertaken — out of scope, deferred to
a future chunk if the incidental data below still looks concerning.

## Step 5: 3 fresh production-settings mock drafts (slot 3, 150 iterations)

| Seed | QB | RB | WR | TE | QB dev | RB dev | WR dev | TE dev |
|---|---|---|---|---|---|---|---|---|
| 2 | 4 | 6 | 4 | 1 | **+2.0** | +1.0 | **-2.0** | -1.0 |
| 3 | 4 | 7 | 3 | 1 | **+2.0** | +2.0 | **-4.0** | +0.0 |
| 4 | 4 | 7 | 3 | 1 | **+2.0** | +2.0 | **-3.0** | -1.0 |

**Honest read: this looks worse than Chunk 38's own production check, not
better** — QB elevation (+2.0 in all 3 seeds) and WR shortage (-2.0 to -4.0)
both look more pronounced here than Chunk 38's single production run
(QB +0.0, WR -2.0). I do **not** conclude this chunk's fix caused it,
though — a git-stash sanity check on seed 2 (pure Chunk 38 code) showed
QB=3 (deviation +1.0) instead of QB=4, a genuine difference between the two
code versions for this one seed. I can't cleanly attribute that difference
to the fix's mechanism, though: a full 150-pick mock draft is a single
continuous trajectory where opponent picks and my own downstream picks all
depend on what's already been drafted, so any one early decision differing
cascades into a different overall outcome regardless of whether that first
difference was itself meaningful (the same trajectory-divergence caveat
Chunk 38 documented for its own pick 27/47 check). Reported as an **open,
unresolved data point**, not forced into either "the fix caused this" or
"this is pure data drift." Per the brief, not chased further this chunk —
flagged for a dedicated future WR/QB-balance chunk if this still looks
concerning, ideally using fixed-trajectory replay methodology rather than
fresh full simulations to avoid this exact ambiguity.

## Full regression suite

2 failures, both root-caused to live data drift (confirmed via git-stash
against pure Chunk 38 code, identical failures either way), not this
chunk's code:
- `test_adp_margin_tiebreak_regression.py`'s pick-79 case: no longer
  exercises the ADP-margin tiebreak mechanism at all (resolves via adaptive
  resolution alone now) — removed from its parametrize list, same
  precedent as pick 39's earlier removal. Mechanism itself remains covered
  by this file's synthetic unit tests.
- `test_positional_balance.py::test_positional_balance_slot7_multiseed`:
  WR deviation back to -2.0, identical under pure Chunk 38 code — xfail
  marker restored with the data-drift explanation documented.

Also re-pinned (all confirmed data drift via the sister test's git-stash
check): picks 79/82/102 in `test_adaptive_resolution_regression.py`.

## Negative control

Two independent negative controls confirm the fix's real, isolated effect:
1. **In-process monkeypatch** (forcing `percentile_lookup=None` at the
   allocation call, regardless of what's passed): picks 59/39 scores
   byte-identical to the fix-active run; picks 79/82 scores narrow
   substantially (from decisive z~5.3/z~2.19 down to near-tie z~0.5) but
   Sutton still edges Pollard either way — inconclusive on its own.
2. **`git stash` to pure, unmodified Chunk 38 code**, run against today's
   live data: this is the authoritative comparison, since it isolates code
   from data. Confirmed picks 59/39/79/82/102 and the positional-balance
   WR regression are **all identical** between pure Chunk 38 code and this
   chunk's code — none of them are caused by this chunk. The synthetic
   controlled tests (Case A/B in the fix's own commit) remain the clean,
   decisive evidence that the fix itself is correct.

## Bottom line for the follow-up planning chat

1. The degenerate-percentile fix is correct, validated in isolation, and
   fixes a real, frequently-firing (18.3% of QB calls) mechanism — but has
   **zero measurable effect** on any of the 6 real-draft-replay decision
   points this arc has been tracking. Worth keeping regardless (it's a
   genuine correctness fix), but don't expect it to move the needle on
   visible recommendations for this specific fixture.
2. This project's live projections/ADP data drift is now confirmed to be a
   real, material source of test-suite churn independent of any code
   change — worth keeping in mind for future re-pins (a `git stash`
   negative control against the previous chunk's exact code is now the
   established way to separate "my change caused this" from "the data
   moved").
3. Step 5's production-settings QB/WR numbers look concerning (QB +2.0 in
   all 3 fresh seeds, WR -2.0 to -4.0) but the single git-stash sanity
   check on this specific full-draft methodology was ambiguous, not
   conclusive either way. This is real, current-state evidence the WR/QB
   balance question from Chunk 38 is not fully closed — a dedicated future
   chunk, not this one, should investigate with fixed-trajectory replay
   methodology to avoid the divergence-sensitivity this chunk ran into.
