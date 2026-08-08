# FF Draft Assistant

A personal, single-user fantasy football draft assistant for the **Kiddos**
league (Sleeper). Phase 1: live Sleeper connectivity + a websocket draft-pick
feed. Later phases add rankings/projections and the actual draft-day UI.

Free data sources only, forever, unless a cost is explicitly flagged first:
- [Sleeper API](https://docs.sleeper.com/) — free, public, read-only, no auth
- [`nfl_data_py`](https://github.com/nflverse/nfl_data_py) — free NFL data
- Free projection sources (added in a later phase)

## Tech stack

- **Backend**: FastAPI + WebSockets (chosen over Streamlit for full control
  over a custom, gamified, visually distinctive draft-day UI)
- **Frontend**: plain HTML/CSS/JS served by FastAPI (no framework yet)
- **Language**: Python only

## League settings

Hardcoded in [`app/config.py`](app/config.py) — league name "Kiddos", 10
teams, snake draft, full PPR + TE premium scoring.

**Roster note:** Sleeper's league settings are stale (still show a required
TE + only 2 FLEX). The league verbally agreed to drop the required TE for a
3rd FLEX instead. `app/config.py` hardcodes the *corrected* 15-round roster
(`QB, 2 RB, 2 WR, 3 FLEX, SUPER_FLEX, 6 BN`) as the actual source of truth —
see the comment there for details. `GET /api/league-check` returns both
Sleeper's raw (stale) settings and the override side by side so this stays
easy to sanity-check.

Draft date and draft order are not yet set by the league and are
intentionally left as `None` in config rather than given placeholder values.

## Setup

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Then visit:
- http://127.0.0.1:8000/ — placeholder home page
- http://127.0.0.1:8000/api/league-check — live Sleeper league data +
  manual roster override, side by side
- `ws://127.0.0.1:8000/ws/draft` — live draft-pick feed (polls Sleeper every
  3 seconds, pushes new picks as JSON)

## Project structure

```
ff-draft-assistant/
  app/
    main.py              # FastAPI entrypoint + WebSocket for live draft picks
    config.py            # league settings (hardcoded, see above)
    routers/
    models/
    services/
      sleeper.py          # Sleeper API client (read-only)
    static/
    templates/
  data/
    players_cache.json    # cached Sleeper player dump (gitignored, generated)
  requirements.txt
  README.md
```
