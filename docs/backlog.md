# Backlog

Not acted on yet — logged here so it isn't lost, per this project's
practice of documenting known gaps rather than letting them go
undiscovered again.

## `opponent_model.py` performance (logged Chunk 15)

Chunk 14's profiling found `app/services/opponent_model.py`
(`pick_probabilities` / its inner listcomp, called via
`mcts._advance_opponents`) accounts for **~60% of total per-pick MCTS
compute time** — a cost that predates and is independent of anything
Chunk 13 or 15 touched. It was already this expensive before Chunk 13's
fix; Chunk 13's `_roster_aware_pick` only added a further ~37% on top of
that pre-existing baseline (see Chunk 14's A/B: 6.48s pre-Chunk-13 →
8.90s with the fix, at an identical mid-draft state).

Worth a dedicated optimization pass **before** MCTS iteration count or
Monte Carlo depth ever increases (any such increase would multiply this
existing cost proportionally). Likely angles, not investigated yet:
- Caching/memoizing `pick_probabilities`' per-position weighting instead
  of recomputing it fresh on every one of `_advance_opponents`' ~2000+
  calls per `recommend()` call.
- Reducing redundant `calculate_vbd` recomputation across nearby
  opponent-advancement steps within the same rollout.

Out of scope for Chunk 15 (a verification/test-suite chunk, not a
rebuild) — flagged here for a future chunk.
