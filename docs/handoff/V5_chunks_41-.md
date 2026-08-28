# V5 - Draft Builder, Chunks 41-

*Living document — continues directly from V4 (Chunks 31-40). Add to project
knowledge alongside the overview doc, Brainstorm Session, and V1-V4 chunk
summaries. Same format as V4: appended to continuously, one section per
chunk plus a dated Update Log entry at the bottom — not rewritten from
scratch each time. Working model unchanged: Claude Code executes and
reports on the user's machine; the planning chat (this project)
scrutinizes each report critically, updates this doc, and writes the next
scoped prompt. Full incident-level history and the "why" behind every
standing discipline below lives in `claude_nuances-audit-2026-08-15.md`
and V1-V4 — this doc assumes that context exists, it doesn't re-derive it.

**Note on this file itself:** it will be kept updated turn-by-turn in this
chat. Because chat-generated files don't auto-attach to Project knowledge,
re-add the latest version yourself when it's grown enough to be worth
syncing — same caveat the Brainstorm Session doc already flagged for V1-V4.

---

## Standing constraint — non-negotiable, in every single Claude Code prompt

Never touch the real league draft: Sleeper `draft_id 1389755334746202113`,
**CONFIRMED by Vincent directly via the Sleeper app: 2026-09-06 (Sunday),
9:00 PM.** (Prior estimates — 2026-09-07 from Chunk 31, then 7pm Pacific
from Chunk 51 — were both off; this confirmed value supersedes both.)
All draft/testing activity is mock, synthetic, or frozen-replay only.
Every prompt confirms this at close via grep + `git status`/`git diff`.

## Standing disciplines (established the hard way, V1-V4)

- Root-cause before fixing, every time — several chunks are diagnostic-only
  specifically to avoid patching a symptom.
- Never fix off a single data point (n=1) — the tie-break saga (Ch. 23-26)
  and the WR-shortage chase are the canonical examples of why.
- Negative-control every claimed fix.
- Never blind-repin a failing test — root-cause it first, document the
  justification when repinning.
- No silent scope creep — only widen a chunk's scope with explicit sign-off
  once evidence shows the originally-named cause isn't the real one
  (e.g. Chunk 33's mid-chunk pivot from `FLEX_CONCENTRATION_DISCOUNT` to
  `BENCH_DISCOUNT_DECAY["TE"]`).
- Self-correct openly in this doc when later evidence contradicts an
  earlier chunk's conclusion — never quietly smooth it over (e.g. Chunk 39
  discovering pick 39's "resolution" was data drift, not its own fix).
- **New as of Chunk 40:** separate code effects from data drift by
  `git stash`-ing (or worktree-comparing) back to the prior commit and
  re-running against *today's* live data — data sources drift on their own
  schedule independent of code changes, confirmed material more than once.
- **New as of Chunk 40:** the moment a decision point of interest is
  frozen for replay, snapshot-and-name its data immediately — a "known
  decision point" is not a stable reference once only current data can be
  pinned (lost the ability to cleanly re-examine Chunk 33's pick 82 for
  exactly this reason).
- **New as of Chunk 44:** `recommend()`'s internal Welford-based stderr
  only captures within-run sampling noise, not between-seed variance —
  confirmed to underestimate true run-to-run spread by up to 3.4× for at
  least one candidate. Not yet remediated or even scoped as a fix — flagged
  as a real, standalone concern: other places that trust this stderr to
  call something a "confident gap" (tie-break logic, adaptive resolution)
  may be more overconfident than believed. Carried forward, not yet acted
  on.

## Quick reference — league & stack (full detail in overview.md / nuances audit)

- League "Kiddos": `league_id 1389755334746202112`. 10-team SUPERFLEX, full
  PPR, TE premium +0.5/rec, snake draft, no keepers. Draft date/time:
  **CONFIRMED 2026-09-06 (Sunday), 9:00 PM** (Vincent confirmed directly
  via the Sleeper app — supersedes both the original 2026-09-07 finding
  and Chunk 51's 7pm estimate).
- League "Former Bradley Bums" (added Ch. 51): `league_id 1389749759891214336`,
  `draft_id 1389749759891214337`. Same format as Kiddos field-for-field
  (full PPR, TE +0.5, SUPERFLEX, 10-team, snake) — confirmed via API, not
  assumed. Draft: 2026-09-08, 6pm Pacific, 90s pick timer (vs. Kiddos'
  60s). Keeper status flagged for Vincent's confirmation (evidence points
  to none, matching Kiddos' pattern, not yet asserted as settled).
- Roster is a **manual override**, not what Sleeper's API reports: QB,
  2×RB, 2×WR, 3×FLEX, SUPER_FLEX, 6×BN (15 rounds). Re-apply this whenever
  pulling fresh Sleeper settings — the endpoint is stale for this league.
  Same roster shape confirmed for League 2 too.
- Stack: FastAPI + WebSockets backend, plain HTML/CSS/JS frontend
  (Streamlit explicitly rejected early, don't resuggest). Python 3.10 venv
  (machine default is 3.14, lacks numpy/pandas/scipy wheels).
- **Load-bearing design principle:** MCTS's value estimate *is* the single
  Draft Score. Shapley is a subordinate "why" explanation only, never
  blended into the score — violating this would break the project's
  founding "no weighted averages" principle (Chunk 8).
- Data sources: nflverse parquet direct fetch (migrated off dead/frozen
  `nfl_data_py` in Chunk 30) as primary, + FantasyFootballCalculator ADP
  (`2qb` format as a documented SUPERFLEX approximation, ~78% pool
  coverage) for rookies/team-changers and opponent modeling. 100% free
  only — any paid service must be named and flagged before use, never
  added silently.

---

## State carried into V5 (as of Chunk 40 close, 2026-08-26)

**Closed and considered solid:** full analytical pipeline (projections →
VBD → correlated Monte Carlo → MCTS/opponent modeling → Markowitz →
lineup-awareness → Shapley → single Draft Score), live UI (Chunks 1-12),
sequencing/decision-logic correctness (Chunks 13-27, includes the full
tie-break saga), the nflverse data migration off frozen 2024 data
(Chunk 30), the LA/LAR team-change false-positive fix (Chunk 31), and the
TE-glut fix (`BENCH_DISCOUNT_DECAY["TE"]` 1.0→0.3, Chunk 33, reconfirmed
clean after the Chunk 37 harness fix).

**Open, in-progress thread:** WR-shortage / QB-over-representation in
FLEX/SUPER_FLEX starter allocation. Chased through: bench-discount
hypothesis (refuted, Ch. 35) → root-caused to `_allocate_starters` sorting
by raw `projected_points` with zero positional-scarcity awareness (Ch. 36)
→ a real harness bug found along the way (`mock_draft.py` hardcoded
`top_n=1`, silently disabling tie-break/adaptive-resolution in every
synthetic sweep since Chunk 14 — fixed Ch. 37, confirmed not to invalidate
prior conclusions) → the actual `_allocate_starters` percentile-based fix
shipped (Ch. 38, `93119e1`) — real improvement, no overcorrection on RB,
but WR only reached -1.0 (unflagged) in test sweeps vs. -2.0 in a single
production draft, and introduced its own new bug (Jared Goff
degenerate-percentile edge case) → Goff fix shipped cleanly (Ch. 39,
`compute_league_wide_percentiles()`) but widened production sampling (3
fresh drafts) showed the WR/QB imbalance **confirmed not resolved and
trending worse** (QB +2.0 / WR -2.0 to -4.0 across all 3 seeds) — with
attribution confounded by data drift and full-draft trajectory divergence
stacked together.

**Chunk 40 — CLOSED, 2026-08-26, committed `96fd420` (infrastructure
only).** Built the fixed-trajectory replay harness specifically to break
that confound: freeze a real draft's state at a chosen pick, replay only
the next decision under a chosen code ref + a pinned data snapshot.
Everything needed already existed cleanly in the codebase — zero
production-file changes required. Key outputs:
- `replay_lib/harness.py`, `scripts/replay_cli.py` (snapshot/freeze/run),
  `scripts/replay_compare.py` (git-worktree-based two-ref diff, always
  cleaned up), `tests/test_replay_harness.py` (7 unit tests).
- Determinism proven twice (same-ref-twice byte-identical; same-ref via
  two independent worktrees deep-equal) — any Task 5/6 difference is
  attributable to real code differences, not harness noise.
- Task 5 (reproduce Chunk 33's pick-82 finding): **did not reproduce
  cleanly** — further data drift since Chunk 39 meant Kelce wasn't even in
  Chunk 40's top-8 pool under current data. Root-caused as data drift, not
  a harness bug, and is the direct origin of the new snapshot-immediately
  discipline above. Candidate-pool-level comparison (Kelce present
  pre-Chunk-38, absent post) still cleanly confirmed the Chunk 38
  mechanism qualitatively.
- Task 6 (fresh WR-passed-over point, pick 87, pre-Chunk-38 vs. HEAD, same
  frozen trajectory/snapshot): pre-Chunk-38 top-8 pool was QB/TE only —
  zero RB/WR present at all. HEAD's pool includes both a bench-tier RB
  (Tony Pollard, wins, 2640.3) and a would-start WR (Jakobi Meyers,
  2633.4) genuinely contending, ~7pt gap. Raw finding only, correctly not
  interpreted — that's V5's Chunk 41.
- Regression suite: 53 passed, 1 failed (pick 82, data-drift-explained,
  matches its own Chunk 39 docstring warning), 2 skipped, 4 xfailed.
  Left un-repinned deliberately — flagged for planning-chat sign-off
  rather than silently fixed, since repinning was outside
  infrastructure-only scope.
- Real draft_id confirmed untouched (grep + `git status`/worktree list).

---

## Chunk 41 — CLOSED, 2026-08-26, committed `0250519` (diagnostic only, one repin)

**Task 0 — pick-82 repin, done right, not blind-flipped.** Re-verified
live before touching anything: found the suite's single failing assert
was hiding a second drifted field (`adp_tie_break_applied` had also
flipped to `True`, not just `adaptive_resolution_applied`). Repinned both
`(82, "Courtland Sutton", True, True)` with a comment attributing it to
Chunk 40's already-root-caused data drift (Kelce absent from the top-8
pool under both pre-Chunk-33 and HEAD code as of today). Full suite: 54
passed, 2 skipped, 4 xfailed, 0 unexplained.

**Method:** reused Chunk 40's exact snapshot (`chunk40_20260826.json`) for
cross-comparability, generated 4 new production-settings mock drafts (slot
7, seeds 1/2/4/5) plus reused Chunk 40's own pick-87 (seed 3) = **6 total
decision points**, each frozen and snapshot-pinned immediately per the new
standing practice. Per the brief's explicit "only Task 0 in the commit"
instruction, all instrumentation was written as uncommitted scratch
reusing Chunk 40's committed `replay_lib`/scripts unchanged — flagged
explicitly rather than silently deviating. Snapshot/trajectory artifacts
are all on disk, gitignored, reloadable (see file list at bottom of this
section).

**The 6 points:**

| Pt | Seed/Pick | Taken (would_start) | WR passed over (would_start, survival%) | Gap | Track B? |
|---|---|---|---|---|---|
| 0 | 3/87 | Pollard RB (False) | Meyers (True, 88.3%) | 6.9, z≈2.1 | No — survival >80% |
| 1 | 1/74 | Henderson RB (True) | Pickens (True, 100%) | 7.6 | No — taken not bench-tier |
| 2 | 2/54 | Maye QB (True) | Adams (True, 51.7%) | −0.5 (WR raw score higher) | No — taken not bench-tier |
| 3 | 4/27 | Allen QB (True) | Nacua (True, 100%) | 11.5 | No |
| 4 | 4/34 | McBride TE (True) | Nacua (True, 100%) | 9.8 | No |
| 5 | 5/87 | Pollard RB (True) | Meyers (True, 91.7%) | 4.5 | No |

**Track B overlap (task 7): 0/6 clean matches.** Point 0 gets closest
(bench-tier winner, confident gap) but fails the ≤80%-survival threshold
at 88.3% — independent reinforcement of Chunk 34's finding that Track B is
real but rare, not the systemic driver here.

**Allocation-level vs. rollout-level (tasks 5–6) — a genuine mix, four
distinct sub-findings:**

Ran all 6 points pre-Chunk-38 (`e7c919a`) vs. HEAD, same frozen
trajectory+snapshot each. In 6/6, the top-8 pool itself shifted in
Chunk 38's intended direction — **allocation is demonstrably working.**
But the outcomes split:

- **Points 0 & 5 — allocation fixed cleanly.** WR went from entirely
  absent from the pool (old code) to present and would-start (new code).
  Point 0's WR still narrowly loses; point 5's doesn't even face a
  WR-specific loss — but WR now at least contends either way.
- **Point 1 — allocation-level, second-order, not a bug.** Chunk 38
  pulled 3 RBs into the pool (displacing 3 TEs); those RBs, not WR, won
  the final comparison. WR's own score improved slightly (2692.6→2697.7)
  — it's facing tougher competition now, not being pushed down. A side
  effect of fixing RB's disadvantage.
- **Points 3 & 4 — rollout-level, NOT allocation. Strongest, most
  repeatable finding of the chunk.** Same two candidates present in the
  pool under both code versions. Root-level VBD moved exactly as the
  Chunk 38 fix intends (TE VBD down, WR VBD up) — but final `mcts_score`
  moved in the **opposite direction** (McBride: VBD 190.0→142.8 down,
  score 1905.7→1924.1 up; point 4 shows the same sign flip). Hard,
  quantitative evidence that something downstream of `_allocate_starters`
  — hypothesized as the roster-level percentile pathway in
  `_roster_aware_marginal_value`/`evaluate_roster`, the same area Chunk 39
  touched for the Goff fix — is partially undoing the root-level
  correction. Not traced to an exact line (same honesty standard as
  Chunk 32's own flag) — **clearest, best-scoped target for Chunk 42.**
- **Point 2 — unrelated to Chunk 38 entirely. A new, previously-undocumented
  bug.** Identical winner (Maye) under both code versions. Traced to
  `_apply_adp_margin_tie_break` (`mcts.py:673-675`): its margin is
  **signed** (`adp − next_turn_pick_no`), not absolute-value, so it favors
  whichever candidate's real ADP is most negative relative to next turn —
  normally correct (favors the nearer-term-at-risk candidate), but here
  Maye's ADP (7.0) is so far below even the *current* pick (54) that he's
  already a 47-pick anomaly, and the signed formula still treats "further
  overdue" as "more urgent" unconditionally. Adams (ADP 51.8, genuinely at
  risk, 51.7% survival, higher raw score) loses to this artifact. Real,
  orthogonal to both allocation and rollout mechanisms above, would apply
  to any extremely-overdue candidate at any position — **flagged for its
  own future chunk, deliberately not chased further here.**

**Task 8 — conclusion:** a mix, not one dominant mechanism — closer to TE
glut's "one real driver plus edge cases" shape, but messier. (1)
Allocation is now working correctly and positively for WR in most fresh
points. (2) A real, quantitatively-clear rollout-level countervailing
effect (points 3/4) is the strongest, most repeatable Chunk 42 target. (3)
A distinct, unrelated ADP-tiebreak signed-margin bug (point 2) is real and
needs its own follow-up but must not be conflated with this thread. (4)
Track B remains real-but-rare, not implicated here.

**Still unknown:** the exact line/mechanism inside the rollout reward
computation causing the VBD-vs-score sign flip — explicitly left for
Chunk 42, not traced further here per scope.

**Artifacts on disk (gitignored, reloadable):**
`data/replay_snapshots/chunk40_20260826.json`; trajectories
`task6_pick87_wr_passed_over`, `chunk41_pt1_seed1_pick74` …
`chunk41_pt5_seed5_pick87`; full pick logs
`chunk41_slot7_seed{1,2,4,5}_full_picklog.json`; per-point
`*_full_instrumentation.json` / `*_prechunk38_vs_head.json`.

**Verification:** `git status`/`git diff` show only the Task 0 test repin;
`git worktree list` clean; grep for the real draft_id/`SLEEPER_DRAFT_ID`
across all touched and scratch files — zero matches.

---

## Chunk 42 — CLOSED, 2026-08-26, diagnostic only, no commit

**Task 1 — widened evidence, zero fresh drafts needed.** Batch-scanned all
60 "my turn" points across Chunk 41's 4 fresh mock drafts (one process per
ref, not one worktree per point — a more efficient reuse of the existing
artifacts). Found 8 candidate sign-flip pairs, selected the 3 clearest new
ones, all immediately snapshot-pinned to `chunk40_20260826.json`.

**Before/after table, 5 points total (2 original + 3 new) — every single
one shows VBD gap and score gap moving in opposite directions:**

| Point | Pair | VBD gap (old→new) | Δ | Score gap (old→new) | Δ |
|---|---|---|---|---|---|
| seed4/27 (orig.) | McBride−Nacua | +15.5→−42.7 | −58.2 | +4.4→+11.5 | +7.1 |
| seed4/34 (orig.) | McBride−Nacua | −13.8→+45.4 | +59.2 | +12.4→−9.8 | −22.2 |
| seed2/34 (new) | Jefferson−McBride | −77.9→−20.9 | +57.0 | +71.3→+16.4 | −54.9 |
| seed2/47 (new) | Jefferson−McBride | −74.8→−9.7 | +65.1 | −28.2→−41.3 | −13.1 |
| seed4/14 (new) | Nacua−Hurts | −14.6→+53.6 | +68.2 | +66.4→+47.0 | −19.4 |

3/5 involve McBride specifically; 1/5 shows the identical pattern for a
QB pair (Nacua−Hurts) — **rules out "TE-only," this is systemic across
position pairs.**

**Task 3 — mechanism traced to a specific function/line, by direct
elimination:**
1. McBride's/Nacua's own discount, checked individually — byte-identical
   both refs. Eliminated.
2. The rollout's deterministic complementary-pick pairing
   (`_roster_aware_pick`) — identical behavior both refs. Eliminated.
3. **The converged 5-player roster's `evaluate_roster` score** — checked
   directly at 2 points, byte-identical both refs (e.g. seed4/pick34:
   1651.2 both). **This rules out the entire discount/starter/percentile
   pathway that was Chunk 41's standing hypothesis** — proven not the
   cause, not just unconfirmed.
4. **The actual cause:** `mcts.py:783,799-800` —
   `vbd_full = calculate_vbd(...)` → `build_adp_proxy_ranks(vbd_full)` →
   `build_market_adp_ranks(...)`, feeding `_advance_opponents`'s stochastic
   opponent-pick sampling on every rollout step. For the 760 players (79%
   of the remaining pool) without real market ADP — who fall back to this
   VBD-proxy rank inside `opponent_model.pick_probabilities`'s
   `ADP_WINDOW=40` filter — the rank shifts median 53, mean 122 between
   refs, and 600/760 (79%) shift by more than the window itself. Which
   players an opponent model even considers at a given simulated pick
   changes substantially between refs, even though nothing in the
   reward/discount math for the endpoint roster does.

**Task 4 — genuine bug, not an emergent tradeoff.** Reasoning: an
intentional scarcity/sequencing effect would have to show up in how the
converged roster or the deterministic pairing gets valued — both proven
byte-identical. The real cause: `opponent_model.build_adp_proxy_ranks` (a
Chunk 1-20 design, kept post-Chunk-21 only as a fallback for ADP-unmatched
players) assumes `calculate_vbd`'s ordering is a reasonable market-order
stand-in. True when VBD was raw-points-based; **false since Chunk 38
deliberately changed VBD's ordering philosophy to a percentile-within-position
ranking that explicitly does not aim to resemble real market order** — and
nobody re-checked whether `opponent_model.py`, an unrelated downstream
consumer of the same shared function, still made sense afterward. Same
bug shape as Chunk 26's set-literal issue and Chunk 39's Goff edge case.

**Honest confidence calibration, stated by Claude Code itself:** steps
1-3 are direct empirical eliminations; step 4 is the strongest remaining
explanation by elimination, not yet confirmed by running enough Monte
Carlo replicates to show the survival-rate difference numerically per
point — explicitly flagged as Chunk 43's necessary first step before any
fix.

**Regression suite:** 54 passed, 2 skipped, 4 xfailed — identical to
Chunk 41's baseline, confirming zero regressions from a diagnostic-only
chunk. No commit (nothing to commit — pure diagnosis).

**Explicitly not touched:** the Chunk 41 ADP-margin signed-tiebreak bug —
kept fully separate as instructed.

**Fix target identified for Chunk 43:** decouple
`opponent_model.build_adp_proxy_ranks` from `calculate_vbd`'s (now
percentile-based) output — give it its own, independent proxy-ranking
basis (e.g. raw projected points, or a dedicated market-likelihood
ranking) so future starter-allocation changes stop silently perturbing
opponent-behavior simulation.

