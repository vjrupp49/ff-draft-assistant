# Handoff docs

Chunk-by-chunk project history for the planning-chat / Claude-Code working
model this project uses (see [`V1_chunks_1-10.md`](V1_chunks_1-10.md) for
that model's description). Read in order; each doc assumes the ones before
it. **`V5` is the living document** — it's appended to after every chunk
report from Chunk 41 onward and is the one to check first for current state.

- [`V1_chunks_1-10.md`](V1_chunks_1-10.md) — analytical engine build:
  projections → VBD → Monte Carlo → MCTS → Markowitz risk-adjustment →
  Shapley → single Draft Score, validated end-to-end via mock draft.
- [`V2_chunks_11-22.md`](V2_chunks_11-22.md) — draft-day UI build, then a
  correctness-hardening arc (QB-shortage/TE-glut root cause, forward-looking
  ADP integration, opponent-model accuracy) triggered by live dry runs.
- [`V3_chunks_22-31.md`](V3_chunks_22-31.md) — closes out MCTS
  sequencing/tie-break correctness (adaptive tie resolution), then a data
  quality investigation (dead upstream stats source found and migrated,
  LA/LAR team-abbreviation bug).
- [`V4_chunks_31-.md`](V4_chunks_31-.md) — TE-glut fix, WR-shortage
  root-causing arc (a long diagnostic chase — allocation vs. rollout-level
  causes, several eliminated hypotheses), a wait-value/backfill bug (Track
  B, still open), a `mock_draft.py` harness bug that silently disabled
  tie-break logic for years (fixed), the `_allocate_starters`
  positional-scarcity fix and its self-inflicted Goff edge case (fixed).
  Closed at Chunk 40 (fixed-trajectory replay harness built) — superseded
  by V5.
- [`V5_chunks_41-.md`](V5_chunks_41-.md) — **living doc, current state.**
  Continues the WR/QB imbalance investigation to its structural conclusion
  (a two-layer currency mismatch between starter-allocation and
  value-maximization, Chunk 45), resolves the "is this a bug or legitimate
  edge" strategic fork via outcome-based validation (Chunk 46), two failed
  VBD-currency fix attempts cleanly reverted (Chunk 47), then a confirmed
  root cause with a scoped, gated fix attempt (Chunks 48-49). Discovers a
  second real Sleeper league and builds multi-league backend architecture
  (Chunks 51-53), then a run of planning/browsing feature chunks: Draft
  Outlook (54), Start/Bench Lineup Optimizer (55), shared "my roster"
  infrastructure + Trade Suggester skeleton (56), Waiver/Free Agency
  Suggester skeleton (57), League Dashboard — transactions + Power
  Rankings (58, committed `3ce7854`, **not yet reflected in this doc's own
  Update Log as of the V5 upload** — the next chat should treat Chunk 58
  as CLOSED and pick up at Chunk 59; see the handoff message template
  this README's constraints feed into).

## Standing constraints (apply to every chunk, not just one)

- **Never touch either real league draft.** Kiddos: Sleeper `draft_id`
  `1389755334746202113`, confirmed 2026-09-06 (Sunday) 9:00 PM. "Former
  Bradley Bums" (discovered Chunk 51): `draft_id` `1389749759891214337`,
  2026-09-08. All draft activity in every chunk is a mock/practice draft,
  synthetic data, or a frozen/historical replay — both real leagues' state
  stays read-only throughout, confirmed via grep + `git status`/`git diff`
  at the close of every chunk, for both draft_ids.
- **Root-cause before fixing; negative-control every fix** (revert and
  confirm the problem reappears). Never blind-repin a failing test.
- **When attributing a behavioral change to a code change**, `git stash`
  back to the previous chunk's exact committed code and re-run against
  today's live data first — live ADP/projection data drifts run-to-run,
  independent of any code change (discovered Chunk 39), and this is the
  only way to cleanly separate the two.
- One commit per chunk. Flag out-of-scope findings rather than silently
  expanding a chunk's work.
- **Since Chunk 53:** both real leagues are pre_draft — every real roster
  is empty and every league is transaction-free. This is correct, expected
  behavior for every planning/browsing feature built since (empty rosters,
  "everything available" free agency, all-tied Power Rankings, sparse
  transactions) — state it explicitly per chunk, don't treat it as a bug
  to fix or a gap to fill with synthetic-looking real data. Several chunks
  add a clearly-labeled DEMO mode (using existing mock-draft artifacts on
  disk) specifically so a feature is still checkable before a real draft
  happens, without ever blending demo data into the real view.
