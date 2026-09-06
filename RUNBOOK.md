# Draft-Day Runbook

Glance, don't read. `KNOWN_LIMITATIONS.md` has the why.

---

## Start (~2 min)

Terminal, inside `ff-draft-assistant`:

```
.venv/Scripts/python.exe scripts/refresh_caches.py
.venv/Scripts/python.exe scripts/preflight.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`preflight` **must** end `RESULT: PASS -- all clear`. If not, read the
`WARN`/`FAIL` line — usually a stale cache (re-run refresh) or wrong slot.

Leave the server running. **Open http://127.0.0.1:8000** → **My draft
slot = 3** → mode **Live Draft** → **Start Watching**.

Keep **Sleeper open separately**. You submit every pick there; this only
watches and advises.

---

## Reading the screen

- **Big name + score** = the pick. **"Also in the mix"** = next-best.
- **Amber ⚠️ Reach line:** the pick's real ADP is 15+ picks away — you
  can likely still get them next round. It names someone about to be
  gone; take *that* player now, come back for the reach next turn.
- **RB/QB lean:** the engine over-drafts RB/QB vs. WR. If a mid-round
  RB/QB pick feels like a reach even with no warning, look one spot down
  "Also in the mix" for the best WR and strongly consider it.
- **Close call** (#1 and #2 basically tied, pick looks a bit safe): low
  stakes, trust your read.

---

## If something breaks

- **Spinning past ~20s** ("RECALCULATING…" won't clear): don't wait. Use
  **Draft Outlook → FULL BOARD** (raw value; doesn't hide drafted
  players — cross-check the feed), or draft off Sleeper's ADP that pick.
- **"RECONNECTING…" top-right:** normal (wifi blip / tab slept). Retries
  every 2s, resyncs itself. Worry only if stuck past ~1 min → check the
  server terminal is still up.
- **Server crashed / terminal closed:** re-run the `uvicorn …` line. It
  re-reads Sleeper's pick feed on startup and resumes where the draft
  is — you don't lose your place. Reopen the URL.
- **Anything obviously wrong** (garbage name, nonsense score, frozen):
  skip the tool that pick, draft off your own board / ADP, move on.

---

## Golden rule

The tool advises. **You draft**, in Sleeper, every pick. In doubt, take
who you'd have taken without it.
