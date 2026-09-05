"""
Chunk 68 -- pre-draft pre-flight check.

Run this in the hour before a real draft. It confirms the boring things
that are easy to get wrong and expensive to discover mid-draft:

  1. The backend is pointed at the RIGHT league (Kiddos vs. Former Bradley
     Bums) -- and specifically at whichever one is drafting next.
  2. The active SLEEPER_DRAFT_ID matches that league's registry entry
     (catches a hand-edit that broke app/config.py's derivation).
  3. Sleeper's API is reachable, the draft exists, and your slot resolves.
  4. The cached projection / ADP / player data isn't suspiciously stale.

Usage:
  python scripts/preflight.py                 # check ACTIVE_LEAGUE (default)
  python scripts/preflight.py --league former_bradley_bums

Exit code 0 if nothing FAILED (WARNs are allowed), 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.leagues import ACTIVE_LEAGUE_KEY, LEAGUES  # noqa: E402
from app.services.roster_identity import MY_SLEEPER_USER_ID  # noqa: E402
from app.services.sleeper import SleeperAPIError, sleeper_client  # noqa: E402

# Caches to age-check: (path, human name, warn-past-hours). The engine
# auto-refreshes these on a 24h TTL, so the real worry is "old AND we're
# about to draft offline / FFC is down" -- warn a bit past the TTL.
_CACHES = [
    ("data/baseline_projections.json", "baseline projections", 30),
    ("data/adp_cache.json", "market ADP (FFC)", 30),
    ("data/players_cache.json", "Sleeper player list", 48),
]

_RESULTS: list[tuple[str, str]] = []  # (level, message); level in {PASS, WARN, FAIL}


def _record(level: str, msg: str) -> None:
    _RESULTS.append((level, msg))
    marker = {"PASS": "  ok  ", "WARN": " WARN ", "FAIL": " FAIL "}[level]
    print(f"[{marker}] {msg}")


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


def _check_league(league_key: str) -> str:
    _section("1. league selection")
    if league_key not in LEAGUES:
        _record("FAIL", f"unknown league key {league_key!r} (known: {sorted(LEAGUES)})")
        return league_key
    cfg = LEAGUES[league_key]
    _record("PASS", f"checking league: {cfg.league_name}  (key={cfg.key}, {cfg.num_teams} teams, "
                    f"{cfg.pick_timer_seconds}s pick timer)")
    if league_key == ACTIVE_LEAGUE_KEY:
        _record("PASS", f"this IS the backend's ACTIVE_LEAGUE_KEY -- config.py derives from it")
    else:
        _record("WARN", f"backend ACTIVE_LEAGUE_KEY is {ACTIVE_LEAGUE_KEY!r}, not {league_key!r} -- "
                        f"if you're about to draft {cfg.league_name}, edit app/leagues.py's "
                        f"ACTIVE_LEAGUE_KEY and restart the server")

    # Which league drafts next?
    today = date.today()
    dated = []
    for c in LEAGUES.values():
        if c.draft_date:
            try:
                dated.append((date.fromisoformat(c.draft_date), c))
            except ValueError:
                pass
    upcoming = sorted((d for d in dated if d[0] >= today), key=lambda d: d[0])
    if upcoming:
        next_date, next_cfg = upcoming[0]
        days = (next_date - today).days
        when = "TODAY" if days == 0 else ("TOMORROW" if days == 1 else f"in {days} days")
        if next_cfg.key == league_key:
            _record("PASS", f"{next_cfg.league_name} drafts next ({next_cfg.draft_date}, {when}) -- matches")
        else:
            _record("WARN", f"the next scheduled draft is {next_cfg.league_name} "
                            f"({next_cfg.draft_date}, {when}), but you're pre-flighting {cfg.league_name}")
    else:
        _record("WARN", f"no upcoming draft_date in the registry (all in the past?) -- can't cross-check")
    return league_key


def _check_draft_id(league_key: str) -> str | None:
    _section("2. draft_id integrity")
    cfg = LEAGUES.get(league_key)
    if cfg is None:
        _record("FAIL", "no league config -- skipping draft_id check")
        return None
    _record("PASS", f"registry draft_id for {cfg.league_name}: {cfg.draft_id}")
    if league_key == ACTIVE_LEAGUE_KEY:
        from app.config import SLEEPER_DRAFT_ID, SLEEPER_LEAGUE_ID
        if SLEEPER_DRAFT_ID == cfg.draft_id:
            _record("PASS", f"config.SLEEPER_DRAFT_ID matches the registry ({SLEEPER_DRAFT_ID})")
        else:
            _record("FAIL", f"config.SLEEPER_DRAFT_ID ({SLEEPER_DRAFT_ID}) != registry draft_id "
                            f"({cfg.draft_id}) -- config derivation is broken")
        if SLEEPER_LEAGUE_ID != cfg.league_id:
            _record("FAIL", f"config.SLEEPER_LEAGUE_ID ({SLEEPER_LEAGUE_ID}) != registry league_id "
                            f"({cfg.league_id})")
    _record("PASS", "-> open sleeper.com/draft/nfl/" + cfg.draft_id + " and eyeball that it's the right draft")
    return cfg.draft_id


async def _check_sleeper(draft_id: str | None, league_key: str) -> None:
    _section("3. Sleeper connectivity + draft state")
    if not draft_id:
        _record("FAIL", "no draft_id -- skipping Sleeper checks")
        return
    cfg = LEAGUES.get(league_key)
    try:
        draft = await sleeper_client.get_draft(draft_id)
    except SleeperAPIError as exc:
        _record("FAIL", f"Sleeper get_draft failed: {exc}")
        return
    if not isinstance(draft, dict) or not draft.get("draft_id"):
        _record("FAIL", f"Sleeper returned nothing usable for draft {draft_id!r}")
        return
    _record("PASS", f"Sleeper reachable; draft status = {draft.get('status')!r}, type = {draft.get('type')!r}")

    status = draft.get("status")
    if status == "complete":
        _record("WARN", "this draft is already COMPLETE on Sleeper -- wrong draft_id, or it's over")
    elif status not in ("pre_draft", "drafting", "paused"):
        _record("WARN", f"unexpected draft status {status!r}")

    settings = draft.get("settings") or {}
    teams = settings.get("teams")
    if cfg and teams and int(teams) != cfg.num_teams:
        _record("WARN", f"Sleeper says {teams} teams, registry says {cfg.num_teams}")
    else:
        _record("PASS", f"team count: {teams}")

    order = draft.get("draft_order") or {}
    if not order:
        _record("WARN", "draft_order is empty -- Sleeper usually fills it once the room is set; "
                        "check again closer to draft time")
    elif MY_SLEEPER_USER_ID in order:
        _record("PASS", f"your slot (from draft_order): {order[MY_SLEEPER_USER_ID]}")
    else:
        _record("WARN", f"your Sleeper user_id ({MY_SLEEPER_USER_ID}) is not in draft_order yet -- "
                        "you'll need to enter your slot manually in the app")

    try:
        picks = await sleeper_client.get_draft_picks(draft_id)
        _record("PASS", f"get_draft_picks OK -- {len(picks)} pick(s) made so far")
    except SleeperAPIError as exc:
        _record("FAIL", f"Sleeper get_draft_picks failed: {exc}")

    if cfg:
        try:
            league = await sleeper_client.get_league(cfg.league_id)
            _record("PASS", f"league '{league.get('name')}' reachable (season {league.get('season')}, "
                            f"status {league.get('status')!r})")
        except SleeperAPIError as exc:
            _record("WARN", f"get_league failed (not draft-critical): {exc}")


def _check_caches() -> None:
    _section("4. cached data freshness")
    now = time.time()
    for rel, name, warn_hours in _CACHES:
        p = _REPO_ROOT / rel
        if not p.exists():
            _record("WARN", f"{name}: {rel} missing -- will be built on first request "
                            "(needs network; do one warm-up request before the draft)")
            continue
        age_h = (now - p.stat().st_mtime) / 3600
        gen = ""
        if name == "baseline projections":
            try:
                ts = json.loads(p.read_text(encoding="utf-8")).get("generated_at")
                if ts:
                    gen = f", generated_at {ts}"
            except (json.JSONDecodeError, OSError):
                pass
        if age_h > warn_hours:
            _record("WARN", f"{name}: {age_h:.0f}h old{gen} -- refresh with a warm-up request while "
                            "you still have network (the 24h TTL will rebuild it on next use)")
        else:
            _record("PASS", f"{name}: {age_h:.0f}h old{gen}")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Pre-draft pre-flight check")
    parser.add_argument("--league", default=ACTIVE_LEAGUE_KEY, help=f"league key (default: {ACTIVE_LEAGUE_KEY})")
    args = parser.parse_args()

    print(f"FF Draft Assistant -- pre-flight  ({datetime.now(timezone.utc).isoformat(timespec='seconds')})")

    league_key = _check_league(args.league)
    draft_id = _check_draft_id(league_key)
    await _check_sleeper(draft_id, league_key)
    _check_caches()

    fails = [m for lvl, m in _RESULTS if lvl == "FAIL"]
    warns = [m for lvl, m in _RESULTS if lvl == "WARN"]
    print("\n" + "=" * 60)
    if fails:
        print(f"RESULT: FAIL -- {len(fails)} blocking issue(s), {len(warns)} warning(s)")
        for m in fails:
            print(f"  FAIL: {m}")
        return 1
    if warns:
        print(f"RESULT: PASS with {len(warns)} warning(s) -- review each before drafting")
        return 0
    print("RESULT: PASS -- all clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
