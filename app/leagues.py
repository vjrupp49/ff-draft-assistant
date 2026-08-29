"""
Per-league configuration model (Chunk 52).

CONTEXT: this project started as a single hardcoded league ("Kiddos",
app/config.py's original docstring: "no multi-tenant config... If the
league ever changes leagues/seasons, update this file directly"). Chunk 51
confirmed a second real Sleeper league ("Former Bradley Bums") the user
also drafts in, and found -- via the live API, field-for-field, not
assumed -- that it shares Kiddos' exact scoring format (full PPR, TE
premium +0.5/rec), roster shape (QB/2RB/2WR/3FLEX/SUPER_FLEX/6BN), and
league size (10 teams). Snake draft, both. Only the league-identifying
IDs and scheduling fields (draft date, pick timer) actually differ.

This module holds ONE `LeagueConfig` per real league, and a single
`ACTIVE_LEAGUE` selector app/config.py derives its module-level constants
from. Every existing consumer of those constants (app/main.py,
app/services/draft_state.py, vbd.py, projections.py, mock_draft.py,
mcts.py, adp.py, app/routers/_shared.py, app/routers/live.py) keeps
importing the SAME names from app.config, completely unchanged -- this
refactor only changes WHERE config.py's values come from, never what any
consumer sees, and for Kiddos (the default ACTIVE_LEAGUE) the values are
byte-identical to what config.py hardcoded before this chunk (verified via
the replay harness's negative control -- see this chunk's report).

DELIBERATELY NOT TOUCHED BY THIS CHUNK: the project's calibrated tuning
constants -- portfolio.py's BENCH_DISCOUNT_BASE/DECAY and
FLEX_CONCENTRATION_DISCOUNT_BASE/DECAY, vbd.py's replacement-level/
percentile logic, mcts.py's search parameters. Those are modeling
assumptions validated against THIS scoring/roster FORMAT (Chunks 2, 9, 10,
13, 33, 38 and onward) -- since both leagues share that format, the
constants are correctly shared/global, not per-league fields, and Chunk 52
leaves them exactly where they already live.

NOT WIRED TO ANY REQUEST-TIME OR UI SELECTOR YET: `ACTIVE_LEAGUE_KEY`
below is a plain module constant, changed by hand to point the whole
backend at a different league. Runtime/UI switching is explicitly Chunk
53's scope, not this one's.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    league_id: str
    draft_id: str
    league_name: str
    num_teams: int
    draft_type: str  # "snake" or "auction" -- both real leagues are "snake" today
    pick_timer_seconds: int
    draft_date: str | None  # ISO date (YYYY-MM-DD), confirmed via the live Sleeper API (Chunk 51) -- None if unknown
    scoring: dict[str, float] = field(default_factory=dict)
    roster_positions: list[str] = field(default_factory=list)


# Shared by both leagues today -- Chunk 51 confirmed this field-for-field
# via the live Sleeper API for "Former Bradley Bums", not assumed from
# Kiddos alone. A future league with a genuinely different format would
# get its OWN scoring/roster_positions values here; nothing about this
# module requires them to be shared, they just happen to be identical for
# every real league this project has been used with so far.
_SUPERFLEX_TE_PREMIUM_SCORING: dict[str, float] = {
    "pass_yd": 0.04,       # 0.04 pts/passing yard (1 pt per 25 yards)
    "pass_td": 4.0,        # 4pt passing TD
    "pass_int": -2.0,      # -2 per interception
    "rush_yd": 0.1,        # 0.1 pts/rushing yard (1 pt per 10 yards)
    "rush_td": 6.0,
    "rec": 1.0,            # Full PPR: 1.0 pt per reception
    "rec_yd": 0.1,         # 0.1 pts/receiving yard (1 pt per 10 yards)
    "rec_td": 6.0,
    "te_premium_bonus": 0.5,  # additional +0.5/rec for TEs, on top of `rec`
}

# 1 QB + 2 RB + 2 WR dedicated, 3 FLEX (RB/WR/TE-eligible), 1 SUPER_FLEX
# (QB/RB/WR/TE-eligible), 6 BN -- 9 starters + 6 bench = 15 rounds.
_STANDARD_SUPERFLEX_ROSTER: list[str] = [
    "QB",
    "RB", "RB",
    "WR", "WR",
    "FLEX", "FLEX", "FLEX",
    "SUPER_FLEX",
    "BN", "BN", "BN", "BN", "BN", "BN",
]

KIDDOS = LeagueConfig(
    key="kiddos",
    league_id="1389755334746202112",
    draft_id="1389755334746202113",
    league_name="Kiddos",
    num_teams=10,
    draft_type="snake",
    pick_timer_seconds=60,  # confirmed via the live Sleeper API, Chunk 51
    draft_date="2026-09-06",  # 2026-09-06 21:00 Pacific -- CONFIRMED by Vincent directly in the Sleeper app (Chunk 51's "2026-09-07 / 7pm PT" was a UTC/estimate error; corrected Chunk 60)
    scoring=dict(_SUPERFLEX_TE_PREMIUM_SCORING),
    roster_positions=list(_STANDARD_SUPERFLEX_ROSTER),
)

FORMER_BRADLEY_BUMS = LeagueConfig(
    key="former_bradley_bums",
    league_id="1389749759891214336",
    draft_id="1389749759891214337",
    league_name="Former Bradley Bums",
    num_teams=10,
    draft_type="snake",
    pick_timer_seconds=90,  # confirmed via the live Sleeper API, Chunk 51 -- a REAL difference from Kiddos' 60s
    draft_date="2026-09-08",  # confirmed via the live Sleeper API, Chunk 51 (2026-09-08 18:00 Pacific / 2026-09-09 01:00 UTC)
    scoring=dict(_SUPERFLEX_TE_PREMIUM_SCORING),  # identical format, confirmed field-for-field, Chunk 51
    roster_positions=list(_STANDARD_SUPERFLEX_ROSTER),  # identical, confirmed via both league.roster_positions AND draft.settings.slots_*, Chunk 51
)

LEAGUES: dict[str, LeagueConfig] = {
    KIDDOS.key: KIDDOS,
    FORMER_BRADLEY_BUMS.key: FORMER_BRADLEY_BUMS,
}

# Which league app.config's module-level constants currently derive from.
# Defaults to Kiddos (the nearer, already-scheduled real draft) so nothing
# about today's behavior changes unless this is deliberately edited.
ACTIVE_LEAGUE_KEY = "kiddos"
ACTIVE_LEAGUE = LEAGUES[ACTIVE_LEAGUE_KEY]
