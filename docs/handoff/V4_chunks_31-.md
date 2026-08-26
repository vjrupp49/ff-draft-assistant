# V4 - Draft Builder, Chunks 31-

*Living document — add to project knowledge alongside the overview doc, Brainstorm Session, and V1-V3 chunk summaries. Unlike V1-V3 (written as one retrospective summary at the end of a session), this doc is meant to be appended to continuously, run by run, as Chunk 31+ reports come back. Working model unchanged: Claude Code executes and reports on the user's machine; the planning chat (this project) scrutinizes each report and writes the next scoped prompt. Root-cause before fixing, negative control every time — see `claude/nuances-audit-2026-08-15.md` for the full discipline history if a future session needs the "why" behind that bar.*

---

## Chunk 31 — CLOSED, 2026-08-15 (all 4 tasks complete)

**Commit:** `b811770` — "Chunk 31 (partial): QB/WR sanity check + LA/LAR team_changed fix" on `main` (task 3's live draft ran as a separate follow-up session same day, no additional commit needed since it was observation-only).

**Correction to this doc's earlier entry:** task 3 was initially logged as "deferred to 2026-09-07" based on checking the real league's official `draft_id`, which is genuinely `pre_draft` until then. That was a mix-up, not a real deferral — task 3 was always meant to be a **separate mock/practice draft** (same pattern as the live dry runs in Chunks 12, 19, 22), not the real league draft. The mock draft ran the same day, completed, and its results are below. **Lesson for future sessions:** "the live dry run" and "the real scheduled league draft" are two different `draft_id`s — don't conflate them again.

**Important scheduling finding (still stands):** the real league draft (`1389755334746202113`) is scheduled **2026-09-07** — closes the overview doc's original, long-open "draft date" question.

**Starting-state note worth remembering for future handoffs:** at the start of this chunk, `git status` showed an uncommitted, untested LA/LAR fix already sitting in the working tree from a prior session — always check `git status` for work-in-progress before assuming a fresh start, not just `git log`.

### Task 1 — QB/WR sanity check of the Chunk 30 nflverse migration (diagnostic only, no code change)

Independently re-verified the schema migration against QB/WR-relevant columns (Chunk 30 only spot-checked RB/TE). All core columns present and unchanged in the new schema; only `interceptions`→`passing_interceptions` and `team`→`recent_team` needed remapping, matching Chunk 30's original claim. Two apparent anomalies (A.J. Brown team=NE, Rashid Shaheed showing 18 games played) both traced to real, correctly-handled trade edge cases, not bugs. No code change.

### Task 2 — LA/LAR team-abbreviation fix (root-caused, verified, negative-controlled)

Root cause: nflverse uses `"LA"` for the Rams, Sleeper uses `"LAR"` — plain string equality in `team_changed()` treated every current Rams player as a role change. Fixed, unit- and pool-verified (Nacua/Stafford/Kyren Williams no longer wrongly flagged; genuine trades like Tyler Scott still correctly flagged), negative-controlled (`git stash` reproduced the bug, `git stash pop` restored the fix). Ripple effect traced and fixed: Kyren Williams' projection was wrongly suppressed 277.8→177.3 by the bug; two dependent regression tests repinned with justification, matching established precedent (Chunk 26). Final suite: 50 passed, 1 skipped, 2 xfailed (TE-glut, untouched), zero unexplained failures.

### Task 3 — Live mock/practice draft: COMPLETE, real findings

Ran a full mock draft through the live app (10 teams, "my" roster at slot 3), following the app's own Draft Score recommendations pick-for-pick. Final roster:

| Pick | Rd | Pos | Player |
|---|---|---|---|
| 3 | 1 | QB | Josh Allen |
| 18 | 2 | RB | Derrick Henry |
| 23 | 3 | QB | Jalen Hurts |
| 38 | 4 | RB | Kyren Williams |
| 43 | 5 | WR | Davante Adams |
| 58 | 6 | TE | Travis Kelce |
| 63 | 7 | RB | D'Andre Swift |
| 78 | 8 | RB | Tony Pollard |
| 83 | 9 | TE | Jake Ferguson |
| 98 | 10 | TE | Mark Andrews |
| 103 | 11 | RB | Tyrone Tracy |
| 118 | 12 | TE | Juwan Johnson |
| 123 | 13 | TE | Dalton Schultz |
| 138 | 14 | WR | Khalil Shakir |
| 143 | 15 | RB | Alvin Kamara |

**Finding A — TE-glut bug reproduced live, empirically confirmed, still unfixed.** Final roster: 5 TEs, 2 WRs. Every other team in this draft finished with exactly 2 TEs — isolated to this app's own MCTS/portfolio engine, matching what the Task 4 diagnosis and the 5-seed synthetic sample both predicted. This is now confirmed in a real full draft, not just simulation.

**Finding B — the original Kamara/Conner over-reach problem is genuinely resolved.** Kamara went at pick 143 (real ADP 152.3 — essentially on time), Conner at pick 149 (round 15, dead last). Neither was reached for. Chunk 30's stale-data fix and Chunk 31's LA/LAR fix are doing their job on this specific, historically-diagnosed failure mode.

**Finding C — NEW, not previously diagnosed: a broader "early-reach vs. ADP" pattern starting around round 6.** User's direct observation reviewing the draft: from roughly round 6-7 onward, several picks were players sitting 20+ spots below (worse than) their real ADP relative to the current pick number — i.e., players unlikely to be gone if the app had waited 1-2 more rounds. User's framing, which is the correct standard here: even if the model's player-value ranking is right, if a player has a high (~90%+) probability of surviving to the next turn, taking them now instead of a scarcer alternative is a wait-value/sequencing error, not a valuation error. This is conceptually the same category of reasoning MCTS's opponent-model-driven "wait value" logic (referenced as already existing architecturally per Chunk 21, and directly diagnosed once before for a single pick in Chunk 23) is supposed to handle — but this is the first time it's been observed as a **pattern across a whole draft**, not a single flagged pick. Not yet root-caused. Open question going in: is this the *same* mechanism as Finding A (i.e., most of the "reaches" are actually the TE picks — Ferguson/Andrews/Johnson/Schultz — and fixing the TE-glut discount would resolve most of this too), or a distinct, broader wait-value problem across positions that needs its own fix. **Diagnosis needed before any fix — see Chunk 32 below.**

**Housekeeping:** temporary `SLEEPER_DRAFT_ID` config override reverted to the real draft ID, dev server stopped cleanly, scratch scripts removed, repo confirmed clean via `git diff`/`git status`. Found and logged (not fixed, out of scope): a broken duplicate `.claude/launch.json` in the outer folder that crashes the app if used to launch it — flag this if the app ever "won't start" mysteriously in a future session.

### Task 4 — TE-glut `xfail`: is it McBride-specific or a broader tier effect?

**Conclusively a broader elite-TE tier effect, not McBride-specific** — confirmed twice over: once synthetically (5-seed mock, two seeds drafted 4 TEs each with zero McBride involvement) and now again empirically in Task 3's real full draft above. Likely lever: re-calibrate `portfolio.py`'s `FLEX_CONCENTRATION_DISCOUNT_BASE={"TE": 0.5}` / decay 0.6 (calibrated pre-Chunk-30, against now-stale data) against current data. Diagnosed, not remediated.

### Still open, carried forward into Chunk 32+

- **TE-glut fix** — root cause understood, fix not yet built. Likely lever identified above.
- **NEW: broad early-reach-vs-ADP pattern (Finding C)** — real, user-observed, not yet root-caused. Needs its own diagnostic pass using this draft's full pick log before any fix is scoped, per this project's standing discipline.
- Broken duplicate `.claude/launch.json` in the outer folder — logged, not fixed.
- `opponent_model.py` performance — still untouched since first flagged in Chunk 14.
- QB/WR only got a lighter sanity check than RB/TE's Chunk 28-30 depth — no anomalies found, but worth remembering the bar was lower.

---

## Chunk 32 — CLOSED, 2026-08-15 (diagnostic only, zero code changes)

**Bottom line: it's a mix, not one mechanism.** Of the 15 picks, 6 showed a 20+ reach vs. real market ADP. 5 of those 6 are TE (Kelce +79.2, Ferguson +66.6, Schultz +43.1, Johnson +42.1, Andrews +28.6 — all already-understood TE-glut mechanism). **The 6th — Tyrone Tracy, RB, pick 103, +57.7 — is a genuinely separate, newly-confirmed wait-value bug**, unrelated to `FLEX_CONCENTRATION_DISCOUNT_BASE` (which is TE-only and never touches RB/WR code paths). Nothing sat marginally under the +20 threshold — next-closest unflagged pick was Kamara at +9.3, so this isn't a fuzzy cutoff artifact.

**Spec correction worth remembering:** the Chunk 32 prompt's formula (`gap = pick_number − real_adp`, "positive = reached for") was internally inverted — that literally produces a large *negative* number for a reach. Correct formula, used instead: `reach = real_adp − pick_number ≥ 20`. Flag this if writing ADP-gap logic again in the future.

### The Tracy-over-Meyers case, instrumented in full

Reconstructed the exact pre-pick-103 draft state and re-ran `mcts.recommend()` directly — Tracy was genuinely the model's own top pick, not a user deviation from the recommendation.

| Candidate | Pos | mcts_score | Real ADP | Margin to user's next turn (pick 118) | Would start now? |
|---|---|---|---|---|---|
| **Tyrone Tracy** | RB | 2522.4 ± 1.8 | 160.7 | +42.7 (totally safe) | **No — 5th RB, pure bench** |
| Jakobi Meyers | WR | 2496.4 ± 8.8 | 101.7 | −16.3 (genuinely at risk) | **Yes — fills a real, thin WR need** |
| George Kittle | TE | 2451.1 ± 3.0 | 125.7 | +7.7 | Yes |

Would-start status confirmed directly via `vbd.allocate_roster_starters_with_flex_ranks` against the actual roster at that point (already 4 RB / 3 TE / 1 WR). Survival probabilities confirmed empirically, not assumed — 500 Monte Carlo replays using the exact same `opponent_model.sample_pick` function MCTS's own rollouts draw from, picks 104→118: **Meyers 66.2% survival (~34% real risk of being gone), Tracy 100% survival, Kittle 89.4%.**

So the model's own opponent-model data confirms Meyers was genuinely at risk and Tracy genuinely safe — and it still took the 100%-safe bench player over the at-risk starter-value one, with real statistical conviction (score gap z ≈ 2.9, not noise). This is not explainable as "correctly discounting a lower-value candidate" — Meyers was the higher-value, roster-need-filling pick by VBD, starter-status, and risk simultaneously, and still lost.

### Root cause: not yet located — only a hypothesis

Claude Code's own honest flag: it did not trace this to a specific line. Best hypothesis for where to look first: the rollout's backfill assumption in `_roster_aware_pick`, or how the tree branch after each root candidate gets evaluated — but that's unverified, not a diagnosed root cause. **Explicitly recommended before building any fix:** determine whether this is a one-off (n=1 in this draft) or systemic, by instrumenting 2-3 more real decision points the same way (empirical survival rate vs. would-start status vs. mcts_score), before committing to a fix design. This mirrors the exact discipline this project already learned the hard way in the Chunk 24→25→26 tie-break saga — don't ship a fix off one example.

### Conclusion for what Chunk 33+ needs to be

**Two separate fixes, not one:**
1. **TE glut** (5 of 6 flagged picks) — root cause already understood (Chunk 20/31), fix not yet built: recalibrate `FLEX_CONCENTRATION_DISCOUNT_BASE`/decay against current data. Ready to scope now.
2. **A real wait-value/backfill gap** (Tracy-over-Meyers) — real, evidenced, but not yet root-caused to a specific mechanism, and not yet known to be systemic vs. a one-off. Needs a widened diagnostic pass (2-3 more instrumented decision points) *before* a fix gets designed — do not fix off n=1.

Housekeeping: zero code changes, repo clean, real league draft (`1389755334746202113`) confirmed still untouched/`pre_draft` throughout.

---

## Chunk 33 (Track A: TE-glut recalibration) — CLOSED, 2026-08-15/16 (fix verified, not yet committed)

**Headline result: TE glut is fixed.** Full 15-seed regression suite: TE deviation from league median is exactly **0.0** (was +2.0/+3.0 at Chunk 30/31/32). Fresh internal mock draft (slot 3, production settings, 150 MCTS iterations): final roster **QB=2 / RB=6 / WR=5 / TE=2** — a complete flip from Chunk 31's broken 5 TE/2 WR roster, now squarely in league range (other teams: 1-4 TE, median 2-3).

**Mid-chunk scoping correction (as previously logged):** the originally-scoped constant, `FLEX_CONCENTRATION_DISCOUNT_BASE`/decay, was swept 0.5→0.1 and produced **zero effect** — root-caused live to `flex_rank>=2` almost never firing (only 1 TE per roster typically reaches flex-starter status). The real driver was a different, previously-untouched constant: `BENCH_DISCOUNT_DECAY["TE"]`, which had been left **flat (1.0)** since Chunk 10 deliberately chose not to apply the QB/RB-style rank-decay fix to TE at the time. User approved widening Track A to this constant.

**Final fix:** `BENCH_DISCOUNT_DECAY["TE"]`: 1.0 → **0.3** (rank-decaying, same `BASE × DECAY^(rank-1)` formula proven at QB/RB in Chunk 10). `BENCH_DISCOUNT_BASE["TE"]` (0.25) and `FLEX_CONCENTRATION_DISCOUNT_BASE`/decay (0.5/0.6) both **left untouched** — a deliberate tightening of `FLEX_CONCENTRATION` alongside the bench fix was tested and rejected because it pushed RB into a new +2.0 overcorrection, the same failure mode Chunk 20 already hit once with a generic discount.

**Calibration sweep (5-seed, methodology matching Chunk 31 task 4):**

| `BENCH_DISCOUNT_DECAY["TE"]` | TE median | TE dev | WR dev | RB dev |
|---|---|---|---|---|
| 1.0 (baseline) | 4 | +2.0 | -3.0 | +1.0 |
| 0.7 | 3 | +1.0 | -3.0 | +1.0 |
| 0.5 | 3 | +1.0 | -2.0 | +1.0 |
| **0.3 (chosen)** | 2 | **0.0** | -2.0 | +1.0 |
| 0.15 | 2 | 0.0 | -2.0 | +1.0 (no further gain) |

**Regression suite:** one real failure found and root-caused, not blind-repinned — `test_adaptive_resolution_regression.py` pick 82 flipped Kelce→Pollard. Instrumented directly: pre-fix, MCTS's rollout continuation could stockpile bench TEs at a flat discount regardless of count, inflating a "take Kelce now" branch's average reward; post-fix that speculative stacking is properly discounted, correctly shifting the pick toward Pollard (real ADP 83.4, genuinely tight margin, z≈8, not noise). Confirmed as the fix's **intended** effect, not a side-effect bug — repinned with a documented Chunk 33 correction. Both `test_positional_balance.py` xfails re-verified at full sample size (not just the 5-seed sweep): TE genuinely resolved (0.0 dev both slot-7 and slot-sensitivity variants), xfail reasons updated to correctly point at the pre-existing WR shortage instead of TE. Final suite: **50 passed, 1 skipped (pre-existing), 2 xfailed (now correctly attributed to WR), 0 unexplained failures.**

**Negative control:** confirmed (revert → glut reappears, restore → fixed again) — with one honest wrinkle: the calibration work spanned long enough wall-clock time that the ADP/projection cache crossed its 24h auto-refresh threshold mid-chunk, so the very first before/after comparison and the later verification steps technically used two different data snapshots. Re-ran a clean apples-to-apples A/B on the stable, current dataset specifically to confirm the calibration choice still holds on data that didn't move mid-comparison — it does (TE +1.0→0.0 on fresh data, still full parity, smaller absolute gap than the original +2.0→0.0 only because the underlying data shifted, not because the fix weakened). Worth remembering for any future long-running (>24h) calibration chunk.

**Elite-TE sanity check:** McBride as sole starter-slot TE — `raw_mean` and `contributed_mean` identical (328.1), zero discount applied. Confirms the fix is surgical to bench-stacking, not a blanket TE-value penalty.

**Still open, not touched by this chunk:**
- **WR shortage** (-2.0 deviation on both positional-balance tests) — real, pre-existing since Chunk 30 (originally noted as a secondary xfail alongside the TE glut), improved somewhat by this fix's ripple effect but not resolved, and not this chunk's target. Needs its own diagnostic chunk.
- **Track B (Chunk 32's wait-value/backfill bug, Tracy-over-Meyers)** — still completely untouched, exactly as instructed.
- Broken duplicate `.claude/launch.json`, `opponent_model.py` performance — both still carried forward, untouched.

**Housekeeping:** 3 files changed (`app/services/portfolio.py`, `tests/test_adaptive_resolution_regression.py`, `tests/test_positional_balance.py`), scratch cleaned, real league draft confirmed untouched throughout. **Committed as `c9e452f`.**

---

## Chunk 34 (Track B widening + WR-shortage hypothesis test) — CLOSED, 2026-08-16 (diagnostic only, zero code changes)

**Question asked:** does the Tracy/Meyers wait-value bug (Chunk 32) systemically explain the pre-existing WR shortage (still open after Chunk 33)?

**Answer: No.** Confirmed **(b)** from the original framing — real and recurring, but too rare to be the systemic cause. Treat as two separate problems.

**The wait-value bug is now confirmed 3 times total, not a fluke:** instrumented all "my"-turn decision points across 7 full mock drafts (slot 7, seeds 1-7) — 65 total points where a `would_start=True` WR was passed over. Applying the Tracy/Meyers criterion strictly (bench-tier winner + genuinely-at-risk WR [survival ≤80%] + statistically confident gap), only **2 of 65 (~3%)** qualify, across **2 of 7 (~29%)** drafts:

| Seed | Pick | Taken (bench-tier) | WR passed over | WR survival | Gap | z |
|---|---|---|---|---|---|---|
| 3 | 107 | Javonte Williams (RB) | Jakobi Meyers | 77.4% | +132.1 | 10.73 |
| 6 | 87 | Lamar Jackson (QB) | Courtland Sutton | 76.0% | +75.8 | 2.95 |

Notably **Jakobi Meyers is the same player** flagged in the original Chunk 32 case — now caught by this exact bug pattern a second time in a fully independent draft. Both matches are real and even stronger than the original (z≈2.9). But at ~3% of flagged points / ~29% of drafts, this is an order of magnitude too infrequent to explain a WR deviation present in *every* seed of the positional-balance suite since Chunk 30.

**Breakdown of the other 63 flagged points, for the record:** ~40 were legitimate value wins (taken candidate was itself `would_start=True`, beating the WR by a real, defensible margin — not a bug). ~15 were near-zero/negative gaps resolved by existing tie-break/adaptive-resolution mechanics, not confident wrong answers. ~8 had a bench-tier winner but the WR was actually safe (survival ≥93%) — superficially similar shape, not a real wait-value mistake. One additional point (seed 5, pick 74) is worth remembering separately: Courtland Sutton at just 16.2% survival (acute risk) got no confident preference either way (gap only +3.6, within noise) — not a confirmed wrong answer, but a **missed-urgency** near-miss worth keeping in mind whenever the wait-value bug eventually gets a real fix designed.

**A concrete, evidenced (but unverified) lead for the real WR-shortage cause:** checked whether WR has a stale, never-recalibrated constant the way TE did pre-Chunk-33. It does:

```
BENCH_DISCOUNT_BASE  = {"QB": 0.15, "RB": 0.35, "WR": 0.20, "TE": 0.25}
BENCH_DISCOUNT_DECAY = {"QB": 0.5,  "RB": 0.7,  "WR": 1.0,  "TE": 0.3}
```

WR's bench-value floor (0.20) is 75% lower than RB's (0.35) and lower than TE's (0.25, even post-Chunk-33), and WR still carries the same flat `decay=1.0` TE had before this week's fix — set back at Chunk 9/10 under "no evidence of a problem, don't touch it," never revisited since. This is a plausible driver of the ~40 "legitimate value win" cases where RB/QB/TE depth beat WR depth — a genuine **valuation asymmetry**, not a wait-value/sequencing problem. Not calibrated or touched this chunk — same epistemic status Track B's original lead had before this chunk widened it: evidenced, not yet verified.

**Conclusion for Chunk 35:** two independent real issues, not one. (1) The wait-value/backfill bug — real, now n=3, not urgent for the WR shortage specifically, needs its own eventual fix. (2) A likely WR-specific bench-valuation asymmetry (`BENCH_DISCOUNT_BASE["WR"]` probably too low relative to RB/TE, `BENCH_DISCOUNT_DECAY["WR"]` still flat) — the better candidate for the actual WR shortage, and the natural next chunk: same calibration shape as Chunk 33 Track A.

Housekeeping: zero code changes, scratch cleaned, real league draft confirmed untouched throughout.

---

## Chunk 35 — CLOSED, 2026-08-16 (diagnostic only, hypothesis refuted, zero code changes)

**Bottom line: REFUTED for its stated purpose.** `BENCH_DISCOUNT_BASE`/`DECAY["WR"]` is real and does move individual late-round bench-tier decisions, but swept `BENCH_DISCOUNT_BASE["WR"]` from 0.20 (current) all the way to 0.60 (3x — well past RB's own 0.35) and the aggregate WR deviation metric **never moved off -2.0, not once, at any point in the sweep.** Same shape of dead-end as Chunk 33's `FLEX_CONCENTRATION_DISCOUNT` — except this time the real cause turned out to be a level deeper than `portfolio.py` entirely. No code changed.

**Step 1 sanity check, done properly before the full sweep:** first tested on 4 of Chunk 34's "both-would-start" cases — zero movement, as expected (bench discount can't affect a decision where neither candidate is bench). Retested on real late-round bench-tier decisions instead and got real movement (two picks flipped toward WR) — confirmed the constant *is* load-bearing for individual decisions, which is exactly why it was worth running the full sweep rather than dismissing it after the first null result.

**Full sweep (5-seed, same methodology):**

| `BENCH_DISCOUNT_BASE["WR"]` | WR median | WR dev | RB dev | TE dev | QB dev |
|---|---|---|---|---|---|
| 0.20 (baseline) | 4 | **-2.0** | +1.0 | 0.0 | +1.0 |
| 0.25 | 4 | **-2.0** | +1.0 | 0.0 | +1.0 |
| 0.35 (= RB parity) | 4 | **-2.0** | +1.0 | -1.0 | 0.0 |
| 0.60 (3x extreme) | 4 | **-2.0** | +1.0 | +1.0 (new, unflagged but trending) | 0.0 |

WR median never left 4 across the entire range; at the extreme end TE started drifting toward a *new* deviation for zero WR benefit — this constant doesn't just fail to help, it starts creating collateral risk at high values.

**Root cause, found and structurally confirmed:** traced into `vbd.py`'s `_allocate_starters` — the function deciding who wins a FLEX/SUPER_FLEX slot:
```python
combined_pool.sort(key=lambda p: p["projected_points"], reverse=True)
```
**Starter allocation is decided by raw `projected_points` only.** Neither `BENCH_DISCOUNT` nor `FLEX_CONCENTRATION_DISCOUNT` is even in scope at that point — both only apply *after* starter/bench status is already settled, purely for downstream roster valuation. Whether a WR wins a starting slot in the first place is a pure raw-points contest against RB/QB/TE, untouchable by any bench-value tuning. This is why the sweep showed zero movement even at 3x the original constant.

**New, separate anomaly surfaced (not investigated further, out of this chunk's scope):** one sweep seed (seed 3) stayed frozen at exactly WR=2 across every value tested — investigated directly, and that roster had drafted **5 QBs** (rounds 3, 5, 6, 7, 9). Unexplained on its own terms — QB gluts were thought closed out by Chunk 10's bench-discount fix. Flagged for follow-up.

**Conclusion for the next chunk:** the real WR-shortage root cause is upstream of any `portfolio.py` discount constant — either `vbd.py`'s raw-points-based FLEX allocation logic itself, or further upstream still in `projections.py`'s actual WR-vs-RB/QB/TE point estimates. This needs a genuinely different kind of diagnostic (compare raw point distributions across positions at the relevant draft depth) than "recalibrate a constant."

Housekeeping: zero code changes, scratch cleaned, real league draft confirmed untouched throughout.

---

## Chunk 36 — scoped, combined hypothesis (not yet sent to Claude Code)

**Working theory connecting two open threads:** Chunk 35's root-cause finding (`_allocate_starters` picks FLEX/SUPER_FLEX winners by raw `projected_points` alone, with zero positional-scarcity or need-awareness) could plausibly explain **both** the WR shortage *and* Chunk 35's seed-3 5-QB anomaly at once, not just WR. This is a SUPERFLEX, TE-premium league — the same "raw QB point inflation" mechanism that caused the original Chunk 9 QB glut (fixed at the time only via bench discount, never touched at the *starter-allocation* layer) could still let QB systematically out-compete WR for FLEX/SUPER_FLEX slots on raw points alone, in both directions: squeezing WR out of starting lineups (feeding the shortage) and letting QB over-claim starter slots in specific rollouts (feeding seed 3's anomaly) — with the existing bench discount powerless to stop either, since it never touches this decision.

**Scope:** diagnostic only.
1. Compare raw `projected_points` distributions for WR vs. QB/RB/TE at the specific draft depths where FLEX/SUPER_FLEX slot competition actually happens (not top-of-draft) — is there a structural, SUPERFLEX-driven gap that systematically favors QB/RB/TE over WR at that raw-points contest, independent of any discount?
2. Directly check whether `_allocate_starters`'s pure-raw-points sort is the actual mechanism behind seed 3's 5-QB roster (same instrumentation approach as prior chunks — reconstruct the relevant decision points and check what a positionally-aware allocation would have done differently).
3. Conclusion needed: is this one root cause explaining both symptoms (in which case a single, carefully-scoped fix to `_allocate_starters` — e.g., positional-scarcity-aware tie-breaking, not a blanket QB penalty — is the right target), or do WR-shortage and the QB anomaly turn out to be unrelated after all (in which case scope two separate follow-up chunks)?

**Not yet sent to Claude Code.**

---

## Chunk 36 — CLOSED, 2026-08-16 (diagnostic only, zero code changes — plus a major secondary finding)

**Bottom line: hypothesis (a) confirmed for the structural WR-shortage mechanism, plus a real, separate, previously-unknown harness bug discovered along the way.**

**Step 1 — structural raw-points gap, cleanly confirmed:**

| Rank | QB | RB | WR | TE |
|---|---|---|---|---|
| 1 | 372.9 | 349.2 | 328.2 | 329.3 |
| 10 | **284.2** | 247.1 | **227.5** | 194.0 |
| 20 | **199.8** | 184.8 | **194.4** | 155.9 |
| 24 | 160.0 | 167.8 | **180.1** | 139.3 |

QB beats WR rank-for-rank through ~rank 20, only falling below around rank 24 — exactly the depth range where real FLEX/SUPER_FLEX slot competition happens in a 10-team league. Confirms Chunk 35's finding: this gap is completely independent of any `portfolio.py` discount constant, since `_allocate_starters` never looks at those constants.

**Step 2 — seed 3's 5 QB picks, instrumented individually:** picks 27/47 (QB1/QB2) are **legitimate** — `would_start=True` each time, and WR wasn't even in the top-8 candidate list at those points, consistent with step 1's structural gap. Picks 54/67/87 (QB3/4/5) were correctly flagged `would_start=False` (bench) by `vbd.py` itself — so `_allocate_starters` was **not** the mechanism responsible for those three specific extra picks. Digging into why they got drafted anyway surfaced something the brief didn't anticipate.

**Major secondary finding — a real, separate harness bug:** `mock_draft.py`'s `_pick_draft_score` hardcodes `mcts.recommend(..., top_n=1)`, while production (`draft_score_engine.py`, the actual live-draft path) uses `top_n=candidate_breadth` (8). Since the Chunk 24 ADP-margin tie-break and Chunk 26 adaptive-resolution logic both only operate on the truncated `top_results` list, **`top_n=1` has silently disabled both refinements for every synthetic mock-draft sweep in this project's history since Chunk 14** — every 5-seed sweep used to calibrate Chunks 20/31/33/34/35, plus `test_positional_balance.py`'s own xfail tests. The real live-Sleeper draft path (Chunk 31 task 3) was unaffected — it goes through the correct code path.

**Verified impact, then reassuringly bounded:** replaying seed 3 with `top_n=8` corrected (scratch-only) improved QB 5→4 and WR 2→3 — real, measurable. But re-running the full 5-seed aggregate sweep with the same correction left the **median-based deviations statistically unchanged** (WR still exactly -2.0, QB still exactly +1.0; TE crept 0.0→+1.0, still unflagged) — individual seeds moved in both directions but washed out at the median. **This means Chunk 33's TE fix and Chunk 35's WR-hypothesis refutation both remain valid** despite the harness bug; it adds real per-seed noise but didn't distort those two conclusions.

**Open thread not fully closed by this chunk, worth flagging:** picks 54/67/87 were correctly flagged bench by `_allocate_starters`, and the harness fix only partially resolved the anomaly (5→4, not 5→2/3 which would match the rest of the league) — meaning something is still making MCTS take bench-flagged QBs over better-flagged alternatives even after both known issues are accounted for. This has the same *shape* as Track B's wait-value bug (bench pick beating a flagged-better alternative) — not confirmed as the same mechanism, just worth keeping in mind; not investigated further this chunk.

**What a real `_allocate_starters` fix would need to do (described, not built):** replace the raw-`projected_points` sort with a positional-scarcity-aware comparison (e.g., within-position percentile, reusing the idea behind the existing `adp_percentile` field) — explicitly **not** a blanket QB penalty, since SUPERFLEX's legitimate QB premium (preserved deliberately through Chunks 9/10/13) is real and must survive this fix; picks 27/47 above are exactly the case it must not break.

**Two concrete items now on the table:**
1. `_allocate_starters` scarcity-aware fix — the real WR-shortage/QB-elevation root cause, well-scoped.
2. `mock_draft.py`'s `top_n=1` harness bug — genuine, low-priority (doesn't retroactively invalidate anything), but worth closing so future sweeps match production exactly — especially before using the sweep harness again to calibrate item 1.

Housekeeping: zero code changes, scratch cleaned, real league draft confirmed untouched throughout.

---

## Chunk 37 — CLOSED, 2026-08-16 (harness fix, committed)

**Fix:** `mock_draft.py`'s `_pick_draft_score` changed from hardcoded `top_n=1` to `top_n=mcts_service.CANDIDATE_BREADTH` (confirmed to resolve to the same `8` as `draft_score_engine.py`'s production path — both now provably use the identical constant, not just similar-looking values).

**Chunk 33/35 conclusions formally reconfirmed (not just assumed from Chunk 36's scratch check):** full regression suite post-fix (50 passed, 1 skipped, 2 xfailed, 0 unexplained — took ~20 min, up from ~3-5 min, confirming the tie-break/adaptive-resolution logic now genuinely runs on every synthetic pick) produced the slot-sensitivity xfail's exact deviation numbers — QB +1.0, RB +1.0, WR -2.0, TE +0.0 — identical to Chunk 33's post-fix state. The 5-seed slot-7 sweep run through the real committed code (not a scratch monkeypatch) produced QB=[4,3,4,3,4], RB=[3,4,5,6,5], WR=[5,6,3,4,3], TE=[3,2,3,2,3] — an exact match to Chunk 36's scratch numbers. Nothing about either prior chunk's conclusion moves.

**Negative control:** reverted to `top_n=1`, confirmed at the mechanism level using the real-draft-replay fixture (pick 82, Chunk 33's own known decision point) that `adaptive_resolution_applied` is structurally `False` at `top_n=1` vs `True` at `top_n=8`, and the pick itself differs (Kelce vs. Pollard) — directly reproducing Chunk 33's known result. Restored the fix; `git diff` confirmed clean.

**Housekeeping:** 1 file changed (`app/services/mock_draft.py`), scratch cleaned, real league draft confirmed untouched. **Committed as `e7c919a`.**

The sweep harness is now a correct measuring stick — Chunk 38 can calibrate against it directly.

---

## Chunk 38 — the real `_allocate_starters` fix (scoped, not yet sent to Claude Code)

**Goal:** replace `_allocate_starters`'s raw-`projected_points`-only sort with a positional-scarcity-aware comparison, so WR isn't structurally squeezed out of FLEX/SUPER_FLEX slots purely because QB's league-wide raw ceiling is higher (Chunk 36's confirmed mechanism) — without breaking SUPERFLEX's legitimate QB premium (picks 27/47's pattern, Chunk 36, must still hold: a QB genuinely filling its 1st/2nd real home should still win cleanly).

**This is the biggest, most invasive fix in this whole Chunk 31+ arc** — every prior fix was a bounded constant recalibration; this touches the core function that decides starter/bench status for every downstream consumer (MCTS reward, `portfolio.py`, `shapley.py`, the live app's own displayed roster). Scope accordingly: more validation surface than any prior chunk, not less.

**Proposed direction (Chunk 36's own suggestion, to be tested not assumed correct):** compare candidates by within-position percentile rank of `projected_points` rather than absolute value — reusing the idea behind the existing `adp_percentile` field. Before committing to full implementation, validate this doesn't break the two known-good cases (picks 27/47's legitimate QB starts) while fixing the known-bad structural gap (Chunk 36's rank-for-rank table).

Full scope to be sent to Claude Code:
1. Implement the percentile-based comparison as an isolated, testable change in `_allocate_starters`.
2. Before the full sweep: directly re-check picks 27/47 (seed 3, Chunk 36) — confirm the legitimate QB starts still win. If they don't, the approach needs revision before proceeding, not after.
3. Full 5-seed sweep (now via the corrected Chunk 37 harness) across ALL positions, not just WR/QB — this change has a wider blast radius than a discount constant, so RB and TE need the same overcorrection scrutiny Chunk 20/33 gave WR/TE.
4. Full regression suite — expect a wider ripple than prior chunks given how central this function is; root-cause and explain every failure individually, same standard as always, budget for more of them than usual.
5. Fresh real mock draft as ground truth.
6. Negative control.
7. Explicitly re-check whether this resolves the residual picks-54/67/87-shaped anomaly Chunk 36 flagged (bench-tier QB still beating a better-flagged alternative) — if it doesn't, that's evidence the residual really does need Track B's wait-value fix separately, not this one.

**Sent to Claude Code, closed 2026-08-16/22 — committed as `93119e1`.** Real, substantial progress with two important honest caveats — not a clean full resolution.

**Step 2 (preserve known-good QB cases) — methodology correction, not a clean pass/fail:** a direct pick-27/47 replay wasn't possible, because the fix reshapes the whole draft trajectory from pick 1 onward (same divergence issue that hit step 7 later) — flagged honestly as a step-2 methodology limitation rather than silently worked around. Verified instead via direct `would_start`/`flex_rank` checks plus three synthetic controlled unit tests. Reasonable substitute, but worth remembering this wasn't the exact validation originally specified.

**Step 3 — 5-seed sweep, all 4 positions:**

| Pos | Deviation now | Deviation pre-fix |
|---|---|---|
| QB | **+0.0** | +1.0 |
| RB | +1.0 (unchanged) | +1.0 |
| WR | **-1.0 (unflagged)** | -2.0 (flagged) |
| TE | **+0.0** | +1.0 |

Real improvement across the board, no overcorrection (RB untouched, as expected since the fix doesn't touch RB's competitive position). **WR improved but did not reach full parity** — moved from flagged (-2.0) to unflagged (-1.0), not to 0.0.

**Step 4 — regression suite: 7 failures, all individually root-caused (none blind-repinned):**
- `test_positional_balance_slot7_multiseed` genuinely resolved (XPASS at 15 seeds) — xfail marker removed with a documented explanation.
- 3 of 6 adaptive-resolution replay failures (picks 79/102/122) were benign: same winning player, only the internal tie-resolution mechanism changed because the fix genuinely cleaned up the VBD landscape (e.g. pick 102's old top-8 held four tight ends). Re-pinned.
- **2 of 6 (picks 59, 39) plus the early-stop test are a real new open finding, marked `xfail`, not silently repinned as correct:** a 3rd elite QB (Jared Goff) now wins MCTS search despite only marginal starting value, even though his league-wide VBD rank is unchanged old vs. new. Root-caused to the percentile fix's *roster-level rollout reward*, where a degenerate case — "only 1 QB candidate in a given rollout branch → percentile 100" — isn't as justified there as it is at the full league-wide level. **This is a new side effect introduced by this chunk's own fix, not a pre-existing issue.**

Final: 5 passed, 3 xfailed, 0 unexplained.

**Step 5 — fresh production mock draft (slot 3, 150 iterations): a real, honestly-reported discrepancy.** QB/TE clean (+0.0 each) — but this single production-settings run showed **WR -2.0 / RB +2.0**, worse than the lighter test-settings sweep (which used 30 iterations, not 150). Reported as an open data point, not smoothed over or explained away. Could be single-run (n=1) noise, or could mean the fix's benefit doesn't fully hold at real production iteration depth — **not yet distinguished, needs more samples before concluding either way.**

**Step 6 — negative control:** confirmed. Reverting the fix reproduces both flagged symptoms (WR back to -2.0, QB back to +1.0) — the fix, not something else, is driving the improvement that does exist.

**Step 7 — residual anomaly (picks 54/67/87) recheck:** not pick-for-pick reproducible (same trajectory-divergence issue as step 2), but a related symptom persists at pick 87: a bench-destined RB beats a similarly bench-destined QB with higher VBD. This is a **bench-vs-bench value comparison**, outside `_allocate_starters`'s scope entirely (that function only decides starter/bench status, not value comparisons among already-bench players) — real, direct evidence that **Track B (the wait-value bug) is still open, still needed, and this chunk correctly left it untouched** as instructed.

**Two new open items from this chunk, both real:**
1. **The Jared Goff degenerate-percentile edge case** — a fresh bug introduced by this fix itself (not pre-existing), marked `xfail`, not yet fixed. Worth its own follow-up given it's self-inflicted and the mechanism (rollout-branch-local percentile with too few same-position candidates) is now understood.
2. **WR shortage: real improvement, unresolved discrepancy between test-sweep (-1.0, unflagged) and single production draft (-2.0, still flagged)** — needs more production-settings samples before concluding whether Chunk 38 alone is sufficient or whether more work remains.

**Housekeeping:** `vbd.py`, `tests/test_adaptive_resolution_regression.py`, `tests/test_positional_balance.py` changed and committed as `93119e1`. Scratch cleaned. `CHUNK38_REPORT.md` was written as a repo-local convenience file but left **untracked** (no prior chunk has committed a report file to the repo — reports have always lived in chat/this doc) — fine as-is unless tracking it is wanted going forward. Real league draft confirmed untouched throughout. One session hiccup: a scheduled wakeup fired after the chunk was already fully done and committed — confirmed nothing was outstanding, no action needed.

---

## Chunk 39 — CLOSED, 2026-08-24 (Goff fix committed; WR/QB balance still unresolved, worse in fresh data)

**Goal recap:** (1) root-cause and fix the Chunk 38 self-inflicted Jared Goff degenerate-percentile edge case, (2) widen production-settings sampling on WR/QB balance beyond Chunk 38's single draft.

**Part 1 — Goff edge case: root-caused and fixed.** Mechanism confirmed exactly as hypothesized in Chunk 38: MCTS's rollout-branch-local percentile calculation degenerates to 100 whenever only one same-position candidate exists in a given branch's local candidate pool, regardless of that candidate's true league-wide quality — this let a 3rd elite QB win search on an artifact of small local sample size, not real value. **Fix:** new `compute_league_wide_percentiles()` in `vbd.py`, building a stable `{player_id: percentile}` table once per `recommend()` call against the full player universe (deliberately different filtering from `compute_replacement_levels`, which is untouched and never receives this table). Threaded as an optional `percentile_lookup` parameter through `_allocate_starters` (vbd.py) and `recommend()` / `_run_iteration` / `_roster_aware_pick` / `_roster_aware_marginal_value` / `_adaptively_resolve_tie` (mcts.py) — `recommend()` builds the table once and passes it to both the main iteration loop and adaptive-resolution call sites, replacing the old branch-local calculation.

**Verification produced two honest self-corrections, both caught within the same report, not hidden:**
1. An in-process check first read pick 59 as resolved (Flowers's raw `mcts_score` now exceeds Goff's under the new table). Closer look showed Goff still wins the *final* recommendation — through a completely separate, untouched mechanism, Chunk 24's ADP-margin tiebreak (near-tie z≈0.5). So the Goff fix is real and correct at the mechanism level (confirmed via controlled unit tests: single-candidate branches no longer default to percentile 100) but has **zero effect on either of the two real-draft-replay picks it was originally motivated by (39, 59)** — both are actually driven by other, already-understood mechanisms (39 turned out to be data drift, below; 59 by the ADP-margin tiebreak).
2. Pick 39's apparent resolution was initially attributed to this chunk's fix. `git stash`-ing back to the exact Chunk 38 commit and re-running against **today's live data** reproduced the same resolved behavior on unmodified Chunk 38 code — meaning pick 39 resolved on its own between chunks because the underlying FFC ADP cache / nflverse projections had moved, not because of anything built this chunk.

**New standing methodological finding, now load-bearing for all future comparison work:** the ADP/projection data sources are not static between chunks — they drift on their own schedule independent of code changes. This is a real, material confound for any before/after regression or calibration comparison that spans more than a few hours. **New standing practice going forward:** whenever attributing a behavioral change to a code change, `git stash` back to the previous chunk's exact committed code and re-run against *today's* live data as the negative control — this cleanly separates "my code change caused this" from "the data moved underneath both versions." This is now the standard technique for isolating a code effect from a data effect in this project, alongside the existing negative-control discipline (revert-and-confirm-failure-reappears).

**Part 2 — widened production-settings sampling: WR/QB imbalance confirmed real and worse, not resolved.** Ran 3 fresh full production-settings mock drafts (150 iterations, matching Chunk 38's single check). All 3 seeds landed **QB +2.0 / WR between -2.0 and -4.0** — every seed worse than or equal to Chunk 38's single -2.0 data point, none better. This directly contradicts any read of Chunk 38 as "WR shortage mostly resolved, just needs more samples to confirm" — the wider sample points the other way.

**Attribution is genuinely confounded, not yet resolved:** a `git stash`-based sanity check on one of the 3 seeds (comparing pure Chunk 38 code vs. Chunk 38+39 code, same seed, same live data) did show a real, code-driven difference (QB=3 under old code vs. QB=4 under new code on that seed) — so the Goff/percentile-table fix is not inert on full-draft outcomes. But a full mock draft is one continuous, cascading trajectory: every opponent pick and every subsequent "my" pick depends on everything drafted before it, so any single early difference between two code versions propagates and compounds through the rest of the draft. This makes it impossible to cleanly attribute the aggregate WR/QB numbers to a specific mechanism from fresh full-draft comparisons alone — you can't tell how much of the divergence is "the fix changed this decision" vs. "the fix changed an earlier decision, which cascaded into a completely different draft from pick 20 onward." Claude Code's own explicit recommendation: **a future dedicated chunk should build a fixed-trajectory replay methodology** — freeze the opponent picks / draft state up to a given point and replay only the code-under-test's decision at that point, rather than comparing two independently-simulated full drafts — to cleanly separate genuine code effects from data drift and trajectory-cascade noise. This is the natural next investigation.

**Regression suite re-pins, all individually justified:**
- `test_adaptive_resolution_regression.py` — picks 39/59/79/82/102/122 all re-verified pick-by-pick against the new code; results as described above (39 = data drift, not this chunk's fix; 59 = still the pre-existing ADP-margin tiebreak, not the percentile fix).
- `test_adp_margin_tiebreak_regression.py` — pick 79 removed from the parametrize list entirely; it no longer exercises the ADP-margin tiebreak mechanism at all under current data/code, resolving via adaptive resolution alone instead (same precedent as an earlier pick-39 removal from this same file in a prior chunk).
- `test_positional_balance_slot7_multiseed` — reverted back to `xfail` (had briefly XPASSed at Chunk 38's close) after the git-stash check confirmed identical behavior under pure, unmodified Chunk 38 code — the earlier pass was itself a data-drift artifact, not a genuine effect of Chunk 38's fix holding up. xfail reason updated to explicitly note the data-drift explanation, not a code regression.

**Housekeeping:** `app/services/vbd.py`, `app/services/mcts.py`, `tests/test_adaptive_resolution_regression.py`, `tests/test_adp_margin_tiebreak_regression.py`, `tests/test_positional_balance.py` changed. Real league draft (`1389755334746202113`) confirmed untouched throughout.

**Bottom line carried into Chunk 40:** the Goff fix is real, correct, and committed, but was never the thing actually driving the tracked regression picks. The WR/QB balance question that Chunk 38 partially addressed is now confirmed **not closed** and trending worse in fresh production data — but full-draft comparisons can no longer cleanly attribute *why*, because of trajectory divergence. The next chunk needs a different kind of tool (fixed-trajectory replay), not another round of fresh full-draft sampling or another constant tweak.

---

## Chunk 40 (fixed-trajectory replay harness) — scoped, sent to Claude Code 2026-08-26

**Why this, now:** Chunk 39 left the WR/QB balance question confirmed-worse-but-unattributable — every fresh full-draft comparison since Chunk 38 has been confounded by two independent sources of noise stacked on top of each other: live data drift (ADP/projections moving between runs) and trajectory divergence (one early decision cascading into a completely different rest-of-draft). Both Claude Code and this planning chat independently converged on the same conclusion: no further constant tweak or fresh-sample sweep can resolve this cleanly. The tool itself needs to change before the next diagnostic step is worth running.

**Goal:** build a reusable **fixed-trajectory replay harness** — freeze a real draft's pick sequence up to a chosen point (all opponent picks, and "my" own prior picks) as fixed input, then re-run only the *next* decision under two different code versions (e.g. pre-Chunk-38 vs. post-Chunk-39) against the *same* frozen state and the *same* data snapshot. This isolates "did this code change alter this one decision" from both confounds at once, without needing a full fresh mock draft per comparison.

**Not a fix chunk — purely infrastructure + first use.** No production code (`vbd.py`, `mcts.py`, `portfolio.py`) should change this chunk except what's strictly needed to support replay (e.g. exposing a way to inject a frozen board/roster state, if one doesn't already cleanly exist).

**Sent to Claude Code — see message below.**

---

## Update log

*(append one dated entry per run/report from here down — most recent at the bottom, chronological)*

- **2026-08-15 (morning):** Project onboarding + deep nuance audit done in a fresh planning-chat session (see `claude/nuances-audit-2026-08-15.md`). Confirmed with user: a practice draft was underway; user stepped into a new Claude Code instance mid-Chunk-31 to continue — handoff briefing written and sent.
- **2026-08-15 (midday):** Chunk 31 tasks 1, 2, 4 report received. Task 3 initially misread as deferred to 2026-09-07 (conflated the mock draft with the real league draft) — flagged for correction. Draft date question resolved: real draft is 2026-09-07.
- **2026-08-15 (afternoon):** Task 3 mock draft completed and reported. TE-glut empirically confirmed live (5 TE/2 WR final roster). Kamara/Conner over-reach confirmed resolved. New Finding C surfaced by direct user review: broad early-reach-vs-ADP pattern from round 6 on, not previously diagnosed. Chunk 31 closed in full; Chunk 32 scoped as a diagnostic-first step to root-cause Finding C before any fix.
- **2026-08-15 (evening):** Chunk 32 report received. Confirmed a real split: 5 of 6 reaches are the already-understood TE-glut, but the 6th (Tyrone Tracy over Jakobi Meyers, pick 103) is a genuinely separate, newly-confirmed wait-value/backfill bug — instrumented in full with empirical survival rates, not yet root-caused to a specific code location, not yet known to be systemic. Chunk 33 scoped into two tracks (TE-glut fix, ready; wait-value widening, needs 2-3 more instrumented data points before a fix is designed) — sequencing pending user input.
- **2026-08-15/16 (overnight):** Chunk 33 Track A closed. Mid-chunk, the originally-scoped constant (`FLEX_CONCENTRATION_DISCOUNT`) proved to have zero effect; root-caused live to a different, long-dormant constant (`BENCH_DISCOUNT_DECAY["TE"]`, flat since Chunk 10) — scope expanded with sign-off, fix built, swept, and verified. TE glut confirmed fixed (0.0 deviation, real mock draft shows league-normal TE count). One real regression test failure found and correctly root-caused (not blind-repinned). Negative control confirmed, including a note about a mid-chunk data-cache refresh that didn't change the conclusion. New open item surfaced: pre-existing WR shortage (since Chunk 30) needs its own future diagnostic. Committed as `c9e452f`.
- **2026-08-16:** Chunk 34 report received. Tested whether the Chunk 32 wait-value bug systemically explains the WR shortage — it doesn't (only 2/65 flagged points, 2/7 drafts match the pattern, though the bug itself is now confirmed 3 times total and worth fixing eventually). Found a concrete, evidenced-but-unverified lead for the real WR-shortage cause: `BENCH_DISCOUNT_BASE`/`DECAY["WR"]` looks like the same kind of stale, never-recalibrated constant TE had before Chunk 33. Chunk 35 scoped as a same-shape recalibration chunk, not yet sent.
- **2026-08-16 (later):** Chunk 35 report received. Hypothesis refuted cleanly (swept to 3x the constant, zero movement on WR deviation) — but the dead-end revealed the real root cause: `vbd.py`'s starter allocation sorts by raw `projected_points` only, with no bench-discount logic in scope at all at that decision point. A separate anomaly (seed 3 drafting 5 QBs) surfaced along the way. Chunk 36 scoped around a combined hypothesis: the same raw-points-only starter allocation, in this SUPERFLEX league, could be driving both the WR shortage and the QB anomaly simultaneously — not yet sent.
- **2026-08-16 (later still):** Chunk 36 report received. Confirmed the structural raw-points gap (QB beats WR rank-for-rank through ~rank 20) as the real WR-shortage mechanism. Seed 3's QB anomaly only partially explained by that same mechanism — most of it traced instead to a major, previously-unknown harness bug (`mock_draft.py` hardcoding `top_n=1`, silently disabling tie-break/adaptive-resolution logic in every synthetic sweep since Chunk 14). Reassuringly, re-verified that this harness bug does not invalidate Chunk 33's or Chunk 35's closed conclusions. A residual, not-fully-explained anomaly remains (picks 54/67/87), possibly connected to Track B's wait-value bug — flagged, not chased further. Chunk 37 (harness fix, sequenced first) and Chunk 38 (the real `_allocate_starters` fix) queued.
- **2026-08-16 (evening):** Chunk 37 report received. Harness fix applied and committed (`e7c919a`); formally reconfirmed (not just assumed) that Chunk 33's and Chunk 35's conclusions are unchanged, via a full fresh regression suite run and a real (non-scratch) 5-seed sweep that matched Chunk 36's numbers exactly. Negative control confirmed the mechanism directly. Chunk 38 (the real `_allocate_starters` positional-scarcity fix) scoped in detail and sent — this is the largest-blast-radius change in the whole arc, since it touches core starter/bench logic used by MCTS, portfolio, Shapley, and the live app directly.
- **2026-08-22:** Chunk 38 report received (this was a long-running chunk, ~2 hours of compute given the fix's central position in the codebase). Committed as `93119e1`. Real, substantial improvement across QB/TE/WR deviations and no overcorrection on RB, but two honest open threads remain: (1) WR improved in the test sweep (-1.0, unflagged) but a single production-settings mock draft still showed -2.0 — not yet enough samples to know if that's noise or a real residual; (2) the fix introduced its own new, understood-but-unfixed edge case (a degenerate roster-level percentile calculation letting a 3rd elite QB, Jared Goff, win search unjustifiably). Step 7 also produced real, direct evidence that Track B (wait-value bug) is still needed independently — a bench-vs-bench value comparison persisted that `_allocate_starters` structurally cannot address. Chunk 39 proposed (widen production-settings sampling, root-cause the Goff edge case) — sequencing pending user input at this natural checkpoint.
- **2026-08-24:** Chunk 39 report received. Goff degenerate-percentile edge case root-caused and fixed (`compute_league_wide_percentiles()`, threaded through vbd.py/mcts.py) — real and correct in isolation, but two honest self-corrections during verification showed it has zero effect on the two tracked picks (39, 59) that originally motivated it; both are driven by other, already-understood mechanisms (data drift and the pre-existing ADP-margin tiebreak, respectively). Widened production sampling (3 fresh drafts) showed WR/QB imbalance is real, confirmed *not* resolved by Chunk 38, and trending worse (QB+2.0/WR -2.0 to -4.0 across all 3 seeds) — but attribution is confounded by both live data drift and full-draft trajectory divergence stacked together, so no further fresh-sample sweep can resolve it cleanly. New standing practice adopted: git-stash-to-prior-commit as the negative control for separating code effects from data drift. Chunk 40 scoped and sent: build a fixed-trajectory replay harness (freeze draft state, vary only code-under-test) as the necessary next tool before any further fix to the WR/QB balance question.
