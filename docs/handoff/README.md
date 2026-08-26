# Handoff docs

Chunk-by-chunk project history for the planning-chat / Claude-Code working
model this project uses (see [`V1_chunks_1-10.md`](V1_chunks_1-10.md) for
that model's description). Read in order; each doc assumes the ones before
it. **`V4` is the living document** — it's appended to after every chunk
report from Chunk 31 onward and is the one to check first for current state.

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
- [`V4_chunks_31-.md`](V4_chunks_31-.md) — **living doc, current state.**
  TE-glut fix, WR-shortage root-causing (still open), a wait-value/backfill
  bug (Track B, still open), a `mock_draft.py` harness bug that silently
  disabled tie-break logic for years (fixed), the `_allocate_starters`
  positional-scarcity fix and its self-inflicted Goff edge case (fixed).
  Ends with Chunk 40, scoped to build a fixed-trajectory replay harness.

## Standing constraints (apply to every chunk, not just one)

- **Never touch the real league draft.** Sleeper `draft_id`
  `1389755334746202113` is scheduled 2026-09-07. All draft activity in
  every chunk is a mock/practice draft (different `draft_id`) or a
  frozen/historical replay.
- **Root-cause before fixing; negative-control every fix** (revert and
  confirm the problem reappears). Never blind-repin a failing test.
- **When attributing a behavioral change to a code change**, `git stash`
  back to the previous chunk's exact committed code and re-run against
  today's live data first — live ADP/projection data drifts run-to-run,
  independent of any code change (discovered Chunk 39), and this is the
  only way to cleanly separate the two.
- One commit per chunk. Flag out-of-scope findings rather than silently
  expanding a chunk's work.