---

## Chunk 43 — CLOSED, 2026-08-26, GATE FAILED at Step 1, no commit

**Step 1 result: the proposed causal link does not hold.** Ran 500-replicate
Monte Carlo survival checks (same methodology as Chunks 32/41) for both
complementary-piece directions at 3 of Chunk 42's 5 sign-flip points, same
frozen trajectory + snapshot, pre-Chunk-38 vs. HEAD:

| Point | Direction | pre-Chunk-38 | HEAD | Δ |
|---|---|---|---|---|
| seed4/pick27 | P(Nacua survives \| took McBride) | 1.000 | 1.000 | 0 |
| | P(McBride survives \| took Nacua) | 1.000 | 1.000 | 0 |
| seed4/pick34 | P(Nacua survives \| took McBride) | 1.000 | 1.000 | 0 |
| | P(McBride survives \| took Nacua) | 0.996 | 0.996 | 0 |
| seed2/pick34 | P(McBride survives \| took Jefferson) | 0.998 | 1.000 | +0.002 (noise) |
| | P(Jefferson survives \| took McBride) | 0.646 | 0.650 | +0.004 (noise, SE≈0.021) |

Every comparison is statistically indistinguishable between refs,
including the one point with genuine survival-risk variance (Jefferson
~65%, not ceiling-saturated) — a 0.4pt difference is trivially inside
Monte Carlo noise at n=500.

**Why the elimination logic was still sound even though the conclusion was
wrong:** the discount/starter/percentile pathway is genuinely ruled out
(byte-identical converged rosters, Chunk 42), and the proxy-rank churn for
ADP-unmatched players is real and large (median 53 ranks) — but McBride,
Nacua, and Jefferson all have **real market ADP**, so their own survival
odds are governed directly by that real ADP, not the proxy-rank fallback.
The massive proxy-rank churn among the ~760 *other* unmatched players
apparently doesn't propagate through team-position-count effects into a
measurable survival difference for these specific pieces. **The mechanism
traced to a precise line in Chunk 42 is real, but it isn't the thing
producing the score-gap reversal.**

**Per the brief's explicit instruction, stopped here rather than
force-fitting Step 2.** Steps 2-4 (fix, hardening, broad validation): not
performed, correctly gated off.

**Two flagged, unexplored candidate directions for whoever scopes next,
explicitly stated as unexplored, not findings:**
1. The tree search's own UCB1 exploration/visit-count allocation
   differentially favoring one candidate's branch over another between
   code versions — a search-allocation-level mechanism, distinct from
   both eliminated value-level mechanisms.
2. Residual Monte Carlo noise in `simulate_players`'s draws not yet
   separated from a real signal — i.e., whether the original "sign flip"
   claim (based on a single `mcts_score` value per point per ref) is even
   statistically distinguishable from run-to-run variance in the first
   place.

**Bottom line, stated directly by Claude Code:** the WR/QB sign-flip
mechanism — the strongest lead since Chunk 36 — is now down to **zero
confirmed candidate mechanisms** after two rounds of direct elimination.
Needs a genuinely fresh diagnostic angle for Chunk 44, not a variant of
either already-eliminated hypothesis.

**Housekeeping:** zero files changed, no commit, `git worktree list`
clean (pre-Chunk-38 worktree created for the gate check, removed
immediately after), grep confirms real draft_id untouched. Survival
results saved to
`data/replay_trajectories/chunk43_step1_survival_{head,prechunk38}.json`.

**Important distinction to hold onto going forward:** this chunk closes
one specific *mechanistic lead* (the sign-flip-at-these-5-points
investigation), not the underlying WR/QB imbalance itself. The aggregate
positional-balance deviation (established via the multi-seed
regression-suite sweep since Chunks 38-39) is a separately-measured fact
and remains real and tracked regardless of what happens to this specific
mechanistic thread.

---

## Chunk 44 — SENT to Claude Code, 2026-08-26, report pending

**Reframing after two eliminated hypotheses:** before chasing a third
specific mechanism (UCB1 visit-count allocation), check the more
fundamental, cheaper-to-test question Claude Code itself flagged as
unexplored: is the original "sign flip" claim even real, or is it
plausibly an artifact of comparing single stochastic runs? Every sign-flip
point so far (Chunks 41-42) used exactly one `mcts_score` per point per
ref — nobody has checked whether that difference survives replication
across independent seeds, or whether it's within ordinary run-to-run
noise. This is cheaper to test than instrumenting UCB1 internals and would
make that instrumentation moot if the answer is "noise."

**Structure: gated again, same discipline as Chunk 43.**

**Scope sent:**
1. **Gate — is the sign flip statistically real?** For all 5 of Chunk 42's
   points, re-run `recommend()` under 10-20 independent seeds for BOTH refs,
   same frozen trajectory + snapshot, holding everything else fixed.
   Determine per point: (a) does the sign-flip pattern hold consistently
   across seeds, or does it wash out/reverse under different draws? (b) is
   the between-ref gap difference larger than the within-ref seed-to-seed
   spread? Reuse `recommend()`'s existing per-candidate standard-error /
   statistical-tie infrastructure (Chunk 4.5) if it's exposed at the needed
   granularity, and reconcile it with the empirical multi-seed spread
   rather than relying on only one.
2. Report a clear real/robust vs. noise/artifact verdict per point. If
   ALL 5 points turn out to be noise, that is a valid, complete, honest
   closure of this thread — not a failure to manufacture a finding.
3. **Only for points confirmed statistically robust:** instrument UCB1's
   visit-count/exploration allocation per candidate branch, both refs — is
   search effort itself (not value) being differentially allocated between
   candidate branches.
4. **Only if 3 still doesn't explain a robust point:** check for
   RNG-consumption-order divergence between refs — do the two code
   versions consume a different number/sequence of random draws before
   reaching the draws that matter for these candidates, such that a
   nominally "same seed" produces a different realized stream at the
   decision point. A genuinely distinct nondeterminism-under-fixed-seed
   class of bug, not yet checked.
5. No fix in this chunk regardless of outcome — still diagnostic, third
   round on this thread.
6. Out of scope, still deferred: the ADP-margin signed-tiebreak bug,
   `opponent_model.py` performance, Track B.
7. Standard closing verification: grep + `git status`/`git diff` confirm
   real draft_id untouched.

## Chunk 44 — CLOSED, 2026-08-26, GATE FAILED at Step 1, no commit

**Step 1 — 15-seed replication, both refs, all 5 points** (VBD confirmed
seed-independent by inspection, so only `mcts_score` needed sweeping):

| Point | Pair | mean gap (old, SD) | mean gap (new, SD) | Δ | Welch t | uncorrected p |
|---|---|---|---|---|---|---|
| seed4/27 | McBride−Nacua | 6.95 (6.10) | 12.58 (5.52) | +5.63 | 2.65 | ≈0.013 |
| seed4/34 | McBride−Nacua | 3.01 (16.08) | 10.53 (18.56) | +7.52 | 1.19 | ≈0.24 |
| seed2/34 | Jefferson−McBride | 21.89 (31.21) | 32.10 (19.80) | +10.21 | 1.07 | ≈0.29 |
| seed2/47 | Jefferson−McBride | −50.85 (34.23) | −74.67 (23.94) | −23.81 | −2.21 | ≈0.036 |
| seed4/14 | Nacua−Hurts | 64.82 (18.47) | 57.98 (11.92) | −6.84 | 1.21 | ≈0.24 |

**3/5 points are unambiguous noise** (within-ref seed-to-seed SD of
12-35 points dwarfs the between-ref delta, |t|<1.25). Notably,
**seed4/pick34 — Chunk 42's own headline illustrative example — is the
clearest noise case of all five.** The other 2/5 (seed4/27, seed2/47) are
nominally significant at uncorrected α=0.05, but this is 5 unplanned
comparisons and **neither survives Bonferroni correction** (critical
|t|≈2.76-2.79 needed; observed 2.65 and 2.21 both fall short). Applying
the same multiple-comparisons discipline this project already paid for
once in the Chunk 24→25→26 tie-break saga: **none of the 5 points is a
defensible, statistically robust finding.**

**Verdict: this specific mechanistic lead does not survive quantitative
replication.** Three consecutive diagnostic chunks (42, 43, 44) have now
each eliminated a specific, reasonably-motivated hypothesis in turn.

**Real side-finding, not chased further but worth carrying forward:**
`recommend()`'s internal Welford-based stderr (within-run sampling noise
only) badly underestimates true run-to-run variance for at least one
candidate — empirical across-seed SD for Nacua at seed4/pick34 (21.80)
was **3.4× the mean reported within-run stderr** (6.35). This is orthogonal
to this chunk's question but a real, standalone concern: **other places in
this system that trust that stderr to call something a "confident gap"
(the tie-break logic, adaptive resolution) may be more overconfident than
believed** — flagged as a new standing open item, not investigated
further here.

**Steps 2-3: correctly not performed** — no point cleared Step 1's bar,
even before the multiple-comparisons correction, so UCB1 visit-allocation
and RNG-consumption-order checks weren't warranted.

**Recommendation, stated directly by Claude Code:** stop single-point
mechanism-hunting on this thread. Three consecutive chunks eliminated
three specific, reasonable hypotheses, and this chunk shows the original
observations don't even reliably replicate — there may be nothing further
at the single-decision-point level, only noise at this iteration budget.
Points toward the one approach in this whole arc that's actually found
something durable: **a population-level structural analysis in the style
of Chunk 36** (the rank-for-rank raw-points distribution table), rather
than a fourth round of single-point forensics. **The aggregate WR/QB
imbalance itself remains real and unresolved** (Chunks 38-39's
regression-suite sweep) — this chunk only closes out the sign-flip lead
as unproductive, it doesn't touch the underlying fact.

**Housekeeping:** zero files changed, no commit, full regression suite
identical to prior baseline (54 passed, 2 skipped, 4 xfailed), `git
worktree list` clean, grep confirms real draft_id untouched. Raw sweep
data saved to
`data/replay_trajectories/chunk44_seed_sweep_{head,prechunk38}.json`.

---

## Chunk 45 — SENT to Claude Code, 2026-08-26, report pending

**Reframing after three eliminated hypotheses:** pivoting from
single-decision-point forensics to population-level structural analysis,
per Claude Code's own recommendation and the one prior success this arc
has actually produced (Chunk 36's rank-for-rank raw-points table, done
*before* Chunk 38's percentile fix). The natural question now: did
Chunk 38's percentile-within-position comparison actually neutralize the
structural scarcity gap Chunk 36 found, or did it just change the axis
the comparison happens on without solving the underlying value mismatch?
A concrete hypothesis worth testing directly: percentile rank alone
doesn't carry information about how much real value a given percentile
represents at a position — if QB's percentile distribution is "steeper"
than WR's under SUPERFLEX (moving from 80th→90th percentile means more
real marginal value for QB than the same percentile move means for WR,
given league-wide 2-QB demand), then comparing raw percentiles cross-position
in `_allocate_starters` could still structurally favor QB even though the
comparison axis changed from raw points to percentile.

**Scope sent (diagnostic only, no fix):**
1. Reconstruct Chunk 36's rank-for-rank raw-points table under current
   data, AND build a parallel percentile-based table under current
   HEAD code — does percentile-within-position actually flatten the
   original QB>WR gap, or does it persist in a different form?
2. Aggregate wait-value/passed-over audit at scale: reuse all existing
   full-draft pick logs from Chunks 41-44 (don't regenerate what already
   exists), apply Chunk 34's exact would-start/survival criterion across
   EVERY "my turn" decision in every available draft (not just 5-6 hand-picked
   points), and report where WR systematically loses, broken down by
   percentile-rank differential, raw-VBD differential, and ADP survival —
   with real statistical power this time (dozens/hundreds of decisions,
   not 5).
3. Specifically test whether `_allocate_starters`'s percentile comparison
   properly reflects real cross-position value differences, or whether
   comparing "80th percentile QB" to "80th percentile WR" as equivalent is
   itself a scale-mismatch — i.e., does the fix's own comparison currency
   have a structural flaw, separate from anything in MCTS/rollout scoring
   (which 3 rounds of elimination have now ruled out as clean).
4. Conclusion: is there a real, population-level structural driver still
   present post-Chunk-38, and if so, precisely what is it — in the same
   spirit as Chunk 36's precise rank-for-rank table, not a vague
   "percentile might not be enough" hand-wave.
5. No fix this chunk. Full regression suite. Standard draft_id
   verification at close.

---

## Chunk 45 — CLOSED, 2026-08-26, precise structural finding, no commit

**The best-quality diagnostic result this entire arc has produced.**
Reused all 5 existing full pick logs (Chunks 41/42), zero new mock drafts
generated, same pinned snapshot throughout.

**Task 1 — dual table, current data. Result is the OPPOSITE of the
brief's working hypothesis:**

