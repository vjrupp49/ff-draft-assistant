"""
Hardcoded league settings for the "Kiddos" fantasy football league.

This is a personal, single-user, single-league tool — no multi-tenant config,
no env-var indirection for these values. If the league ever changes leagues/
seasons, update this file directly.
"""

# --- Sleeper identifiers ------------------------------------------------

SLEEPER_LEAGUE_ID = "1389755334746202112"
SLEEPER_DRAFT_ID = "1389755334746202113"

LEAGUE_NAME = "Kiddos"
NUM_TEAMS = 10
DRAFT_TYPE = "snake"

# Not yet known — deliberately left unset rather than hardcoded with a
# placeholder. Populate once the league schedules the draft / sets order.
DRAFT_DATE = None
DRAFT_ORDER = None

# --- Scoring --------------------------------------------------------------
# Full PPR with a TE premium bonus layered on top of standard PPR reception
# scoring (i.e. a TE catch is worth PPR_RECEPTION + TE_PREMIUM_BONUS).

SCORING = {
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

# --- Roster ----------------------------------------------------------------
#
# MANUAL OVERRIDE — READ BEFORE TOUCHING:
#
# Sleeper's league API (`get_league`) still reports this league's OLD roster
# structure: QB, 2x RB, 2x WR, TE, 2x FLEX, SUPERFLEX, 6 BN. That is STALE.
# The league verbally agreed to drop the required TE slot and add a 3rd FLEX
# in its place. Sleeper's settings were never updated to reflect this, and
# there is no live source of truth for the real roster — this hardcoded list
# IS the source of truth until/unless the league re-syncs Sleeper's settings.
#
# Do NOT "fix" this to match what `get_league` returns — that would be
# reintroducing the stale/wrong data this override exists to correct.
# TE premium scoring (see SCORING["te_premium_bonus"] above) still applies
# regardless of which slot a TE is drafted into.
#
# 9 starters + 6 bench = 15 roster spots = 15 draft rounds.
ROSTER_POSITIONS = [
    "QB",
    "RB", "RB",
    "WR", "WR",
    "FLEX", "FLEX", "FLEX",
    "SUPER_FLEX",
    "BN", "BN", "BN", "BN", "BN", "BN",
]

NUM_DRAFT_ROUNDS = len(ROSTER_POSITIONS)  # 15

# --- Misc --------------------------------------------------------------

SLEEPER_API_BASE = "https://api.sleeper.app/v1"
PLAYERS_CACHE_PATH = "data/players_cache.json"
PLAYERS_CACHE_MAX_AGE_HOURS = 24  # daily refresh, per Sleeper's polling guidance

DRAFT_POLL_INTERVAL_SECONDS = 3
