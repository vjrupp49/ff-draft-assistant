"""
League settings for the currently-active fantasy football league.

CHUNK 52: these module-level constants now DERIVE from app/leagues.py's
`ACTIVE_LEAGUE` (a `LeagueConfig`), rather than being hardcoded here
directly -- see that module's docstring for the full per-league config
model and why it exists (a second real league, "Former Bradley Bums",
confirmed Chunk 51 to share Kiddos' exact scoring/roster format). Every
name below is UNCHANGED from before this chunk (same names, same values
for Kiddos, the default ACTIVE_LEAGUE) -- no consumer of this module
needed to change. To point the whole backend at a different league,
change `app.leagues.ACTIVE_LEAGUE_KEY`, not anything in this file.

This is still a personal, single-user tool -- no env-var indirection, no
request-time league switching (that's explicitly out of scope for Chunk
52; see app/leagues.py's own docstring).
"""

from app.leagues import ACTIVE_LEAGUE

# --- Sleeper identifiers ------------------------------------------------

SLEEPER_LEAGUE_ID = ACTIVE_LEAGUE.league_id
SLEEPER_DRAFT_ID = ACTIVE_LEAGUE.draft_id

LEAGUE_NAME = ACTIVE_LEAGUE.league_name
NUM_TEAMS = ACTIVE_LEAGUE.num_teams
DRAFT_TYPE = ACTIVE_LEAGUE.draft_type
PICK_TIMER_SECONDS = ACTIVE_LEAGUE.pick_timer_seconds

# Confirmed directly via the live Sleeper API, Chunk 51 (both leagues).
# DRAFT_ORDER stays None -- that's each league's live, per-team slot
# assignment (synced elsewhere via the Sleeper draft endpoint, see
# app/services/draft_state.py), not a static config value.
DRAFT_DATE = ACTIVE_LEAGUE.draft_date
DRAFT_ORDER = None

# --- Scoring --------------------------------------------------------------
# Full PPR with a TE premium bonus layered on top of standard PPR reception
# scoring (i.e. a TE catch is worth PPR_RECEPTION + TE_PREMIUM_BONUS).
# See app/leagues.py's `_SUPERFLEX_TE_PREMIUM_SCORING` for the per-field
# breakdown -- shared by both real leagues today (confirmed, not assumed).

SCORING = ACTIVE_LEAGUE.scoring

# --- Roster ----------------------------------------------------------------
#
# MANUAL OVERRIDE, HISTORICAL CONTEXT -- READ BEFORE TOUCHING:
#
# Kiddos' Sleeper league API used to report a STALE roster structure (QB,
# 2x RB, 2x WR, TE, 2x FLEX, SUPERFLEX, 6 BN) that didn't match what the
# league verbally agreed to (drop the required TE slot, add a 3rd FLEX).
# This hardcoded override was the real source of truth while that
# staleness existed. Chunk 51's fresh pull of Kiddos' LIVE settings found
# Sleeper now reports the corrected structure directly (matching this
# override exactly) -- the original staleness this override was built to
# correct appears to have resolved itself since. Left in place anyway
# (matches current reality either way, and provides the same safety net
# if it ever drifts again) rather than silently trusting a live endpoint
# this project has already been burned by once.
#
# See app/leagues.py's `_STANDARD_SUPERFLEX_ROSTER` for the actual value
# -- shared by both real leagues today (confirmed via both `league.
# roster_positions` AND `draft.settings.slots_*`, Chunk 51).
ROSTER_POSITIONS = ACTIVE_LEAGUE.roster_positions

NUM_DRAFT_ROUNDS = len(ROSTER_POSITIONS)  # 15

# --- Misc --------------------------------------------------------------

SLEEPER_API_BASE = "https://api.sleeper.app/v1"
PLAYERS_CACHE_PATH = "data/players_cache.json"
PLAYERS_CACHE_MAX_AGE_HOURS = 24  # daily refresh, per Sleeper's polling guidance

DRAFT_POLL_INTERVAL_SECONDS = 3