Raw projected points (reproduces Chunk 36's shape):

| rank | QB | RB | WR | TE |
|---|---|---|---|---|
| 1 | 372.9 | 349.2 | 328.2 | 329.3 |
| 10 | 284.2 | 247.1 | 227.5 | 194.0 |
| 20 | 199.8 | 184.8 | 194.4 | 155.9 |
| 24 | 160.0 | 167.8 | 180.1 | 131.9 |

Percentile-within-position (pool sizes QB=131/RB=217/WR=414/TE=230):

| rank | QB | RB | WR | TE |
|---|---|---|---|---|
| 1 | 100.0 | 100.0 | 100.0 | 100.0 |
| 10 | 93.1 | 95.8 | 97.8 | 96.1 |
| 20 | 85.4 | 91.2 | 95.4 | 91.7 |
| 24 | 82.3 | 89.4 | 94.4 | 90.0 |

**Percentile does not flatten the QB>WR gap — it overcorrects past it.**
QB's percentile at matched rank is lower than every other position
(82.3 vs. WR's 94.4 at rank 24), purely because QB's total scored pool
(131) is much smaller than WR's (414) — same absolute rank consumes a
bigger fraction of a smaller pool. The raw-points gap Chunk 36 found is
still fully present; percentile, if it were the allocation currency,
would now run the *other* way.

**Task 2 — large-N audit (75 decisions, not 5-6):**
- 56% of all 75 decisions (42/75) had ≥1 would-start WR passed over.
- Excluding WR-over-WR (13, irrelevant): 52 non-WR-taken instances.
  Winner breakdown: **RB 29 (56%)** — not QB — **QB 15 (29%), TE 8 (15%)**.
- Percentile differential (taken−WR): mean **−2.5**, taken player's own
  percentile is *lower* than the passed-over WR's in 65% of instances —
  confirms Task 1 directly, percentile does NOT favor the winner.
- Raw-VBD differential (taken−WR): mean **+20.2**, taken player has higher
  raw VBD in 79% of instances — the inverse pattern.
- `corr(percentile_diff, score_gap) = 0.039` (no relationship) vs.
  `corr(vbd_diff, score_gap) = −0.366` (real, t≈−2.78, but noisy per-point
  since each is a single-seed `mcts_score` — Chunk 44 already proved those
  carry large run-to-run SD, so sign/significance reported honestly,
  magnitude not leaned on).
- Survival: median 99.4%, only 19% at real risk. **Track B, full
  criterion, at this much larger sample: 0/8 bench-tier instances
  qualify** — same conclusion as Chunk 34, now on a far bigger sample:
  essentially never occurs.

**Task 3 — yes, percentile IS a scale-mismatch, but not the one hypothesized,
and not where the decision lives.** Percentile is genuinely miscalibrated
across positions (a real normalization artifact of comparing against each
position's full scored-player pool rather than its draft-relevant pool)
— but it runs in WR's favor, not against it. It doesn't matter empirically
because **percentile is a one-time, discarded classification signal.** It
decides starter/bench/flex-rank (Chunk 38's fix — working correctly, per
Tasks 1-2) and then is never used again. `calculate_vbd`'s output,
`portfolio.py`'s bench/flex discounts, and `evaluate_roster`'s simulated
mean/variance all multiply against **raw `projected_points`**, not
percentile. A WR can legitimately win "should this player start" and
still lose "which player should I draft," because those two questions run
on entirely different, disconnected currencies.

**Task 4 — precise structural conclusion: a two-layer architecture
mismatch, not a single bug.**
1. **Starter-allocation fairness** (percentile, Chunk 38) — fixed, and
   empirically favors WR now (65% of instances).
2. **Value-maximization** (raw points → VBD → bench/flex discounts →
   simulated roster reward, unchanged since Chunk 1) — still structurally
   favors non-WR positions (79% of instances), reflecting **this
   SUPERFLEX league's genuine QB/RB scoring-format ceiling advantage**
   (Chunk 36's original finding, still fully intact).

**MCTS's final pick is governed by layer 2, not layer 1.** Chunk 38 fixed
a real problem (unfair starter classification) that turned out to be a
*different* problem from the one producing the aggregate imbalance. This
retroactively explains why Chunks 41-44's single-point mechanism hunts
(rollout internals, opponent-model coupling, replication noise) all came
up empty — they were investigating machinery downstream of, or orthogonal
to, this more basic fact.

**Regression suite:** 54 passed, 2 skipped, 4 xfailed — identical to the
last three chunks' baseline. Zero files changed, no commit. grep/worktree
confirm real draft_id untouched.

**Fix direction named by Claude Code, not built:** make bench/flex-concentration
discounting (or VBD's own replacement-level base) percentile-aware rather
than raw-points-based, so the value layer and the allocation layer share
one currency.

---

## Planning-chat note: a strategic fork worth naming before scoping Chunk 46

Chunk 45's finding raises a question this project hasn't explicitly
settled: **is "WR shortage relative to league median" actually a bug?**
Layer 2 — the layer that actually governs MCTS's picks — structurally
favors QB/RB because, under this league's real SUPERFLEX/PPR scoring
rules, QB/RB genuinely produce more raw fantasy points at matched draft
depth (Chunk 36's finding, still intact). The positional-balance
regression suite has always used "deviation from league median" as its
metric — but league median reflects what *other, human-drafted* teams
do, not necessarily what's optimal under this league's actual scoring
rules. The project's own founding vision doc is explicit that the system
should have "genuine analytical edge... because it's built on the
league's actual scoring rules" — which cuts against treating a deviation
from human norms as automatically wrong.

Given this, before committing to an invasive fix to the core value layer
(VBD/discounts/`evaluate_roster` — used by literally everything
downstream), the disciplined next step is to test whether the current
"imbalance" actually costs real value, using the project's own original
outcome-based validation methodology (Chunk 9's approach: compare
`evaluate_roster`'s risk-adjusted score across roster-construction
strategies), rather than assuming positional-count-matching is the right
target. This is cheap (reuses existing artifacts and the existing
evaluation function, no new invasive code) and directly answers the
question that actually matters before any fix is designed. Proceeding
with this as Chunk 46 — flag if a different direction is preferred.

---

## Chunk 46 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** determine whether the current (imbalanced) roster construction
actually costs expected value, or whether it's legitimately better under
this league's real scoring rules — using the project's own Chunk 9
validation methodology, not a positional-count-matching assumption. Purely
diagnostic — no fix regardless of outcome, and no change to production
`_allocate_starters`/VBD/discount code.

**Scope sent:**
1. Reuse the 5 existing full mock-draft pick logs (Chunks 41/42/45) — no
   new drafts.
2. For each draft, construct a counterfactual "positionally balanced" my-roster:
   at each of "my" 15 picks, instead of the system's actual historical
   recommendation, take the best-available player (by raw VBD) among
   positions currently below a target quota approximating league-median
   counts (roughly QB2/RB5/WR5/TE2, refine against what the other 9 teams
   in these same drafts actually ended up with) — a simple constrained-greedy
   alternative, same spirit as Chunk 9's VBD-only baseline but with an
   explicit positional cap.
3. Score BOTH the actual system roster and the balanced counterfactual
   roster from each draft using `evaluate_roster` (the same risk-adjusted
   metric Chunk 9 used to validate Draft Score's supremacy originally) —
   apples-to-apples, same function, same league scoring rules.
4. Report per-seed and aggregate: does the actual (imbalanced) roster
   score higher or lower than the balanced counterfactual? By how much
   (report the real point differential, not just win/lose)?
5. If the actual roster wins clearly: this is real evidence the "imbalance"
   is legitimate analytical edge under this league's rules, not a bug —
   state this plainly, and flag that the positional-balance regression
   suite's methodology (deviation-from-league-median) may itself be
   measuring the wrong target.
6. If the balanced counterfactual matches or wins: this supports building
   the percentile-aware value-layer fix Chunk 45 named — state this
   plainly too.
7. No production code changes. Full regression suite (expect no change).
   Standard draft_id verification at close.

**Deliverables:** the counterfactual construction methodology and target
quotas used; per-seed and aggregate `evaluate_roster` comparison with real
point differentials; a clear, evidence-based recommendation on which
strategic direction (accept as legitimate vs. build the fix) the evidence
actually supports.

---

## Chunk 46 — CLOSED, 2026-08-26, no commit — strategic fork resolved

**Methodology:** reused the same 5 pick logs, zero new drafts. Checked the
brief's guessed quota (QB2/RB5/WR5/TE2) against the other 9 teams' actual
counts across all 45 team-instances — real median differs meaningfully:
**QB=3, RB=5, WR=6, TE=1** (sums to 15) — used this instead, correctly
deviating from the brief on evidence. Counterfactual built sequentially,
pick-by-pick, holding all opponent picks fixed exactly as historically
recorded; below-quota positions get priority by raw VBD, then
best-available once all positions clear quota. One limitation logged
honestly, not corrected for: 0-1 draft-collision per seed where a
counterfactual pick coincides with a player an opponent historically took
later.

**Results — consistent across all 5 seeds, no exceptions:**

| Seed | Actual (score, counts) | Counterfactual (score, counts) | Diff |
|---|---|---|---|
| 1 | 2908.0 — QB4/RB6/TE1/WR4 | 2939.2 — QB3/RB5/WR6/TE1 | −31.2 |
| 2 | 2834.1 — QB4/WR4/RB6/TE1 | 2873.6 — QB3/RB5/WR6/TE1 | −39.5 |
| 3 | 2770.4 — RB8/QB4/TE1/WR2 | 2775.7 — QB3/RB5/TE1/WR6 | −5.3 |
| 4 | 2859.4 — WR6/RB5/QB3/TE1 | 2863.2 — RB5/WR6/QB3/TE1 | −3.8 |
| 5 | 2841.2 — RB7/WR4/QB3/TE1 | 2976.7 — RB5/WR6/QB3/TE1 | −135.5 |

**Aggregate mean diff: −43.1. The balanced counterfactual wins 5/5 seeds,
using `evaluate_roster` unchanged** — the system's own risk-adjusted
metric. Seed 4 (smallest gap) is exactly the draft where the actual
roster already landed closest to the balanced quota — internally
consistent with the pattern, not an outlier.

**Verdict, resolving the strategic fork from Chunk 45: the imbalance is
NOT legitimate analytical edge — it actively costs real expected
risk-adjusted value**, by margins from a few points up to 135, with zero
seeds going the other way. This supports building the value-layer fix,
not accepting the current behavior.

**Planning-chat note on why this result is meaningful, not circular:**
using `evaluate_roster` (the system's own unmodified metric) to show a
different sequence of picks it *didn't* choose scores higher by its own
standard is real evidence of an internal inconsistency — not just
"balance looks nicer." It implies MCTS's rollout-time reward and the
final roster evaluation aren't well-aligned, which is exactly consistent
with Chunk 45's finding that starter-allocation (percentile, used
mid-rollout) and value-maximization (raw points, used for final scoring)
run on different currencies. A currency-unification fix should resolve
both the positional imbalance and this MCTS-underperforms-a-simple-heuristic
anomaly at once, if it's correctly targeted.

**Housekeeping:** regression suite identical to the last 4 chunks'
baseline (54 passed, 2 skipped, 4 xfailed). Zero production code touched,
no commit. grep/worktree confirm real draft_id untouched.

**Claude Code's proposed fix direction, flagged for correction before
scoping the fix chunk:** the report suggests making the value layer
"percentile-aware." **This planning chat is overriding that specific
framing** — Chunk 45's own Task 1 found percentile-within-position
*overcorrects past* WR's favor (QB percentile 82.3 vs. WR's 94.4 at rank
24 — the wrong direction for a shared currency). Swapping the value
layer's currency to percentile risks trading today's QB/RB-favoring bug
for a WR-favoring one — the same overcorrection shape that already bit
this project twice (Chunk 20's generic discount, Chunk 33's near-miss on
RB). The better candidate currency is **VBD** — already computed,
already SUPERFLEX-demand-aware (built specifically for this in Chunk 2),
and not shown to have Chunk 45's overcorrection problem.

---

## Chunk 47 — SENT to Claude Code, 2026-08-26, report pending

**Structure: cheapest test first, gated, before the invasive architectural
change.** Before redesigning what currency the value layer uses (a
Chunk-38-scale invasive change touching `portfolio.py`'s discount logic
and/or `vbd.py`'s replacement-level computation, used by every downstream
consumer), test whether the existing, already-position-aware discount
constants can resolve this under *current* code first. This matters
because the landscape genuinely changed since the last time these
constants were swept: **Chunk 35 found sweeping `BENCH_DISCOUNT_BASE["WR"]`
from 0.20 to 0.60 (3x) had ZERO effect** — but that null result was
measured *before* Chunk 38 fixed starter-allocation. Now that starter/bench
status is decided differently (percentile, not raw points), the same
sweep may behave completely differently. This hasn't been tested
post-Chunk-38 and is worth 1-2 hours before committing to a larger fix.

**Scope sent:**
1. **Gate — re-sweep `BENCH_DISCOUNT_BASE`/`DECAY["WR"]` under CURRENT
   (post-Chunk-38) code**, same methodology as Chunk 33's TE sweep and
   Chunk 35's original (now-stale) WR sweep. Use TWO joint success
   criteria this time, not just position-count deviation: (a) the
   standard positional-balance regression metric, AND (b) Chunk 46's
   `evaluate_roster`-based actual-vs-balanced-counterfactual comparison,
   re-run at each sweep value. Also sweep a light RB/QB check alongside
   (same precaution Chunk 33 applied to RB) to catch any new
   overcorrection early.
2. **If the sweep fully closes the gap on both metrics:** this is the
   fix — far smaller footprint than a currency redesign, same precedent
   as Chunk 33. Pick the calibrated value, validate with the full
   regression suite, negative control, and a fresh production mock draft.
   Done, no architectural change needed.
3. **If the sweep does NOT close the gap (replicates Chunk 35's null
   finding even post-Chunk-38):** this is strong evidence a currency-level
   change really is necessary. Design and build the larger fix: make
   `portfolio.py`'s bench/flex-concentration discount operate on **VBD**
   (value above position-specific, SUPERFLEX-demand-aware replacement
   level — Chunk 2's existing computation) rather than raw
   `projected_points`. Do NOT use percentile as the shared currency — Chunk
   45 showed it overcorrects in the wrong direction for this specific
   purpose. Leave `evaluate_roster`'s actual point-total simulation on raw
   points where it directly represents real weekly scoring — the fix
   target is specifically the discount/concentration multiplier logic,
   not the underlying point simulation itself. Determine and document
   precisely which pieces of the pipeline should use VBD vs. raw points,
   don't default to "everything."
4. **If proceeding with the larger fix (step 3):** treat with the same
   validation depth as Chunk 38 — this touches every downstream consumer
   of `portfolio.py`. Full 4-position regression sweep, full regression
   suite (expect a wider ripple, root-cause every failure individually,
   don't blind-repin), negative control, fresh production mock draft, AND
   re-run Chunk 46's exact `evaluate_roster` counterfactual-comparison
   methodology post-fix to directly confirm the value gap actually closes
   (not just that position counts look better).
5. Out of scope, still deferred: the ADP-margin signed-tiebreak bug,
   `opponent_model.py` performance, Track B.
6. Standard closing verification: grep + `git status`/`git diff` confirm
   real draft_id untouched; commit hash for whichever path was taken.

**Deliverables:** Step 1's sweep results on both metrics; which path was
taken and why; full validation per whichever path; git/grep confirmation.

---

## Chunk 47 — CLOSED, 2026-08-26, VBD-currency fix attempted twice, failed
twice, cleanly reverted, no commit

**Step 1 (gate): FAILED cleanly, and exposed a new RB risk in the
process.** Re-swept `BENCH_DISCOUNT_DECAY["WR"]` post-Chunk-38 (5 seeds,
30 iterations, both metrics per value):

| DECAY["WR"] | QB dev | RB dev | WR dev | TE dev | Value gap (mean) |
|---|---|---|---|---|---|
| 1.0 (baseline) | +1.0 | +1.0 | −2.0 | 0.0 | −43.1 |
| 0.7 | +1.0 | +2.0 | −2.0 | 0.0 | −51.2 |
| 0.5 | +1.0 | +2.0 | −2.0 | 0.0 | −35.0 |
| 0.3 | +1.0 | +2.0 | −2.0 | 0.0 | −26.2 |
| 0.15 | +1.0 | +2.0 | −2.0 | 0.0 | −16.5 |

**WR position-count deviation is exactly −2.0 at every value tested** —
zero effect, replicating Chunk 35's original null result even
post-Chunk-38. Worse, tightening the constant at all immediately
introduces new RB overcorrection (+1.0→+2.0). Metric (b) shows some
isolated improvement, but metric (a)'s complete non-response disqualifies
Step 2A outright.

**Diagnostic bonus, done before building anything:** directly measured
current replacement levels (QB=230.0, RB=145.1, WR=138.4, TE=186.5) and
confirmed VBD at matched rank flips decisively in WR's favor at bench
depth (rank 20: QB_vbd=−30.2 vs. WR_vbd=+56.0) — the VBD-currency
direction was directionally sound in principle before committing to build
it, which is why Step 2B was attempted.

**Step 2B — built twice, validated twice, made things worse both times,
reverted:**

- **Attempt 1** (`contributed = replacement + (raw − replacement) ×
  discount`): value gap worsened −43.1→−90.9. Root cause found by hand:
  this formula adds a position's full replacement level back in
  regardless of discount — since QB's replacement (230) is the largest,
  this makes bench QBs look *more* valuable, the opposite of intended.
- **Attempt 2** (`contributed = raw − replacement × (1 − discount)`,
  algebra corrected, hand-verified to correctly reverse the QB-vs-WR bench
  comparison at rank 10: QB 88.7 < WR 109.9 vs. the old formula's QB
  238.1 > WR 151.8). Cleanly implemented and threaded through
  `recommend()`/`_run_iteration`/`_roster_aware_marginal_value`/
  `_roster_aware_pick`/`_adaptively_resolve_tie`/`evaluate_roster`
  (default `None` preserves old behavior for every non-MCTS caller).
  Re-validated: WR deviation still exactly −2.0, **value gap worsened
  further to −106.7.**

**Root cause of the second failure, worked out from the numbers — and
this is the real finding of the chunk:** both formulas share a flaw —
they replace Chunk 10's calibrated "discount decays toward zero" property
with "discount decays toward a large positive floor" (replacement level),
inflating every position's bench value and undoing the Chunk 9/10/33
QB-glut/TE-glut fixes, which were specifically built around a decay-to-zero
assumption (confirmed directly: QB counts got *more* erratic under the
fix, seed3→7 QBs, seed4→5 QBs). **More fundamentally: Chunk 45's own Task
2 data already showed 44/52 (85%) of WR-passed-over instances are
starter-vs-starter comparisons (`taken_would_start=True`), where
discount=1.0 for BOTH candidates — this entire fix family is a
mathematical no-op by construction for 85% of the actual problem.** The
fix was built correctly to spec; the spec targeted a layer that isn't the
dominant driver.

**Reverted cleanly** via `git checkout --`, confirmed `git diff` empty,
working tree matches Chunk 41's commit exactly. Full attempted diff
(110+79 lines) saved to scratch (`chunk47_attempted_fix.diff`) for
reference, not applied. Regression suite on the reverted codebase:
identical baseline (54 passed, 2 skipped, 4 xfailed). No commit.

**For the planning chat, stated directly by Claude Code:** this closes
out the bench/flex-concentration-discount fix family as a dead end, with
two independent, decisive negative results — not one thin data point.
The real lever, per the 85% figure, has to touch how starter-vs-starter
raw-points comparisons feed `evaluate_roster`'s top-line mean — a more
invasive change than a discount-multiplier tweak, and one the Chunk 47
brief explicitly fenced off ("leave `evaluate_roster`'s point-total
simulation on raw points"). That fence may need reconsidering — flagged
as a real scoping decision, not guessed at.

**Planning-chat reframing:** Chunk 46 already proved, using *unmodified*
`evaluate_roster`, that a balanced roster scores higher than the actual
one. The leaf-level evaluation already "knows" balance is better — so the
bias likely isn't in how a final roster gets scored, it's in what MCTS's
search actually *explores*. Leading hypothesis: `_roster_aware_pick` (the
policy simulating "my" future picks *within* a rollout, last touched in
Chunk 13 for a related-but-different bug) is itself greedy on raw points,
so rollout continuations systematically keep stacking QB/RB regardless of
root candidate — under-exploring the balanced region of outcome-space
rather than mis-scoring it once found. Before testing that hypothesis
directly, run the cheap, well-precedented check this project already used
to resolve the entire tie-break saga (Chunk 25): does the imbalance shrink
at drastically increased iteration budget? If yes, this is primarily a
search-budget/exploration problem. If no even at high budget, that
confirms a genuine, budget-independent bias in the rollout continuation
policy itself.

**Checkpoint worth naming:** this thread is now 9+ chunks deep (38-47)
with two reverted fix attempts, heading into genuinely foundational
search-behavior territory. Chunk 48 is being treated as a real decision
point — if it doesn't produce a clean, well-scoped, low-risk fix path,
the recommendation will be to document this as a known limitation and
redirect remaining runway to Track B and the ADP-margin tiebreak bug,
both confirmed and considerably cheaper to close.

---

## Chunk 48 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** diagnostic only, no fix. Determine whether the WR/QB imbalance
is primarily a search-budget/exploration problem (MCTS under-sampling the
balanced region of outcome-space) or a genuine, budget-independent bias in
`_roster_aware_pick`'s rollout-continuation policy.

**Scope sent:**
1. **Gate — iteration-budget test.** For 2-3 existing frozen decision
   points (reuse artifacts already on disk, same methodology as Chunk
   25's forced-root test), run MCTS at a drastically increased iteration
   budget (~2000-3000, matching Chunk 25's precedent) vs. production
   budget (~20-30 effective per candidate). Does the resulting
   recommendation/candidate ranking shift toward WR / more balanced
   choices as budget increases? Report the actual shift, not just
   direction.
2. If budget clearly resolves it: this is an exploration problem, not a
   policy bias — report this plainly, and note the practical tension (a
   fix here would mean either accepting the live-draft time budget
   constraint as a real limitation, or finding a cheaper way to bias
   exploration toward balanced continuations without brute-forcing more
   iterations).
3. If budget does NOT resolve it even at high multiples: instrument
   `_roster_aware_pick` directly — across many simulated rollout
   continuations branching from a few different fixed early-roster
   states (some already QB/RB-heavy, some already balanced), does the
   policy systematically favor drafting additional QB/RB regardless of
   starting state? Root-cause precisely where/why, same evidentiary bar
   as every prior chunk — a specific mechanism, not a general area.
4. No fix in this chunk regardless of outcome. State clearly what a
   Chunk 49 fix would need to target, and give an honest read on how
   invasive and how confident that fix would be — this feeds directly
   into the checkpoint decision named above.
5. Out of scope, still deferred: ADP-margin signed-tiebreak bug,
   opponent_model.py performance, Track B.
6. Standard closing verification: grep + git status/diff confirm real
   draft_id untouched.

**Deliverables:** iteration-budget test results with actual numbers;
budget-vs-policy-bias verdict; `_roster_aware_pick` instrumentation and
root cause if warranted; a clear, honest recommendation for whether Chunk
49 should attempt a fix or whether this is the point to stop and document
as a known limitation; full regression suite; git/grep confirmation.

---

## Chunk 48 — CLOSED, 2026-08-26, precise deterministic root cause found,
no commit

**The strongest result this thread has produced.**

**Task 1 — iteration-budget test: mixed, doesn't clear the "clearly
resolves" bar.** 3 points, 150 vs. 2400 iterations (16x):

| Point | Production gap | High-budget gap | Verdict |
|---|---|---|---|
| seed3/pick87 (Pollard RB vs. Meyers WR) | 6.9 | 3.6 | Narrows, doesn't resolve |
| seed4/pick27 (Allen QB/McBride TE vs. Nacua WR) | 11.5 | 13.4 | Doesn't narrow, widens slightly |
| seed5/pick87 (Pollard RB vs. Meyers WR) | 4.5 | 1.6, flips to within-noise | Genuinely resolves |

1/3 converges, 2/3 don't. Correctly triggered Task 3 per the brief's own
branching logic rather than over-interpreting an ambiguous result either
way.

**Task 3 — direct policy instrumentation: clean, decisive, budget-independent.**
Built 3 synthetic "my roster" states (QB-heavy, balanced, WR-heavy) over
the IDENTICAL 86-player available-candidate pool, called
`_roster_aware_pick`/`_roster_aware_marginal_value` directly — zero MCTS
search, zero randomness:
- **QB-heavy roster** (already 3 QBs): correctly picks RJ Harvey (RB) —
  the 3 candidate QBs get properly bench-discounted (marginal value
  15-22 vs. raw 200-296). **Working as intended here.**
- **Balanced roster** (1 QB, 2 RB, 2 WR): picks Caleb Williams (QB),
  undiscounted marginal value 296.1, beating Jakobi Meyers (WR,
  undiscounted 201.7) purely on raw points.
- **WR-heavy roster** (1 QB, 1 RB, 3 WR): **identical result** — Caleb
  Williams again, marginal value 296.1, byte-identical to the balanced
  case. The function's output doesn't move at all despite the roster
  already carrying real WR depth.

**Exact root cause, `app/services/mcts.py:486-489`,
`_roster_aware_marginal_value`'s starter branch:**
```python
if pid in starter_ids:
    if pid in flex_ranks:
        return candidate["projected_points"] * flex_concentration_discount_for(candidate.get("position"), flex_ranks[pid])
    return candidate["projected_points"]
```
Returns raw, undiscounted value for any would-start candidate, with zero
awareness of roster composition — confirmed a pure function of
would-start status alone. **The identical gap exists in `evaluate_roster`
(portfolio.py)**, for the same structural reason:
`FLEX_CONCENTRATION_DISCOUNT_BASE = {"TE": 0.5}` only ever discounts TE —
QB/RB/WR all default to 1.0 at any `flex_rank`.

**Critical clarification this instrumentation surfaced (not assumed going
in): this can't be fixed by extending `FLEX_CONCENTRATION_DISCOUNT` to QB
the way Chunk 20 did for TE.** That mechanism fires on `flex_rank≥2`
(same-position crowding of the shared pool) — but this league's
SUPER_FLEX count is exactly 1, so a 2nd QB entering the shared pool is
structurally always `flex_rank=1` for itself (Chunk 20's own documented
reason QB was left exempt originally). **The gap isn't same-position
crowding; it's an uncosted cross-position comparison at the moment a
shared slot gets filled** — a materially different, more invasive
mechanism than Chunk 20's fix, and precisely the layer both of Chunk 47's
reverted attempts left untouched (they only ever changed the
discount<1.0 bench-value math; this finding lives entirely in the
discount=1.0 starter branch).

**Verdict: primarily a rollout-policy bias, not a search-budget problem.**
Task 1 alone was ambiguous; Task 3 makes it conclusive — reproduces
deterministically with zero search, zero randomness, holding the
candidate pool fixed and varying only roster composition.

**Claude Code's direct, calibrated recommendation:** this is real,
precisely-located progress — the first exact function/line citation this
whole thread has produced (Chunks 42-44 all ended in elimination; Chunks
45-46 diagnosed a two-layer problem but pointed Chunk 47's fix at the
wrong layer). A targeted fix at lines 486-489 plus its `evaluate_roster`
counterpart is worth attempting. But stated directly, not optimistically:
building genuine cross-position, scarcity-aware shared-slot valuation is
new logic, not a constant tweak — closer in shape to Chunk 38's own
invasive rewrite than to Chunk 33's calibration. Given ~25-30 min
regression cycles, multiple validation rounds typically needed, and that
Chunk 47 needed two attempts before failing outright: real but not high
confidence of a validated fix landing in a single chunk before
2026-09-07. If Chunk 49 doesn't converge cleanly on its first attempt,
recommendation is to document this as a known, well-understood limitation
rather than force a rushed fix in the final stretch. Practical note: the
fix direction (cross-position shared-slot valuation) doesn't touch
iteration count, so Chunk 27's 60s-pick-timer latency concern isn't
directly implicated either way.

**Housekeeping:** full regression suite identical to every recent
chunk's baseline (54 passed, 2 skipped, 4 xfailed). Zero files changed,
no commit. grep/worktree confirm real draft_id untouched.

---

## Chunk 49 — SENT to Claude Code, 2026-08-26, report pending

**Framing: this is the one well-scoped attempt before falling back to the
Chunk 47/48 checkpoint.** Given Claude Code's own calibrated "real but
not high" confidence, this chunk is structured to give the best possible
single shot: cheap synthetic verification first (reusing Chunk 48's exact
proven methodology) before any expensive full-pipeline validation, with
an explicit stop condition if the cheap check doesn't confirm the design
works as intended.

**Design direction, given precisely (not left fully open, given the
track record on this thread) — verify before generalizing:**

The fix should distinguish DEDICATED slots (QB1, RB1/RB2, WR1/WR2 — each
only ever fillable by one position, no cross-position competition, Task 3
confirmed these already work correctly) from SHARED slots (`pid in
flex_ranks` — the 3×FLEX and 1×SUPER_FLEX slots, where multiple positions
genuinely compete for the same slot). For candidates filling a SHARED
slot specifically, replace `candidate["projected_points"]` (raw) with a
value based on VBD (value above position-specific, SUPERFLEX-demand-aware
replacement level — already computed, already correctly calibrated for
this league's 2-QB demand since Chunk 2), THEN apply the existing
`flex_concentration_discount_for` on top unchanged (still relevant for
same-position crowding within FLEX, e.g. 2 TEs both flex-eligible).
Dedicated-slot candidates keep raw `projected_points` exactly as today —
Task 3 showed that part isn't broken, don't touch it.

**Explicit guardrail: do NOT reach for Shapley here.** The marginal-contribution
concept needed is conceptually similar to what Shapley already computes,
but Shapley is deliberately expensive (Monte Carlo permutation sampling)
and Chunk 8 deliberately decided it's never blended into the core score.
Wiring Shapley into MCTS's per-rollout-step reward would violate that
explicit, load-bearing founding principle and also blow the latency
budget. This needs a cheap, targeted VBD-based adjustment specific to the
shared-slot case, not a general blend.

**Scope sent:**
1. **Cheap gate first.** Before touching production code broadly,
   implement the VBD-based shared-slot valuation and immediately re-run
   Chunk 48's EXACT Task 3 methodology (same 3 synthetic roster states,
   same 86-player pool, zero MCTS/randomness). Confirm: does the
   WR-heavy roster's marginal value for a shared-slot QB candidate now
   differ from the balanced roster's — i.e., does composition finally
   matter? Does a genuinely-warranted QB (filling real SUPERFLEX need,
   no existing depth) still win cleanly, preserving the legitimate
   premium — reuse the spirit of Chunk 38's own "picks 27/47 must still
   hold" check, adapted to this context. **If this synthetic check
   doesn't show the intended behavior cleanly, STOP here and report back
   — do not proceed to the expensive full validation cycle on a design
   that hasn't been shown to work at the cheap gate.**
2. **If the gate passes:** apply the same fix consistently to both
   `_roster_aware_marginal_value` (mcts.py) and its `evaluate_roster`
   counterpart (portfolio.py) — Chunk 48 confirmed the identical gap
   exists in both. Add a regression test that would catch these two
   drifting apart again (same hardening precedent Chunk 43 was scoped for
   but never reached).
3. **If proceeding, full validation at Chunk 38-scale depth** (this
   touches every downstream consumer of both functions): full 4-position
   regression sweep, full regression suite (expect a real ripple, expect
   more failures than a calibration chunk — root-cause each individually,
   do not blind-repin), negative control, fresh production mock draft,
   AND re-run Chunk 46's exact `evaluate_roster` counterfactual-comparison
   methodology post-fix to confirm the actual value gap closes (the real
   bar for success — position counts alone were already shown
   insufficient).
4. **Be honest in the final report about confidence and outcome either
   way.** If this converges cleanly: full validation as above, commit. If
   it doesn't converge on this attempt (design doesn't hold up in
   full-pipeline validation even after passing the synthetic gate, or a
   second design attempt would be needed): revert cleanly, report exactly
   what was learned, and say so plainly rather than attempting a third
   iteration within the same chunk — per the checkpoint from Chunks 47-48,
   that would be the point to stop and document as a known limitation
   rather than continue.
5. Out of scope, still deferred: ADP-margin signed-tiebreak bug,
   opponent_model.py performance, Track B.
6. Standard closing verification: grep + git status/diff confirm real
   draft_id untouched; commit hash if the fix lands.

**Deliverables:** the cheap-gate synthetic verification results (pass/fail,
with numbers); if proceeding, full validation results at Chunk-38 depth
including the post-fix Chunk-46-style value-gap check; an honest final
verdict — fixed and validated, or reverted with lessons for documentation.

---

## Chunk 49 — CLOSED, 2026-08-26, gated out at Step 1, reverted, no commit

**The fix, as built:** distinguished dedicated slots (unchanged, raw
points) from shared FLEX/SUPER_FLEX slots — for shared-slot candidates,
value became `(raw − replacement) × flex_concentration_discount` instead
of `raw × flex_concentration_discount`. Same plumbing pattern as Chunk 47,
gated on `pid in flex_ranks` only.

**Step 1 gate: both checks failed, each with a full, verified
explanation.** Two real methodology issues found and fixed along the way
first: a harmless debug-script key bug, and a real one — `_allocate_starters`
fills the dedicated slot with whichever same-position player has the
highest raw points (not draft order), so a synthetic "existing QB" could
get silently displaced into the shared pool, invalidating the comparison.
Fixed by anchoring to Josh Allen (372.9, higher than every test
candidate). Also found mid-chunk that QB/WR replacement-level gaps
collapse within 2-3 rounds in a real SUPERFLEX draft (already crossed by
pick 27) — retested at an earlier depth (pick 21) to give the fix a fair
shot where the targeted gap still exists.

- **Check (a) — FAILED, by mathematical necessity, not a bug.** A
  shared-slot QB candidate's value was still byte-identical (152.7)
  between "Balanced" and "WR-heavy" states, confirmed at two depths.
  Root cause: `replacement_levels` is a league-wide quantity — nothing in
  this design can make a candidate's VBD depend on the roster's own
  WR-vs-RB mix, only on how many players you already have at that
  candidate's *own* position. The check as specified was asking this
  design to do something it structurally cannot do.
- **Check (b) — FAILED, for a real, distinct, concerning reason.** With
  zero existing QBs (maximal uncontested SUPERFLEX need), the policy
  chose Bijan Robinson (RB) over every QB candidate. Traced directly: the
  fix cuts QB's shared-slot value by ~140 points (replacement subtraction)
  while leaving RB/WR's *dedicated*-slot value untouched — so a
  merely-comparable RB can now beat a genuinely-needed QB purely because
  only one side of the comparison took a VBD haircut. **This is exactly
  the "must not break the legitimate SUPERFLEX premium" failure mode
  Chunk 38 explicitly guarded against for its own fix.**

**Correctly stopped at the gate** — did not proceed to Step 2/3's
validation cycle on a design already shown not to work.

**Reverted cleanly:** `git diff` empty, working tree matches Chunk 48's
commit exactly. Attempted diff (360 lines) saved to scratch, not applied.
Regression suite identical to baseline. No commit.

**Claude Code's direct, honest verdict:** three reverted fix attempts in
a row (Chunk 47 ×2, Chunk 49 ×1) on the same underlying value-layer
problem. Chunk 48's root cause was real and precisely located, but this
chunk shows a symmetric VBD adjustment (shared-slot side only) creates a
new asymmetry against dedicated-slot RB/WR, and the design can't satisfy
"composition-aware" in the needed sense — replacement level is
structurally a league-wide, not roster-specific, quantity. A workable fix
would need either a much bigger blast radius (VBD-relative valuation on
dedicated slots too — the exact cases Chunk 48 confirmed already work
correctly) or a genuinely different mechanism entirely. **Direct
recommendation, given three attempts, three reverts, and a draft ~10
days out: stop attempting further value-layer fixes for this draft
cycle, document as a known, well-understood limitation.**

**Planning-chat decision: accepted.** This is decisive evidence, not a
failure of effort — three independently-designed, carefully-gated
attempts failing for three distinct, well-understood structural reasons
is a strong signal a low-risk fix isn't available in the remaining time.
Closing this thread (Chunks 38-49, 12 chunks) as an accepted, documented
limitation rather than continuing to iterate under time pressure.

---

## Known limitations — accepted for the 2026-09-07 draft (living section)

1. **WR/QB positional imbalance — CLOSED as accepted limitation, Chunk 49.**
   Root cause precisely located (Chunk 48): shared FLEX/SUPER_FLEX slot
   valuation ignores roster composition entirely, compounding a genuine
   SUPERFLEX scoring-format effect (Chunk 36) where QB/RB legitimately
   score more raw points at matched draft depth. Three independent,
   well-designed fix attempts failed for real structural reasons (Chunks
   47 ×2, 49). **Real-world impact** (Chunk 46, `evaluate_roster`-measured):
   mean ~43 points of risk-adjusted value left on the table relative to a
   balanced alternative (range: ~4 to ~135 across 5 tested seeds).
   **Practical guidance for draft day:** expect more QB/RB and fewer WR
   than typical league rosters, especially from round ~6-7 onward; feel
   free to manually weight toward WR if a recommendation feels off.
2. **Track B (wait-value/backfill bug) — open, unfixed.** Confirmed real
   across 3 independent samples (Chunks 32, 34 ×2) but rare (~3% of "my
   turn" points, ~29% of drafts show ≥1 instance). Occasionally takes a
   safe bench-tier player over a genuinely at-risk starter-value
   alternative. Never root-caused to an exact mechanism. Scoped below.
3. **ADP-margin signed-tiebreak bug — open, unfixed.** Found Chunk 41
   (point 2), exact location known: `mcts.py:673-675`,
   `_apply_adp_margin_tie_break` uses a signed rather than absolute-value
   margin, mishandling extremely-overdue candidates. Small, well-understood,
   low-risk — scoped for Chunk 50.
4. **`opponent_model.py` performance — never optimized** (flagged since
   Chunk 14). Currently within budget (7.89s worst-case per Chunk 27) but
   that figure predates Chunk 38/39's added per-call percentile-table
   computation — needs re-measurement.
5. **Broken duplicate `.claude/launch.json`** in the outer folder — logged
   Chunk 31, never fixed. Could cause a confusing "won't start" moment if
   triggered accidentally.

---

## Roadmap: Chunks 50-59 (draft-day readiness push)

*Original Chunks 40-50 sketch assumed 2 chunks for the WR/QB thread; it
consumed 12 (38-49). This roadmap covers what was originally slated for
the back half of that sketch, reordered by draft-day priority given ~10
days remain.*

- **50** — Close out WR/QB documentation (done as part of this chunk's
  write-up) + fix the small, well-scoped ADP-margin tiebreak bug.
- **51** — Diagnose Track B properly, reusing Chunk 48's proven
  direct-instrumentation methodology (synthetic states, zero randomness)
  instead of the slower single-point Monte Carlo approach used in
  Chunks 32/34 — should be faster and more decisive this time.
- **52** — Fix Track B, contingent on 51's findings. Likely lower blast
  radius than the WR/QB thread given it's ~3% of decisions and not yet
  shown to be architecturally entangled the way that was.
- **53** — Full regression + stress sweep on current code, and re-run
  Chunk 27's exact latency benchmark — several rounds of added computation
  since then (percentile tables, replay harness) haven't been
  re-measured against the 60s pick-timer budget.
- **54** — Full live/practice mock draft through the production UI (same
  format as Chunk 31 Task 3) — the primary "does this work end-to-end,
  right now" checkpoint. Compare against the documented known-limitations
  list to confirm no *new* surprises, not just re-litigate old ones.
- **55** — Triage findings from 54; fix anything broken or surprising
  that isn't already an accepted, documented limitation.
- **56** — Operational readiness: websocket reconnect behavior, state
  recovery if the app restarts mid-draft, a foolproof pre-flight check
  that `SLEEPER_DRAFT_ID` points at the real draft, fix the broken
  duplicate `launch.json`.
- **57** — Final open-items triage: explicit go/no-go on
  `opponent_model.py` performance and any UI polish, given fresh Chunk 53
  numbers and remaining time — sort what's truly in scope for 09-07 vs.
  Phase 1.5 backlog.
- **58** — Build the draft-day runbook: pre-draft checklist, the
  known-limitations list above in plain language, what to do if the app
  misbehaves mid-draft, fallback plan if MCTS stalls (e.g. raw VBD
  display).
- **59** — Final full dress rehearsal under realistic draft-day pace, as
  close to real conditions as safely possible — last confidence check
  before 2026-09-07.

---

## Chunk 50 — SENT to Claude Code, 2026-08-26, report pending

**Two small, unrelated, low-risk tasks — a deliberate change of pace
after 12 chunks on one hard thread.**

**Scope sent:**
1. **Document the WR/QB decision in-repo**, not just in this planning
   doc — add a `KNOWN_LIMITATIONS.md` (or equivalent) at the repo root
   covering the WR/QB imbalance (root cause, magnitude, practical
   guidance) in plain language a person glancing at it during a live
   draft could actually use, not chunk-history prose. Keep it short.
2. **Fix the ADP-margin signed-tiebreak bug** (`mcts.py:673-675`,
   `_apply_adp_margin_tie_break`) — the margin should be evaluated by
   absolute value (favor whichever candidate is closer to real risk
   *in either direction*, i.e. genuinely soonest-at-risk), not signed
   (which currently treats "further overdue" as unconditionally "more
   urgent," mishandling extremely-overdue candidates like Chunk 41's
   Maye/Adams case). Root-cause-confirmed already (Chunk 41) — this
   should be a small, contained change. Validate: re-check the original
   Chunk 41 point 2 (seed2/pick54, Maye/Adams) resolves correctly, full
   regression suite, negative control, a quick multi-seed sanity sweep to
   confirm no new distortion (this touches a tiebreak mechanism used
   project-wide, so don't skip the sanity check even though the change
   itself is small).
3. Standard closing verification: grep + `git status`/`git diff` confirm
   real draft_id untouched; commit hash.

**Deliverables:** the `KNOWN_LIMITATIONS.md` content; the tiebreak fix
diff; point-54 resolution confirmation; full regression suite; sanity
sweep results; git/grep confirmation.

---

## Arc: Multi-League Expansion + League-Long Skeleton (Chunks 51+) —
rough draft, 2026-08-26

**Trigger:** Vincent joined a second Sleeper league (drafts ~3 days after
Kiddos' 09-07). Wants this tool usable for both, plus wants to start
building the league-long "Phase 2" system (trade suggester, waiver
suggester, start/bench optimizer, league dashboard/analytics) — skeleton
and UI structure only, explicitly NOT the modeling/math behind those
features yet. Explicit instruction: pause the correctness/modeling work
(Track B, the previously-planned Chunks 51-59 draft-day-readiness
sequence) in favor of this.

**Important status note, not to be lost:** the prior Chunks 51-59
roadmap (Track B diagnose/fix, full regression + latency re-check, a live
practice-draft checkpoint, operational hardening, the draft-day runbook,
final dress rehearsal) is **deferred, not cancelled.** None of that
Kiddos-specific readiness work has happened yet, and Kiddos still drafts
first (09-07). Given Vincent's stated ~10 chunks/day pace, this ~9-chunk
expansion arc is roughly a day's work, leaving runway to circle back —
but this is a real, consciously-made tradeoff worth tracking explicitly
rather than letting the original plan quietly disappear.

**Critical open risk, flagged directly:** multi-league support is only
"just an interface thing" if league 2 uses a similar format to Kiddos
(SUPERFLEX, TE premium, similar roster). If it doesn't, nearly everything
calibrated so far (Chunks 9/10/20/33's glut fixes, the whole VBD
replacement-level engine) is tuned specifically to Kiddos' exact scoring
rules and would need real recalibration, not just a config swap — and
there's no time to redo that arc before a draft only ~3 days after
Kiddos'. Chunk 51 exists specifically to resolve this unknown before any
architecture commitments are made.

**Architectural principle to hold throughout this arc:** keep the new
Phase 2 skeleton pages (55-58) additive — new routes/pages that don't
modify the existing live-draft code path — so Kiddos' draft-day
reliability isn't put at risk by feature work for a system that doesn't
need to be trustworthy until later.

**Rough chunk plan (expect 52+ to shift once 51 reports back):**
- **51** — Discover league 2's real Sleeper settings (scoring, roster,
  format, size, snake/auction, draft date/time, keepers), diff against
  Kiddos, produce an honest transfer-vs-recalibrate verdict. The gate.
- **52** — Multi-league config architecture (backend): replace hardcoded
  Kiddos constants with a real per-league config model; wire in league 2
  at whatever fidelity 51 supports. Hard requirement: negative-control
  against Kiddos — Draft Score output byte-identical before/after.
- **53** — Frontend shell: multi-league navigation + section tabs (Draft/
  Trade/Waivers/Lineup/League Dashboard) per league, matching the
  existing dark-broadcast-scoreboard identity. Live in-draft view becomes
  one tab, functionally unchanged.
- **54** — Draft Outlook view: pre-draft planning page reusing the
  existing engine in a "no picks yet" browsing mode — full rankings/tiers,
  mark/star targeted players, "who do I want at pick N." Both leagues.
- **55** — Start/Bench Lineup Optimizer: likely a cheap real win, not
  pure skeleton — `_allocate_starters` logic already exists.
- **56** — Trade Suggester skeleton: roster views + placeholder
  suggestion interaction, not the full Shapley/portfolio engine yet.
- **57** — Waiver/Free Agency Suggester skeleton: available free agents
  via Sleeper API + placeholder ranking.
- **58** — League Dashboard/analytics skeleton: real transactions feed
  (cheap, direct Sleeper API display) + clearly-labeled rough/provisional
  standings/best-team/best-draft leaderboards. Good spot for real design
  creativity per the project's original "fun, gamified" goal.
- **59** — Integration + Kiddos regression check: full regression suite +
  fresh live mock draft on Kiddos specifically, confirming this expansion
  didn't destabilize the draft-day-critical path.

---

## Chunk 51 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** diagnostic only, mirrors the very first league-settings-gathering
step this project ever did for Kiddos (Chunk 1 / the original Brainstorm
Session). No architecture decisions, no code changes to the live-draft
path — this exists purely to resolve the critical open risk above before
Chunk 52 commits to a design.

**Scope sent:**
1. Identify league 2 on Vincent's Sleeper profile (there should be
   exactly one other league beyond Kiddos, `league_id 1389755334746202112`
   — confirm this assumption rather than guessing which one if multiple
   candidates exist, and ask/flag rather than picking wrong).
2. Pull its real settings via the Sleeper API: scoring format (PPR/half/standard,
   TE premium or not, any other custom scoring), roster requirements
   (starting slots, FLEX/SUPERFLEX counts, bench size), league size,
   SUPERFLEX or standard, snake vs. auction, draft date/time, keeper
   rules (and whether any `max_keepers`-style field is a real rule or a
   dead default the way Kiddos' was — confirm directly, don't assume
   either way).
3. Direct side-by-side diff against Kiddos' confirmed config (documented
   in the overview doc and this doc's Quick Reference section).
4. Produce an honest, explicit verdict: does the existing calibrated
   engine (VBD replacement levels, bench-discount constants, TE-premium
   handling, SUPERFLEX QB-demand modeling) transfer as-is, need light
   parametrization (same mechanisms, different constants), or need
   genuine recalibration (different mechanisms entirely, e.g. no
   SUPERFLEX means the whole 2-QB-demand VBD logic doesn't apply the same
   way)? Be direct about which case this is — this determines whether
   Chunk 52 is a straightforward refactor or a much bigger problem.
5. No code changes to `vbd.py`, `mcts.py`, `portfolio.py`, or any
   live-draft path this chunk. This is a settings-gathering and
   assessment chunk only.
6. Standard closing verification: confirm neither Kiddos' nor league 2's
   real draft state was modified (this chunk should be entirely read-only
   against both leagues' Sleeper data).

**Deliverables:** league 2's full settings; the direct diff against
Kiddos; the transfer-vs-recalibrate verdict with reasoning; any
surprises or ambiguities flagged rather than assumed away.

---

## Chunk 51 — CLOSED, 2026-08-26, read-only, no code changes

**League identified cleanly, no ambiguity:** user `vjrupp4949` →
`user_id 1131040333669957632` → exactly two 2026-season leagues found.
League 2 = "Former Bradley Bums", `league_id 1389749759891214336`,
`draft_id 1389749759891214337`, status `pre_draft`.

**League 2's full settings, as discovered:**

| Dimension | Value |
|---|---|
| Scoring | Full PPR (rec=1.0), TE premium +0.5/rec, pass_yd 0.04, pass_td 4.0, pass_int −2.0, rush_yd 0.1, rush_td 6.0, rec_yd 0.1, rec_td 6.0 |
| Roster slots | QB, RB, RB, WR, WR, FLEX, FLEX, FLEX, SUPER_FLEX, BN×6 (confirmed twice — `league.roster_positions` and `draft.settings.slots_*` agree) |
| Reserve/IR slots | 1 |
| League size | 10 teams |
| Draft type | "snake" (confirmed directly) |
| Draft date/time | 2026-09-08, 6:00 PM Pacific (2026-09-09 01:00 UTC) |
| Pick timer | 90 seconds |
| Keepers | `settings.type=0` (redraft), `max_keepers=1`, all 10 rosters show `keepers: []` |
| Continuity | Has a `previous_league_id` (rolled-over league, same pattern as Kiddos) |

**Direct diff vs. Kiddos:**

| Dimension | Kiddos | League 2 | Same? |
|---|---|---|---|
| Scoring (PPR, TE premium, rates) | Full PPR, TE +0.5, standard rates | Identical, field-for-field | ✅ Same |
| Roster positions | QB/2RB/2WR/3FLEX/1SF/6BN | Identical | ✅ Same |
| Reserve slots | 1 | 1 | ✅ Same |
| League size | 10 | 10 | ✅ Same |
| Draft type | Snake | Snake | ✅ Same |
| `settings.type`/`max_keepers` | 0 / 1 | 0 / 1 | ✅ Same (dead-default pattern) |
| Draft date | **2026-09-06, 7pm PT (per this chunk — see discrepancy flag below)** | 2026-09-08, 6pm PT | Different (~2 days later) |
| Pick timer | 60s | 90s | Different — league 2 has 50% more decision time |

**Verdict: (a) TRANSFERS AS-IS.** Every dimension the calibrated engine
actually depends on — scoring, TE premium value, SUPERFLEX roster shape,
league size — is identical to Kiddos, confirmed directly from the live
API. Real corroborating evidence, not coincidence: league 2 carries a
`copy_from_league_id` in its metadata — very likely templated from an
existing SUPERFLEX/TE-premium league at creation. VBD replacement levels,
`BENCH_DISCOUNT_BASE`/`DECAY`, `FLEX_CONCENTRATION_DISCOUNT_BASE["TE"]`,
and the whole SUPERFLEX 2-QB-demand modeling arc (Chunks 2, 9, 10, 13,
33, 38) apply directly with zero recalibration. **This is a
config/interface problem for Chunk 52, not a modeling problem** — a
significant de-risking of this whole arc.

**⚠️ CRITICAL DISCREPANCY FLAGGED — RESOLVED (see Update Log):** this
chunk reports Kiddos' draft date as **2026-09-06, 7pm Pacific** — a full
day earlier than every prior reference in this project (2026-09-07, first
established Chunk 31). Most likely explanation: a UTC-vs-local-time
mixup — Sept 6, 7pm Pacific converts to Sept 7, 2am UTC, so reading the
epoch timestamp's date component in UTC without converting to local time
would produce exactly this discrepancy. **RESOLUTION: Vincent confirmed
directly via the Sleeper app — the real date/time is 2026-09-06 (Sunday),
9:00 PM, not 7pm as estimated here.** Both this chunk's estimate and the
original Chunk 31 finding were imprecise; Vincent's direct confirmation
is now the source of truth (reflected in the Standing Constraint and
Quick Reference sections above).

**Also flagged, not assumed (relayed to Vincent for confirmation):**
league 2's keeper status — evidence (redraft classification, empty
keeper lists on every roster) strongly suggests no active keepers,
matching Kiddos' own confirmed pattern, but not asserted as settled per
the brief's explicit instruction not to guess on this dimension.

**Other honest limitation noted:** could not independently rule out
Kiddos-style settings staleness in league 2's data the way Kiddos' case
was caught — league 2's `roster_positions` and `draft.settings.slots_*`
agree with each other internally, but internal agreement isn't the same
as confirming the league's real intent. Worth Vincent's own quick
gut-check that league 2's SUPERFLEX/3-FLEX structure is really what that
league means to run.

**Read-only confirmation:** `SleeperClient` has no write/mutation methods
at all — structurally incapable of writing to either league, not just
"didn't call" them. All calls were `GET` requests only. `git status`/`git
diff` confirm zero code changes.

---

## Chunk 52 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** build the multi-league config architecture. Given Chunk 51's
"transfers as-is" verdict, this is a real but well-bounded refactor —
replace hardcoded Kiddos-only constants with a per-league config model,
wire in league 2 using the SAME calibrated engine (no new modeling work
needed).

**Scope sent:**
1. Design a per-league configuration model — league_id, draft_id,
   scoring rules, roster requirements, format flags — that the backend
   can load and switch between, replacing today's module-level hardcoded
   Kiddos constants.
2. Wire in both leagues' confirmed configs: Kiddos (existing, unchanged
   values) and league 2 (from Chunk 51's findings — identical calibration
   constants, different league_id/draft_id/pick-timer/draft-date).
3. **Critical negative control, non-negotiable given Kiddos' draft is
   close:** confirm Kiddos' Draft Score output is BYTE-IDENTICAL before
   and after this refactor, for the same frozen trajectory/snapshot used
   in recent chunks. This refactor must not change Kiddos' behavior in
   any way, only make the config it currently hardcodes swappable.
4. Do not yet build new frontend routes or league-switching UI — this
   chunk is backend config architecture only, Chunk 53 covers the
   frontend shell.
5. Full regression suite. Standard closing verification: confirm both
   leagues' real Sleeper state remain untouched (read-only against both,
   same as Chunk 51) — this chunk should not draft into or write to
   either league.

**Deliverables:** the config model design; confirmation both leagues'
settings are correctly loaded; the Kiddos byte-identical negative
control result; full regression suite; git/grep confirmation.

---

## Chunk 52 — CLOSED, 2026-08-26, committed `4b347d3`

**Task 1 — inventory:** every Kiddos-specific hardcoded value traced to
`app/config.py`, consumed by 9 other modules — but always via named
constants, never scattered literals. Unusually clean refactor target.

**Design:** new `app/leagues.py` — a frozen `LeagueConfig` dataclass
(league_id, draft_id, league_name, num_teams, draft_type,
pick_timer_seconds, draft_date, scoring, roster_positions) + a `LEAGUES`
registry + an `ACTIVE_LEAGUE_KEY`/`ACTIVE_LEAGUE` selector (defaults to
`"kiddos"`). `app/config.py` now derives its existing constants from
`ACTIVE_LEAGUE` instead of hardcoding them — every consumer file needed
**zero changes**, since they still import the same names from
`app.config`. Calibrated tuning constants (bench/flex-concentration
discounts, VBD replacement-level logic) deliberately kept **global, not
per-league** — correct call, reasoned directly from Chunk 51's finding
that both leagues share the exact format those were calibrated against.

**Both leagues wired and verified:** Kiddos (unchanged) + "Former Bradley
Bums" (confirmed settings, 90s pick timer, 2026-09-08). Confirmed in a
fresh process that flipping `ACTIVE_LEAGUE_KEY` correctly propagates
every `app.config` constant.

**Negative control — the critical check, and it passed:** Chunk 40+
replay harness at 2 independent frozen points, pre-refactor vs.
post-refactor: byte-identical `recommend()` output at both, SHA256-confirmed
for one. Kiddos' Draft Score behavior provably unchanged.

**Regression suite — root-caused, not assumed fine.** 51 passed, 3
failed (baseline 54/0/2/4). Did not assume harmless — used the Chunk 39
git-stash technique: ran the exact same 3 failing tests against pure,
unmodified pre-refactor code with today's live data. **Identical
failures reproduced** — confirmed as the same live-data-drift phenomenon
already characterized in Chunks 39/41 for this exact test file
(`test_adaptive_resolution_regression.py`, picks 39/82/102), unrelated to
this chunk. Correctly not repinned (out of scope for a config-only
chunk) — flagged as a small housekeeping item for whenever convenient,
not urgent given it's fully understood and not a correctness bug.

**Housekeeping:** scope held exactly — only `config.py` (modified) +
`leagues.py` (new); no frontend, no live-draft routes, no calibration
constants touched. `git worktree list` clean. Real draft_ids appear only
as static values in `leagues.py`; zero live Sleeper API calls this
chunk; `SleeperClient` structurally read-only (no write methods exist).

---

## Chunk 53 — SENT to Claude Code, 2026-08-26, report pending

**Scope refinement from the original rough draft, explained:** the
original plan called this "frontend shell," but there's a backend piece
first — Chunk 52's `ACTIVE_LEAGUE_KEY` is a process-level default;
switching leagues currently means changing code and restarting. A real
switcher needs per-request league selection. Key simplification: Kiddos
drafts 2026-09-06, league 2 drafts 2026-09-08 — **they never overlap in
time**, so true concurrent *live* drafting is never actually needed. Only
the planning/browsing views (rankings, outlook) need real per-request
league-switching; the live in-draft view can keep operating on a single
active-league config, just pointed at whichever league is actually
drafting that day. This meaningfully de-risks the backend work — no need
for a heavier concurrent-sessions architecture.

**Scope sent:**
1. Extend planning/browsing-oriented API routes (NOT the live-draft
   websocket/polling routes — leave those untouched) to accept a
   `league_key` parameter, loading the corresponding `LeagueConfig` from
   Chunk 52's registry per-request rather than relying on the process-level
   default. Scope this to whatever routes actually serve non-live data
   (rankings, VBD board, etc.) — inventory what exists first.
2. Leave the live in-draft view/websocket path exactly as today
   (single active-league config) — do not add per-request league
   switching there. Confirm this explicitly rather than assuming it by
   omission.
3. Basic frontend navigation shell: a league switcher (Kiddos / Former
   Bradley Bums) for the planning views, in the existing dark-broadcast-scoreboard
   visual identity — not a generic default-looking tab bar. The existing
   live-draft view becomes one section within this shell, functionally
   identical to today.
4. **Negative control, required:** confirm Kiddos' existing live-draft
   functionality (websocket polling, tiered recompute, everything from
   Chunk 12 onward) is completely unchanged — the route-extension work in
   task 1 must not leak into or modify live-draft behavior in any way.
5. Full regression suite. Standard closing verification: confirm both
   real leagues' Sleeper state remain untouched (read-only only).

**Deliverables:** inventory of routes extended; confirmation the live
path is untouched; the navigation shell; negative control result; full
regression suite; git/grep confirmation.

---

## Chunk 53 — CLOSED, 2026-08-26, committed `be5e79a`

**Route classification:** live-draft-path (`/ws/draft`, `live.py`,
`draft_live.py`) — untouched, as required. `/api/league-check` —
correctly identified as diagnostic/not a planning consumer and explicitly
left out of scope, rather than either silently extending or silently
ignoring it. Planning/browsing routes (`/api/rankings`,
`/api/mcts/recommend`, `/api/draft-score`, `/api/portfolio/evaluate`,
`/api/shapley/evaluate`, `/api/simulate/*`) — extended with `league_key`.

**Design:** `_shared.py`'s new `resolve_league()` validates `league_key`
against the Chunk 52 registry, defaults to current behavior when
omitted, threads into `DraftState` for the hypothetical branch only — the
live branch (`use_live_draft=true`) completely unaffected.

**Important architectural finding, honestly surfaced — a real, tracked
limitation:** `vbd.py`/`projections.py` still read `NUM_TEAMS`/
`ROSTER_POSITIONS`/`SCORING` as **globals**, not from the per-request
resolved league config. This means per-league routing currently exists at
the dispatch layer, but computation still depends on a single shared
global config — this would silently compute WRONG numbers for a
differently-formatted third league if one were ever added. Claude Code
built a 409 guard that rejects any `league_key` whose format diverges
from the active global config, and **verified the guard actually fires**
with a deliberately mismatched test league (not just assumed working).
Since both real leagues are confirmed identical format (Chunk 51), this
never blocks anything today — but it's real architectural debt, not
resolved, just safely fenced off. **Tracked as a known limitation below.**

**Frontend nav shell:** Live Draft / Rankings tabs + Kiddos / Former
Bradley Bums league switcher, matching the dark scoreboard identity —
verified live in-browser (correct `league_key` on each network request,
Live Draft section unaffected).

**Negative control:** ran an actual mock draft end-to-end post-change —
cheap board, expensive MCTS recompute, tiered updates all fired
identically to pre-chunk.

**Regression suite:** 51 passed, 2 skipped, 4 xfailed, 3 failed — the
same 3 live-data-drift failures from Chunk 52, this time reasoned as
**structurally impossible** for this chunk to have caused (the failing
test calls `mcts_service.recommend()` directly, bypassing every file this
chunk touched) — an even stronger argument than Chunk 52's git-stash
comparison, since it's a direct code-path argument rather than requiring
a live re-run.

**Housekeeping:** `git status` clean, grep confirms both real draft_ids
appear only as read-only definitions in `leagues.py`, no writes anywhere
in the diff. Commit `be5e79a`.

---

## Known limitations (addendum): architecture

6. **Per-league computation isn't fully wired end-to-end** — routing/config
   selection works per-request (Chunk 53), but `vbd.py`/`projections.py`
   still consume global constants for actual computation, not the
   resolved per-request config. Safely fenced with a verified 409 guard;
   doesn't affect either real league today (confirmed identical format).
   Would need real work if a third, differently-formatted league is ever
   added — not urgent now.

---

## Chunk 54 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** build out the Draft Outlook view — Vincent's own framing:
"who do I want with the third pick, who am I trying to get at the third
pick, what's my ranking for my first pick" — a pre-draft planning page,
distinct from the live in-draft view, for browsing rankings and setting
targets before either draft actually starts. Works for both leagues via
Chunk 53's league switcher.

**Scope sent:**
1. First, audit what the existing Rankings tab (built in Chunk 53)
   already provides — don't rebuild from scratch if it already covers
   part of this. Report what's there before extending it.
2. Extend/build toward: full rankings/tiers using the actual Draft Score
   engine (not just raw VBD) for the current state (0 picks made) — this
   is what Vincent will actually reference, so it should be consistent
   with what he'll see live, not a cheaper approximation presented as
   equivalent.
3. Mark/star targeted players — some persistence mechanism so targets
   survive a page reload (simple server-side storage is fine, doesn't
   need to be fancy — a JSON file or lightweight local DB is a reasonable
   choice given the project's zero-cost constraint; use judgment on
   exact mechanism but state what was chosen and why).
4. A "likely available at pick N" view — reuse the existing ADP-based
   survival modeling (opponent_model.py's real-ADP path, not the
   proxy-rank fallback where avoidable) to show, for an arbitrary pick
   number Vincent specifies, which currently-ranked players are likely
   still on the board versus already at real risk. This does not need a
   fresh full MCTS run per hypothetical pick — reuse the existing
   survival-probability machinery already built and validated (Chunks 21,
   32, 41 etc.) rather than building something new.
5. Both leagues must work through the existing switcher.
6. Do not touch the live-draft path at all — this chunk is entirely
   within the planning/browsing surface Chunk 53 already established.
7. Full regression suite. Standard closing verification: grep + git
   status/diff confirm both real leagues' state untouched.

**Deliverables:** audit of the existing Rankings tab; what was built on
top of it; the persistence mechanism chosen for targets and why; the
pick-N survival view; confirmation both leagues work; full regression
suite; git/grep confirmation.

---

## Chunk 54 — CLOSED, 2026-08-26, committed `b7668c2`

**Audit:** existing Rankings tab was pure VBD — no simulation,
roster-awareness, or risk-adjustment. Kept for full-board browsing, now
explicitly labeled "VBD APPROXIMATION" rather than presented as
equivalent to the real Draft Score.

**Real Draft Score (`/api/outlook/top-picks`):** runs actual
`mcts_service.recommend()`, same engine as the live view. **Real bug
found and fixed:** MCTS requires it to literally be `my_slot`'s turn,
which a bare 0-picks state only satisfies for draft slot 1. Fixed by
pre-advancing the board one realization via `opponent_model.sample_pick`
(the same machinery MCTS's own rollouts use) — the simulated-pick count
is surfaced honestly in the UI rather than silently guessed. **Note for
later, not urgent:** this is a single stochastic realization per view, so
refreshing could show a different simulated pre-advance each time — fine
for a browsing tool given it's transparent about what's simulated, but a
future enhancement could aggregate across a few realizations if
consistency ever feels off.

**Target persistence:** `targets.py`, flat per-league JSON file,
deliberately git-tracked (not gitignored, unlike cache files) since it's
irreplaceable user input for a single-user tool. Verified no cross-league
leakage.

**Pick-N survival (`survival.py`):** reuses `opponent_model.sample_pick`
via Monte Carlo replay — not a fresh MCTS search per pick number, exactly
as directed. ADP ranks computed once, mirroring `mcts.py`'s own
precedent. Sanity-checked monotonic decay.

**Both leagues:** verified via TestClient and live browser testing.
**Real bug found and fixed during browser testing:** a stale-response
race condition where a slow request from an abandoned league could
overwrite the new league's panel — fixed with a captured-at-fetch-start
`league_key` guard, the standard correct pattern for this class of bug.

**Live-draft path:** untouched, `main.py`'s diff purely additive,
re-verified with an actual mock draft run end-to-end.

**Regression suite:** 51 passed, 2 skipped, 4 xfailed, 3 failed — same
pre-existing data-drift failures, no new ones. 12 new dedicated tests, all
passing, isolated from real user data via monkeypatch.

**Housekeeping:** zero references to either real draft_id outside
`leagues.py`'s registry, `git status` clean. Commit `b7668c2`.

---

## Chunk 55 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** Start/Bench Lineup Optimizer. Flagged as a likely cheap win in
the original roadmap since the underlying starter-allocation logic
(`_allocate_starters`, vbd.py) already exists and is well-tested (used
since Chunks 2, 7, 9, 10, 20, 33, 38) — this should mostly be wiring, not
new modeling.

**Important scoping note:** both leagues are still `pre_draft` — neither
has a real roster yet (Kiddos drafts 09-06, league 2 drafts 09-08). This
chunk can build and test the full mechanism against synthetic roster
data (reuse existing completed mock-draft outputs already on disk from
the replay harness work — plenty available), but genuine end-to-end
validation against real rosters has to wait until after an actual draft
happens. State this limitation clearly in the report rather than
implying it's been validated against real data it can't possibly have
yet.

**Scope sent:**
1. New endpoint (e.g. `/api/lineup/optimize`) that takes a roster (real,
   via Sleeper's roster read endpoint when available, or a
   test/synthetic roster otherwise) plus current projections, and returns
   optimal starter/bench assignment via the existing `_allocate_starters`
   logic — reuse it directly, don't reimplement.
2. Check whether bye-week or injury-status data is already available
   anywhere in the existing pipeline (it may not be — this project has
   been draft-time asset valuation, not week-to-week matchup logic, so
   far). If it's cheaply available, incorporate it; if not, don't build
   new schedule-awareness infrastructure from scratch this chunk — note
   what's missing rather than silently ignoring it.
3. Frontend: a new "Lineup" tab in the nav shell, both leagues via the
   existing switcher, matching the established visual identity.
4. Test against synthetic roster data (existing mock-draft outputs on
   disk) since no real rosters exist yet. Clearly state this limitation
   in the report.
5. Do not touch the live-draft path. Full regression suite — expect no
   change beyond the 3 known pre-existing failures.
6. Standard closing verification: grep + git status/diff confirm both
   real leagues' state untouched (this chunk should be read-only against
   real Sleeper data even where it reads roster info).

**Deliverables:** the optimizer endpoint and its reuse of
`_allocate_starters`; bye-week/injury-data availability check and what
was done about it; the Lineup tab; synthetic-data test results with the
real-data-validation caveat stated explicitly; full regression suite;
git/grep confirmation.

---

## Chunk 55 — CLOSED, 2026-08-26, committed `38f9bff`

**Task 1 — optimizer endpoint:** `/api/lineup/optimize` calls
`vbd.allocate_roster_starters_with_flex_ranks` directly, cross-checked
byte-identical, not reimplemented. Supports synthetic `player_ids` and a
real, read-only Sleeper `use_live_roster` path (`roster_id` required
explicitly). **Notable finding: this codebase has never tracked which
Sleeper roster is "mine"** — worked around here by requiring `roster_id`
explicitly. **Flagged for Chunk 56: this will recur for Trade Suggester,
Waiver Suggester, and the League Dashboard, all of which need "my roster
vs. everyone else's" as a basic building block — worth solving once as
shared infrastructure rather than re-solving per feature.**

**Task 2 — bye-week/injury:** bye-week explicitly flagged out of scope
(no schedule data source exists anywhere in this pipeline). Injury
status was cheaply available — Sleeper's already-cached `injury_status`
per player, added via a one-line fix in `projections.py`, surfaced as a
separate field rather than blended into `projected_points` — correctly
respects the "no invented weighted averages" principle rather than
folding an unmodeled signal into the point estimate.

**Task 3 — Lineup tab:** search-and-add roster builder + "Load from
Sleeper" button, verified in-browser for both leagues.

**Task 4 — synthetic testing:** validated against a real completed
roster reused from Chunk 41's on-disk mock-draft artifact (not newly
generated). Real-roster-validation caveat stated explicitly in code and
commit message.

**Bug found and fixed:** an explicitly-empty `player_ids: []` was wrongly
rejected the same as an omitted field — fixed to distinguish `None`
(omitted) from `[]` (a genuine empty roster), directly relevant to Task
7's pre-draft case.

**Task 5 — live-draft path:** untouched, `main.py`'s diff purely
additive, re-verified with an actual mock draft run.

**Task 7 — empty pre-draft rosters:** confirmed via real read-only
`get_rosters` calls against both actual leagues — Sleeper currently
returns `players: null` for both, handled gracefully as a 200 with an
explanatory note, not an error.

**Regression suite:** 71 passed, 2 skipped, 4 xfailed, 3 failed — same 3
pre-existing failures (picks 39/82/102). Root-caused, not assumed:
git-stashed to pure pre-Chunk-55 code, re-ran against today's live data —
byte-identical wrong names under both versions, conclusively confirming
continued data drift, not a regression. 8 new Chunk 55 tests all passed
(the jump from the prior "51 passed" baseline to 71 reconciles cleanly:
51 + Chunk 54's 12 new tests + Chunk 55's 8 new tests = 71, now all
merged into one combined run rather than reported separately as in
Chunk 54).

**Housekeeping:** zero references to either real draft_id outside
`leagues.py`'s registry, `git status` clean. Commit `38f9bff`.

---

## Chunk 56 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** resolve the "my roster" infrastructure gap first, then build
the Trade Suggester skeleton on top of it — explicitly UI/structure only,
not the real Shapley/portfolio trade-value engine yet.

**Scope sent:**
1. **Shared infrastructure first:** resolve and expose "my roster_id"
   per league — match a roster's `owner_id` against the known Sleeper
   `user_id` (1131040333669957632, from Chunk 51) for both leagues. Cache
   this somewhere sensible and reusable (the Chunk 52 `LeagueConfig`
   registry, or a small shared utility — use judgment, but make it
   genuinely reusable so Chunks 57/58 don't have to re-solve this). This
   should also let Chunk 55's lineup endpoint stop requiring explicit
   `roster_id` for "my" roster specifically, if that's a cheap
   improvement to make while here — note whether you did this or left it,
   don't silently skip it either way.
2. **Roster browser:** a way to view any roster in a league — mine and
   all 9 opponents' — reusing the roster-read infrastructure already
   built in Chunk 55.
3. **Trade Suggester skeleton:** a new "Trade" tab where Vincent can
   manually select players from his roster and an opponent's roster to
   propose a hypothetical trade, and see a **simple raw-value comparison**
   (sum of raw VBD or projected points on each side) — explicitly NOT
   Shapley marginal-contribution analysis, NOT season-simulation-based
   trade impact, just a transparent, easily-understood value gut-check.
   This is manual exploration, not proactive trade suggestions — don't
   build "who should I trade with" logic yet, that's real modeling work
   for later.
4. Both leagues via the existing switcher. Same synthetic-data caveat as
   Chunk 55 applies — neither league has real rosters yet, test against
   existing mock-draft artifacts and state the real-data-validation
   limitation explicitly.
5. Do not touch the live-draft path. Full regression suite — expect no
   change beyond the 3 known pre-existing failures.
6. Standard closing verification: grep + git status/diff confirm both
   real leagues' state untouched (read-only roster reads only).

**Deliverables:** the my-roster-id resolution mechanism and where it's
cached; whether Chunk 55's lineup endpoint was updated to use it; the
roster browser; the trade comparison UI and its explicitly-simple
valuation method; synthetic-data test results with the caveat stated;
full regression suite; git/grep confirmation.

---

## Chunk 56 — CLOSED, 2026-08-26, committed `feb3fa0`

**Task 1 — my-roster-id infrastructure:** `roster_identity.py` resolves
`MY_SLEEPER_USER_ID` against `owner_id` per league, cached in-memory.
**Confirmed live against both real leagues: roster_id=7 in Kiddos,
roster_id=8 in Former Bradley Bums.** This is now the one shared place
"which roster is mine" gets resolved for future chunks.

**Task 2 — lineup.py update:** `roster_id` now optional for
`use_live_roster=true`, auto-resolving "mine" via the new infrastructure.
The one Chunk 55 test whose behavior this superseded was updated
accordingly, not left stale.

**Task 3 — roster browser:** `GET /api/rosters` (mine + all 9 opponents',
`is_mine` flagged), validated against a monkeypatched synthetic 10-team
league built from all 10 slots of Chunk 41's existing picklog, and
confirmed live against both real leagues (graceful empty pre-draft
rosters).

**Task 4 — Trade Suggester skeleton:** `POST /api/trade/compare` — plain
sum of raw VBD/projected_points per side, explicitly not
Shapley/portfolio/season-simulation. **Good test design detail:**
verified via a schema-exact check rather than a naive substring check —
a substring check for "shapley" would have false-flagged on the
response's own disclaimer text. New "Trade" tab verified end-to-end
in-browser for both leagues.

**Synthetic-data caveat:** stated explicitly — both leagues remain
pre-draft, genuine validation against real, populated opponent rosters
waits until after an actual draft.

**Live-draft path:** untouched, `main.py`'s diff purely additive,
re-verified with an actual mock draft run.

**Regression suite:** 83 passed, 2 skipped, 4 xfailed, 3 failed — same 3
pre-existing picks (39/82/102), byte-identical wrong names to Chunk 55's
already git-stash-verified data-drift run — no fresh stash needed since
the failure signature matches exactly. **Runtime note, flagged for
visibility only:** this run took ~1h50m vs. the usual ~27m — no effect
on correctness, worth a look in a future housekeeping pass if the trend
continues, not chased now.

**Housekeeping:** zero references to either real draft_id outside
`leagues.py`'s registry, `git status` clean. Commit `feb3fa0`.

---

## Chunk 57 — SENT to Claude Code, 2026-08-26, report pending

**Goal:** Waiver/Free Agency Suggester skeleton — UI/structure only, a
simple raw-value ranking of available free agents, explicitly not
roster-need-aware modeling yet.

**Scope sent:**
1. Available free agents: cross-reference the full player pool against
   every roster in the league (reusing existing roster-read
   infrastructure) — whatever's unrostered is available. **Expected,
   worth stating explicitly in the report:** since both leagues are
   pre-draft, essentially the entire player pool will show as "available"
   right now — this is correct, not a bug, same pattern as the empty-roster
   caveat from Chunks 55-56, just a different manifestation of it.
2. Simple raw-value ranking: sort available free agents by raw VBD or
   projected points (reuse existing computation directly) — explicitly
   NOT roster-need-aware suggestions ("you need a WR" style logic). That
   real modeling work comes later; this chunk is a ranked list, not a
   recommendation engine.
3. Reuse Chunk 56's "my roster" infrastructure (`roster_identity.py`)
   directly rather than re-deriving it.
4. Optional, only if cheap: show "my current roster counts by position"
   alongside the free agent list as context, letting Vincent manually
   judge need rather than the system inferring it. Skip if it adds real
   complexity — this is a nice-to-have, not a requirement.
5. Surface injury_status if easily available (already added to
   projections.py in Chunk 55) — reuse, don't rebuild.
6. New tab in the nav shell, both leagues via the existing switcher,
   matching the established visual identity.
7. Do not touch the live-draft path. Full regression suite — expect no
   change beyond the 3 known pre-existing failures.
8. Standard closing verification: grep + git status/diff confirm both
   real leagues' state untouched throughout — read-only only.

**Deliverables:** the free-agent availability logic and confirmation of
the expected pre-draft "everything available" state; the ranking method
and confirmation it's simple raw-value, not needs-aware; confirmation
Chunk 56's roster-identity infrastructure was reused directly; whether
the optional roster-context display was included; full regression suite;
git/grep confirmation.

---

## Chunk 57 — CLOSED, 2026-08-26, committed `2f1167c`

**Task 1 — availability:** `waivers.py`'s `/api/waivers/available`
cross-references the full player pool against every roster, reusing
Chunk 56's `roster_identity.get_rosters_with_mine_flag` directly.

**Task 2 — pre-draft state:** confirmed explicitly for both real
leagues — 990/990 players available, `total_rostered_players: 0`,
handled gracefully with a clear UI note, not treated as a bug.

**Task 3 — ranking:** confirmed byte-identical to `calculate_vbd()`
called directly, with a dedicated schema-exact test proving no
need-scoring or roster-fit fields exist anywhere in the response —
matching the same rigor as Chunk 56's trade-comparison schema test.

**Task 4 — roster_identity reuse:** confirmed via a smart test design —
pre-warms the shared cache with a known synthetic value and checks the
endpoint returns that *exact* value, proving it routes through the
shared resolver rather than an independently-reimplemented but
behaviorally-similar match. Real proof of reuse, not just equivalent
behavior.

**Task 5 (optional roster context):** included since genuinely cheap;
passive-only, doesn't touch ranking.

**Task 6 (injury_status):** reused directly from Chunk 55.

**Real finding along the way, properly root-caused:** a stale on-disk
projections cache (predating Chunk 55's `injury_status` field, still
within its 24h TTL) caused one transient test failure — confirmed via
`force_refresh` this was cache staleness, not a code bug. Correctly
scoped out of redesigning cache invalidation itself.

**Frontend:** new "Free Agents" tab, verified end-to-end for both
leagues; **caught and fixed a class-naming collision** with Draft
Outlook's existing filter buttons before it became a live bug, not after.

**Live-draft path:** untouched, re-verified with an actual mock draft
run.

**Regression suite:** 91 passed, 2 skipped, 4 xfailed, 3 failed — same 3
pre-existing failures, no new ones, no recurrence of the stale-cache
issue (already resolved before this run). Runtime ~44 min — down from
Chunk 56's ~1h50m but still above the original ~27m baseline; continuing
to note for visibility, not investigating yet.

**Housekeeping:** zero references to either real draft_id outside
`leagues.py`'s registry, `git status` clean. Commit `2f1167c`.

---

## Chunk 58 — SENT to Claude Code, 2026-08-26, report pending

**Scope simplification from the original rough draft, explained:** the
original plan named "standings/best-team/best-draft leaderboards"
separately, but most of that isn't actually meaningful yet — no games
have been played in either league, no draft has happened. Faking
standings or "who's projected to win" against nonexistent season data
would break the honesty-in-labeling discipline this arc has held
throughout (VBD APPROXIMATION, the trade `method_note`, etc.).
**Consolidating "best team / best draft / standings" into one Power
Rankings view** that reuses `evaluate_roster` (already exists, already
validated since Chunk 5) across all 10 rosters in a league — genuinely
meaningful the moment a draft completes, and stays meaningful as the
season progresses, rather than three separate features where two would
be fake placeholders right now.

**Scope sent:**
1. Real transactions feed: display Sleeper's transaction data directly
   (no modeling) for a league. Expected to be sparse/empty right now
   given pre-draft status — state this explicitly, same pattern as
   prior chunks' pre-draft caveats, don't treat sparse real data as a
   bug.
2. Power Rankings view: run `evaluate_roster` across all 10 rosters in a
   league, rank them, highlight "my" roster using Chunk 56's `is_mine`
   flag. Pre-draft, this will correctly show all rosters near-zero/tied
   — that's correct, not broken, since no one has drafted anything yet.
3. Explicitly OUT of scope: real win/loss standings (requires actual
   game results, which don't exist for a long time yet) — do not build a
   placeholder that could be mistaken for real data. If you want to show
   something here, an honest "not available until games are played" note
   is fine; a fake or synthetic-looking number is not.
4. Given real data is sparse right now, optionally add a clearly-labeled
   "DEMO" mode/view using one of the existing completed mock-draft
   artifacts (already on disk from the replay harness work) so Vincent
   can see what Power Rankings will look like once a real draft
   completes — must be unmistakably labeled as demo/synthetic data, not
   blended with the real-league view.
5. Both leagues via the existing switcher. New "League Dashboard" (or
   similar) tab, matching the established visual identity — this is
   explicitly a good spot for genuine visual/design creativity per the
   project's original "fun, gamified" goal, within the time available.
6. Do not touch the live-draft path. Full regression suite — expect no
   change beyond the 3 known pre-existing failures.
7. Standard closing verification: grep + git status/diff confirm both
   real leagues' state untouched throughout — read-only only.

**Deliverables:** the transactions feed and confirmation of expected
sparse pre-draft state; the Power Rankings view and its direct reuse of
`evaluate_roster`; confirmation real standings were NOT faked; whether a
demo mode was included and how clearly it's labeled; full regression
suite; git/grep confirmation.

---

## Update log

*(append one dated entry per run/report — most recent at the bottom)*

- **2026-08-26:** V5 doc started, continuing from V4 (Chunks 31-40, closed
  there — V4 retained in project knowledge as historical record). Chunk 40
  there — V4 retained in project knowledge as historical record). Chunk 40
  (fixed-trajectory replay harness) closed and committed `96fd420` — full
  writeup carried forward into this doc's "State carried into V5" section
  above. New standing practices adopted from its findings: (1) snapshot-
  and-name decision points immediately, not retroactively; (2) the harness
  is now proven deterministic and worktree-comparison-clean, so future
  before/after claims can lean on it directly. Chunk 41 scoped and sent:
  proper harness-based diagnosis of the WR/QB imbalance across multiple
  fresh, immediately-snapshotted decision points, distinguishing
  allocation-level from rollout-level causes, plus an explicit Track B
  overlap check. Report pending.
- **2026-08-26 (later):** Chunk 41 report received, closed, committed
  `0250519`. Task 0 repin done carefully (caught a second drifted field
  the suite hadn't surfaced on its own). 6 decision points instrumented
  with clean before/after evidence each. Result: a genuine mix, not one
  mechanism — allocation-level effects are net positive for WR now
  (2 points fixed cleanly, 1 point a benign second-order RB-competition
  effect), but a real, quantitative, rollout-level countervailing effect
  showed up at 2 points (VBD moves correctly, `mcts_score` moves the
  opposite direction) — the clearest Chunk 42 target, not yet traced to a
  specific line. Track B overlap: 0/6, reinforcing Chunk 34's "real but
  rare" finding. Bonus find: a distinct, unrelated ADP-margin tiebreak bug
  (signed rather than absolute-value margin, mishandles extremely-overdue
  candidates) — real, deliberately deferred, not conflated with this
  thread. Chunk 42 scoped as diagnostic-only (widen evidence, trace to a
  specific mechanism, determine bug-vs-emergent-tradeoff) — explicitly not
  combined with a fix, given this thread's history of premature-fix
  lessons. Sent, report pending.
- **2026-08-26 (later still):** Chunk 42 report received, closed,
  diagnostic-only, no commit. Root cause traced to a precise
  function/line by direct elimination: the discount/starter/percentile
  pathway (Chunk 41's standing hypothesis) proven byte-identical between
  refs and ruled out entirely; the real cause is
  `opponent_model.build_adp_proxy_ranks` silently depending on
  `calculate_vbd`'s ordering, which Chunk 38 deliberately changed from
  raw-points to percentile-within-position — a coupling nobody re-audited
  when Chunk 38 shipped. Same bug shape as Chunk 26/39. Confirmed systemic
  (5/5 points, spans a QB pair too, not TE-only) and confirmed a genuine
  bug rather than an emergent tradeoff (the roster-valuation pathway is
  proven identical; only opponent-modeled survival odds differ). One gap
  honestly flagged: the causal link is the strongest explanation by
  elimination but not yet quantitatively confirmed via enough Monte Carlo
  replicates. Chunk 43 scoped as a gated chunk — quantify first, only
  build the fix (decoupling the proxy-rank basis from VBD's now-percentile
  ordering) if quantification confirms; broad validation required given
  this touches opponent modeling for every rollout, not just these 5
  points. Sent, report pending.
- **2026-08-26 (later still x2):** Chunk 43 report received. Gate failed
  at Step 1 — 500-replicate survival checks showed the opponent-model
  proxy-rank coupling has zero measurable effect on these specific
  candidates' survival odds between refs (all differences within Monte
  Carlo noise), because McBride/Nacua/Jefferson all have real market ADP
  and aren't governed by the proxy-rank fallback that was found to churn.
  Correctly stopped rather than proceeding to build a fix on an
  unconfirmed premise — Steps 2-4 (fix, hardening, validation) not
  performed, as designed. Two mechanisms now eliminated by direct
  measurement (discount/starter/percentile pathway in Ch. 42; opponent-model
  proxy-rank coupling in Ch. 43) with zero confirmed candidate mechanisms
  remaining. Important distinction preserved: this closes one specific
  mechanistic lead, not the underlying aggregate WR/QB imbalance, which
  remains separately established via the multi-seed regression sweep.
  Chunk 44 scoped to test the more fundamental, cheaper question first —
  is the original sign-flip claim (based on single-run comparisons)
  statistically distinguishable from ordinary seed-to-seed noise at all —
  before chasing a third specific mechanism (UCB1 visit-count allocation),
  with RNG-stream-divergence as a further fallback check. Explicitly
  gated: if all 5 points wash out as noise, that's a valid, complete
  closure of this thread, not a failed chunk. Sent, report pending.
- **2026-08-26 (later still x3):** Chunk 44 report received. Gate failed
  at Step 1 — 15-seed replication showed 3/5 points are unambiguous noise
  (including Chunk 42's own headline example), and the remaining 2/5 are
  only nominally significant before correction, failing Bonferroni once
  the 5-comparison multiplicity is accounted for. Correctly concluded: no
  point survives as a defensible finding. Third consecutive elimination on
  this thread (value pathway, opponent-model coupling, now the "is it even
  real" check itself). Steps 2-3 correctly skipped since nothing cleared
  the gate. Real side-finding, not chased: recommend()'s internal stderr
  underestimates true between-seed variance by up to 3.4x — logged as a
  new standing open item (other confident-gap calls elsewhere in the
  system may be more overconfident than believed), not yet acted on.
  Claude Code's own recommendation, adopted: stop single-point
  mechanism-hunting, pivot to population-level structural analysis in the
  style of Chunk 36 — the one approach in this whole arc that's actually
  found something durable. Chunk 45 scoped accordingly: rebuild Chunk 36's
  rank-for-rank table under current data/code plus a parallel
  percentile-based version, run an aggregate (not single-point) wait-value
  audit across all existing pick logs for real statistical power, and test
  directly whether percentile-within-position comparison actually
  neutralized the original cross-position scarcity gap or just moved it.
  Diagnostic only, no fix. Sent, report pending.
- **2026-08-26 (later still x4):** Chunk 45 report received — the best
  diagnostic result this arc has produced. Found the opposite of the
  working hypothesis: percentile-within-position overcorrects PAST WR's
  favor (QB's smaller scored pool means the same rank consumes a bigger
  percentile fraction), and now empirically favors WR in 65% of
  passed-over instances. But it doesn't matter, because percentile is a
  one-time, discarded classification signal (decides starter/bench/flex-rank
  only) — the actual value-maximization layer (raw points → VBD →
  bench/flex discounts → evaluate_roster) runs on a completely different,
  untouched currency, and that layer still favors non-WR positions in 79%
  of instances, reflecting a genuine SUPERFLEX scoring-format effect
  (Chunk 36's original finding, confirmed still fully intact). Precise
  conclusion: a two-layer architecture mismatch — starter-allocation
  fairness (fixed, Chunk 38) and value-maximization (unchanged since
  Chunk 1) are two different questions running on two different
  currencies, and MCTS's final pick is governed by the second one. This
  retroactively explains why Chunks 41-44's single-point mechanism hunts
  all came up empty — they were investigating the wrong layer. Track B
  reconfirmed essentially-never at a much larger sample (0/8 qualifying
  at N=75 vs. Chunk 34's N=65). Planning-chat flagged a strategic fork
  before scoping further: is "WR shortage vs. league median" actually a
  bug, given the project's own founding vision explicitly wants
  "analytical edge... because it's built on the league's actual scoring
  rules" — deviation from human-drafted norms isn't automatically wrong.
  Decided (not asked, per established preference for this chat to decide
  and act on modeling/sequencing calls): before any invasive fix to the
  core value layer, test with the project's own original outcome-based
  validation methodology (Chunk 9's evaluate_roster comparison) whether
  the "imbalance" actually costs value or is legitimate edge. Chunk 46
  scoped accordingly — reuses existing artifacts, no production code
  touched, purely a counterfactual-roster-construction comparison. Sent,
  report pending.
- **2026-08-26 (later still x5):** Chunk 46 report received, closed, no
  commit. Resolved the strategic fork decisively: a positionally-balanced
  counterfactual roster (built by holding real opponent picks fixed and
  applying a simple quota-constrained greedy strategy) beat the system's
  actual historical roster in 5/5 seeds using evaluate_roster unchanged —
  mean −43.1 points, up to −135.5 in one seed, zero seeds favoring the
  actual roster. The imbalance is real lost value, not legitimate edge.
  Planning-chat override on the proposed fix direction: Claude Code
  suggested making the value layer "percentile-aware," but Chunk 45's own
  Task 1 showed percentile overcorrects in the wrong direction for this
  exact purpose (QB percentile 82.3 vs WR's 94.4 at rank 24) — swapping to
  percentile risks trading today's bug for its mirror image, the same
  overcorrection shape that already bit Chunks 20 and 33. Redirected the
  fix target to VBD instead — already computed, already SUPERFLEX-demand-aware
  (built specifically for this in Chunk 2), not shown to have the
  overcorrection problem. Chunk 47 scoped as gated: cheap test first
  (re-sweep BENCH_DISCOUNT_BASE/DECAY["WR"] under current post-Chunk-38
  code, since Chunk 35's null result on this exact sweep predates the
  Chunk 38 fix and may no longer hold), using both the standard
  positional-balance metric AND Chunk 46's evaluate_roster methodology as
  joint success criteria; only if that fails does it proceed to the larger
  VBD-currency architectural fix to portfolio.py's discount logic. Sent,
  report pending.
- **2026-08-26 (later still x6):** Chunk 47 report received, closed, no
  commit. Step 1 gate failed cleanly (WR deviation exactly −2.0 at every
  sweep value, replicating Chunk 35's null result post-Chunk-38 too; RB
  overcorrection appeared immediately on tightening). Step 2B (VBD-currency
  fix) built and validated twice — attempt 1 had an arithmetic error
  (added replacement level back in regardless of discount, inflating bench
  QB value), attempt 2 corrected the algebra and was hand-verified
  correct, but made the value gap worse again (−43.1→−106.7). Root cause,
  the real finding of the chunk: both formulas replace Chunk 10's
  calibrated decay-to-zero bench discount with decay-to-a-large-floor,
  undoing the QB/TE-glut fixes — and more fundamentally, Chunk 45's own
  data already showed 85% of WR-passed-over instances are starter-vs-starter
  comparisons where the discount is a mathematical no-op by construction.
  The entire bench/flex-concentration-discount fix family is now closed
  out as a dead end with two independent decisive negative results.
  Cleanly reverted, confirmed via git diff and matching regression
  baseline. Planning-chat reframing: since Chunk 46 already showed
  unmodified evaluate_roster prefers balanced rosters, the bias is likely
  in what MCTS's search explores (rollout continuation policy,
  _roster_aware_pick) rather than how a final roster gets scored. Chunk 48
  scoped to test this cheaply first, reusing Chunk 25's exact
  precedent (forced high iteration budget) before touching rollout-policy
  internals — still diagnostic only. Explicit checkpoint named: 9+ chunks
  deep on this thread with two reverted fixes; if Chunk 48 doesn't produce
  a clean low-risk fix path, recommend documenting as a known limitation
  and redirecting to Track B / the ADP-tiebreak bug instead. Sent, report
  pending.
- **2026-08-26 (later still x7):** Chunk 48 report received, closed. The
  strongest result this thread has produced. Iteration-budget test was
  ambiguous (1/3 points resolved, 1/3 unchanged, 1/3 widened) — correctly
  triggered deeper instrumentation rather than being over-interpreted.
  Direct policy instrumentation (3 synthetic roster states, zero MCTS,
  zero randomness) found a clean, deterministic, exactly-located root
  cause: _roster_aware_marginal_value's starter branch (mcts.py:486-489)
  returns raw undiscounted points for any would-start candidate with zero
  roster-composition awareness — confirmed byte-identical output for a
  QB candidate regardless of whether the roster is balanced or already
  WR-heavy. Identical gap confirmed in evaluate_roster's counterpart.
  Important structural clarification: this can't be fixed by extending
  Chunk 20's TE mechanism to QB, since SUPER_FLEX's single-slot count
  means a 2nd QB structurally never reaches flex_rank≥2 — the gap is an
  uncosted cross-position comparison at shared-slot-fill time, not
  same-position crowding, a genuinely new mechanism to build. Claude
  Code's honest calibration: real but not high confidence of a validated
  fix landing in one chunk, given the novelty of the mechanism and the
  Chunk 47 precedent of needing two attempts before failing. Chunk 49
  scoped as the one well-considered attempt before the checkpoint: a
  specific design given upfront (VBD-based valuation for shared-slot
  candidates only, dedicated slots untouched), an explicit guardrail
  against reaching for Shapley (would violate the Chunk 8 no-blending
  principle and blow the latency budget), a cheap synthetic gate reusing
  Chunk 48's exact Task 3 methodology before any expensive full-pipeline
  validation, and an explicit instruction to stop and report honestly
  rather than attempt a third design within the same chunk if it doesn't
  converge. Sent, report pending.
- **2026-08-26 (later still x8):** Chunk 49 report received, closed —
  gated out at Step 1, exactly as designed, reverted cleanly. Both
  synthetic checks failed for real, distinct, well-understood reasons:
  check (a) failed by mathematical necessity (replacement level is a
  league-wide quantity, structurally can't depend on the roster's own
  position mix); check (b) failed because the fix cut QB's shared-slot
  value while leaving RB/WR's dedicated-slot value untouched, letting a
  merely-comparable RB beat a genuinely-needed QB — the exact failure
  mode Chunk 38 had guarded against for its own fix. Two real methodology
  bugs found and fixed along the way before reaching this conclusion
  (starter-slot displacement in the test harness, and QB/WR replacement
  levels collapsing within 2-3 rounds requiring an earlier test depth) —
  thorough, honest work even in a chunk that ended in a revert. Claude
  Code's direct recommendation: three reverted attempts (Ch. 47 ×2, Ch.
  49) is decisive evidence, not insufficient effort — stop pursuing
  value-layer fixes for this draft cycle and document as a known
  limitation. **Planning-chat decision: accepted.** Closed the WR/QB
  thread (Chunks 38-49, 12 chunks total) as an accepted, documented
  limitation. Added a "Known limitations" living section to this doc
  (WR/QB imbalance closed/accepted; Track B and the ADP-tiebreak bug still
  open; opponent_model.py performance and the launch.json bug carried
  forward). Laid out a Chunks 50-59 roadmap for the draft-day readiness
  push, reordered by priority given ~10 days remain per Claude Code's own
  framing: quick wins first (ADP-tiebreak fix), then Track B
  diagnose/fix, then a full regression+latency re-check, then a live
  practice-draft checkpoint, then operational-readiness hardening, then
  final open-items triage, then a draft-day runbook, then a final dress
  rehearsal. Chunk 50 scoped and sent: in-repo KNOWN_LIMITATIONS.md +
  the small, well-scoped ADP-margin tiebreak fix, as a deliberate change
  of pace after 12 chunks on one hard thread. Sent, report pending.
- **2026-08-26 (later still x9):** Vincent joined a second Sleeper
  league (drafts ~3 days after Kiddos) and requested a deliberate pivot:
  pause the correctness/modeling track (the Chunks 51-59 draft-day-readiness
  roadmap — Track B, latency re-check, live checkpoint, operational
  hardening, runbook, dress rehearsal — deferred, not cancelled) in favor
  of multi-league support and league-long "Phase 2" skeleton work (trade
  suggester, waiver suggester, start/bench optimizer, league dashboard),
  explicitly UI/structure only, not the modeling behind those features
  yet. Useful new context: Vincent can do roughly 10 chunks/day, which
  meaningfully changes prior time-pressure assumptions. Flagged a
  critical open risk before committing to any plan: multi-league is only
  "just interface" if league 2's format resembles Kiddos' (SUPERFLEX, TE
  premium) — if it doesn't, most of the calibration work done so far
  (Chunks 9/10/20/33, the whole VBD engine) is Kiddos-specific and
  wouldn't transfer without real recalibration, which there's no time for
  before league 2's draft. Added a new "Arc: Multi-League Expansion +
  League-Long Skeleton" section with a rough 9-chunk plan (51-59,
  expected to shift after 51's findings), and an explicit architectural
  principle to keep the new skeleton pages additive so Kiddos' draft-day
  reliability isn't put at risk. Chunk 51 scoped and sent: pure
  settings-discovery and a transfer-vs-recalibrate verdict for league 2,
  no code changes — the gate before any architecture work begins. Sent,
  report pending.
- **2026-08-26 (later still x10):** Chunk 51 report received, closed,
  read-only, no code changes. League 2 identified cleanly ("Former
  Bradley Bums") with zero ambiguity. Verdict: (a) TRANSFERS AS-IS —
  every dimension the engine depends on (scoring, TE premium, SUPERFLEX
  roster shape, league size) is identical to Kiddos, confirmed
  field-for-field via the live API, with real corroborating evidence
  (a `copy_from_league_id` suggesting league 2 was templated from a
  SUPERFLEX/TE-premium league). Significant de-risking — Chunk 52 is a
  config/interface problem, not a modeling one. **Critical discrepancy
  flagged and NOT resolved:** Chunk 51 reports Kiddos' draft date as
  2026-09-06, 7pm Pacific, a full day earlier than every prior reference
  in this project (2026-09-07, since Chunk 31) — likely a UTC-vs-local-time
  mixup. Flagged to Vincent for direct confirmation via the Sleeper app
  rather than picking either date; added explicit unresolved-discrepancy
  notes to the standing constraint and Quick Reference sections rather
  than silently updating either value. Also relayed Claude Code's request
  to confirm league 2's keeper status (evidence points to none, matching
  Kiddos' pattern, not yet asserted). Chunk 52 scoped and sent: multi-league
  backend config architecture, with a mandatory negative control —
  Kiddos' Draft Score output must be byte-identical before/after the
  refactor. Sent, report pending.
- **2026-08-26 (later still x11):** Vincent confirmed Kiddos' real draft
  date/time directly via the Sleeper app: **2026-09-06 (Sunday), 9:00
  PM** — resolving the discrepancy flagged in Chunk 51. Both prior
  estimates (2026-09-07 from Chunk 31, 7pm Pacific from Chunk 51) were
  imprecise; this confirmed value is now the source of truth, updated in
  the Standing Constraint and Quick Reference sections. Vincent noted
  this doesn't affect his ability to draft either way — informational
  correction only. No impact on Chunk 52, already in progress
  (Vincent sending it to Claude Code now). League 2's keeper-status
  confirmation still outstanding.
- **2026-08-26 (later still x12):** Chunk 52 report received, closed,
  committed 4b347d3. Clean refactor — every hardcoded value traced to a
  single file (config.py), a new LeagueConfig registry (leagues.py)
  derives the existing constants so zero consumer files needed changes,
  and calibration constants correctly stayed global (Chunk 51's
  same-format finding reasoned through properly, not just followed
  blindly). Negative control passed: byte-identical Kiddos recommend()
  output pre/post refactor, SHA256-confirmed. 3 regression failures
  found and properly root-caused via the git-stash technique rather than
  dismissed — confirmed as pre-existing live-data drift (same phenomenon
  Chunks 39/41 already characterized), not caused by this chunk; correctly
  left un-repinned as out of scope, flagged for later housekeeping. Chunk
  53 scoped with a refinement to the original rough draft: since Kiddos
  (09-06) and league 2 (09-08) never draft concurrently, true concurrent
  live-draft support isn't actually needed — only planning/browsing
  routes need per-request league-switching, the live in-draft path can
  stay on a single active-league config. Sent with an explicit negative
  control requirement that the live-draft path remain untouched. Sent,
  report pending.
- **2026-08-26 (later still x13):** Chunk 53 report received, closed,
  committed be5e79a. Clean scope discipline — live-draft path untouched
  and verified via a real end-to-end mock draft negative control;
  /api/league-check correctly identified as out of scope rather than
  silently handled either way; the 3 regression failures reasoned as
  structurally impossible to have been caused by this chunk (direct
  code-path argument, stronger than a git-stash comparison). Important
  honest finding: vbd.py/projections.py still consume global config, not
  the per-request resolved league — computation isn't fully wired
  end-to-end yet, only routing/dispatch is. Fenced with a verified 409
  guard rather than left as a silent risk; doesn't affect either real
  league today since both are confirmed identical format. Logged as a
  new "Known limitations (addendum): architecture" entry. Chunk 54
  scoped: build the Draft Outlook view Vincent described (browsable
  pre-draft rankings, target-marking with persistence, a pick-N
  survival-likelihood view reusing existing ADP machinery rather than
  building new), starting with an audit of what the existing Rankings tab
  already covers rather than rebuilding from scratch. Sent, report
  pending.
- **2026-08-26 (later still x14):** Chunk 54 report received, closed,
  committed b7668c2. Existing Rankings tab correctly audited as pure VBD
  and honestly relabeled "approximation" rather than left ambiguous. Real
  Draft Score wired in via a new outlook endpoint reusing
  mcts_service.recommend() directly. Two real bugs found and fixed during
  the chunk, not just during a final check: a my_slot-turn-order edge
  case for non-slot-1 outlook views (fixed transparently, surfacing the
  simulated-pick count rather than hiding the assumption), and a
  stale-response race condition between league switches caught during
  live browser testing (fixed with a captured-at-fetch-start league_key
  guard). Target persistence deliberately git-tracked as irreplaceable
  user input. Pick-N survival correctly reused existing ADP/opponent-model
  machinery rather than new modeling. Regression suite unchanged from
  baseline plus 12 new passing tests. Chunk 55 scoped: Start/Bench Lineup
  Optimizer, expected to be a cheap win since _allocate_starters already
  exists — but flagged clearly that neither league has a real roster yet
  (both pre_draft), so this chunk validates against synthetic mock-draft
  data with real-roster validation explicitly deferred until after an
  actual draft happens. Sent, report pending.
- **2026-08-26 (later still x15):** Chunk 55 report received, closed,
  committed 38f9bff. Optimizer endpoint correctly reuses
  _allocate_starters, cross-checked byte-identical. Two real bugs found
  and fixed: an empty-list-vs-omitted-field validation bug directly
  relevant to the pre-draft empty-roster case, and injury_status
  correctly surfaced as a separate field rather than folded into the
  point estimate (good discipline holding the no-weighted-averages
  principle even for a small, tempting shortcut). Bye-week correctly
  flagged out of scope rather than guessed at. Regression suite clean
  (3 pre-existing failures only, root-caused via git-stash yet again).
  Important infrastructure gap surfaced: the codebase has never tracked
  "my roster" per league, worked around with an explicit roster_id
  parameter for now. Flagged as a cross-cutting need for Chunks 56-58
  (Trade Suggester, Waiver Suggester, League Dashboard all need this).
  Chunk 56 scoped to resolve this as shared infrastructure first (match
  roster owner_id against the known Sleeper user_id), then build the
  Trade Suggester skeleton on top of it — explicit manual trade
  exploration with simple raw-value comparison, not proactive
  suggestions or real Shapley-based modeling yet. Sent, report pending.
- **2026-08-26 (later still x16):** Chunk 56 report received, closed,
  committed feb3fa0. My-roster-id infrastructure confirmed live against
  both real leagues (roster_id 7 and 8 respectively) — clean, reusable
  shared infrastructure now exists for future chunks. Lineup endpoint
  correctly updated to use it rather than left with the old required
  parameter. Roster browser validated against a proper synthetic 10-team
  league, not just an isolated single-roster case. Trade Suggester
  skeleton correctly stayed simple (raw-value sum only), verified via a
  smart schema-exact test rather than a substring check that would have
  false-flagged its own disclaimer text. Regression suite clean (same 3
  pre-existing failures). One non-urgent watch-item: this run's runtime
  jumped to ~1h50m from the usual ~27m — flagged for visibility, no
  correctness impact, not chased now. Chunk 57 scoped: Waiver/Free Agency
  Suggester skeleton, simple raw-value ranking of available free agents
  reusing Chunk 56's roster-identity infrastructure directly, explicitly
  not roster-need-aware modeling yet — with the expected pre-draft
  "everything is available" state noted upfront as correct behavior, not
  a bug to chase. Sent, report pending.
- **2026-08-26 (later still x17):** Chunk 57 report received, closed,
  committed 2f1167c. Availability logic and ranking correctly reused
  existing infrastructure (roster_identity, calculate_vbd) with strong
  proof-of-reuse tests, not just behaviorally-similar reimplementations —
  notably a cache-prewarming test proving the shared resolver is actually
  consulted. Pre-draft "everything available" state confirmed and
  handled gracefully for both real leagues. Real stale-cache finding
  properly root-caused (predated Chunk 55's injury_status field, within
  TTL) rather than dismissed as flaky. Caught a frontend class-naming
  collision proactively during testing. Regression suite clean, runtime
  still elevated (~44m) but improved from Chunk 56's ~1h50m, continuing
  to just note it. Chunk 58 scoped with a deliberate simplification: the
  original "standings/best-team/best-draft" framing got consolidated
  into one Power Rankings view reusing evaluate_roster across all 10
  rosters, since faking standings or win-probability data against a
  season that hasn't started would break this arc's established honesty-in-labeling
  discipline. Real transactions feed (genuinely real, just sparse
  pre-draft) plus an optional clearly-labeled demo mode using existing
  mock-draft artifacts to preview the feature. Sent, report pending.
