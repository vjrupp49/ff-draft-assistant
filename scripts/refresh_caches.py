"""
Chunk 70 -- force-refresh the disk caches the app builds from.

The projection / ADP / Sleeper-player caches all carry a 24h TTL and
rebuild lazily on the next request that needs them once stale. This
script forces that rebuild NOW -- useful right before a draft (the Chunk
68 pre-flight flags a stale cache but doesn't fix it), or any time you
want fresh data without waiting for the TTL to lapse.

It hits the network (nflverse stats, FanballFC ADP, Sleeper's player
list) -- all read-only, public, nothing to do with either league's
draft.

Usage (from the repo root):
  .venv/Scripts/python.exe scripts/refresh_caches.py

Exit 0 if every cache is now < 24h old; 1 otherwise. Prints before/after
age + a content fingerprint so you can see it actually re-fetched, not
just that the calls returned.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.services import adp  # noqa: E402
from app.services.projections import build_baseline_projections  # noqa: E402
from app.services.sleeper import sleeper_client  # noqa: E402

_FILES = [
    "data/players_cache.json",
    "data/adp_cache.json",
    "data/adp_fallback_cache.json",
    "data/baseline_projections.json",
]


def _snap(rel: str) -> dict:
    p = _REPO_ROOT / rel
    if not p.exists():
        return {"exists": False}
    b = p.read_bytes()
    d = {
        "exists": True,
        "mtime": p.stat().st_mtime,
        "age_h": (time.time() - p.stat().st_mtime) / 3600,
        "size": len(b),
        "sha12": hashlib.sha256(b).hexdigest()[:12],
    }
    if rel.endswith("baseline_projections.json"):
        try:
            j = json.loads(b)
            d["generated_at"] = j.get("generated_at")
            d["players"] = len(j.get("players", []))
        except (json.JSONDecodeError, OSError):
            pass
    return d


def _line(rel: str, s: dict) -> str:
    if not s.get("exists"):
        return f"  {rel}: MISSING"
    extra = ""
    if "generated_at" in s:
        extra = f"  generated_at={s['generated_at']}  players={s.get('players')}"
    return (f"  {rel}: age={s['age_h']:.2f}h  size={s['size']}  sha={s['sha12']}"
            f"  mtime={time.strftime('%H:%M:%S', time.localtime(s['mtime']))}{extra}")


async def main() -> int:
    before = {f: _snap(f) for f in _FILES}
    print(f"BEFORE  ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    for f in _FILES:
        print(_line(f, before[f]))

    print("\nFORCING REFRESH ...")
    n_players = len(await sleeper_client.get_all_players(force_refresh=True))
    print(f"  Sleeper players: {n_players}")
    adp_ok = bool(await adp.fetch_adp(force_refresh=True))
    fb_ok = bool(await adp.fetch_fallback_adp(force_refresh=True))
    print(f"  FFC ADP: {'ok' if adp_ok else 'FAILED'}   fallback: {'ok' if fb_ok else 'none'}")
    proj = await build_baseline_projections(force_refresh=True)
    print(f"  projections: {len(proj.get('players', []))} players, "
          f"generated_at={proj.get('generated_at')}")

    after = {f: _snap(f) for f in _FILES}
    print(f"\nAFTER  ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    for f in _FILES:
        print(_line(f, after[f]))

    print("\nVERIFICATION")
    all_fresh = True
    for f in _FILES:
        b, a = before[f], after[f]
        if not a.get("exists"):
            print(f"  {f}: STILL MISSING -- FAIL")
            all_fresh = False
            continue
        rewritten = a["mtime"] > b.get("mtime", 0) + 1
        fresh = a["age_h"] < 24
        content_changed = a["sha12"] != b.get("sha12")
        gen_changed = a.get("generated_at") != b.get("generated_at") if "generated_at" in a else None
        if not (rewritten and fresh):
            all_fresh = False
        note = "content changed" if content_changed else (
            "content byte-identical (upstream data unchanged since last fetch) -- "
            "file was still re-fetched + rewritten (mtime advanced), TTL reset")
        if gen_changed is not None:
            note += f"; generated_at {'changed' if gen_changed else 'UNCHANGED (?)'}"
        print(f"  {f}: rewritten={rewritten}  age={a['age_h']*60:.1f}min (<24h: {fresh})  -- {note}")

    print("\nRESULT:", "all caches < 24h" if all_fresh else "SOMETHING NEEDS A LOOK")
    return 0 if all_fresh else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
