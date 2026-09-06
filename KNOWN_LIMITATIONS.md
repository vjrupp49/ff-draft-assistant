# Known limitations — read before the draft

Plain-language list of things the tool gets wrong or doesn't do, and what
to do about each one during a live draft. Kept short on purpose. Full
history and root-cause detail live in `docs/handoff/`.

---

## 1. It drafts too many RB/QB and not enough WR

**What it is.** Under this league's SUPERFLEX + TE-premium scoring, QBs and
RBs genuinely score more raw fantasy points than WRs at the same draft
position — so the engine leans that way. That part is legitimate. The
*bug* on top of it: when the engine fills a FLEX or SUPER_FLEX slot, it
compares candidates on raw points **without looking at what's already on
your roster**, so it keeps stacking RB/QB even after you have plenty and
your WR corps is thin.

**What you'll see.** By roughly round 6–7 onward, recommendations skew RB
(and sometimes QB) harder than feels right. Final mock rosters land around
QB 3 / RB 7–8 / WR 3–4 / TE 1, versus a more typical QB 3 / RB 5 / WR 6 /
TE 1.

**Cost.** ~43 points of risk-adjusted value on average versus a
positionally balanced roster (measured range: ~4 to ~135 across test
drafts). Real, not cosmetic.

**What to do.** From the mid rounds on, if the top pick is another RB/QB
and you already have depth there, look one or two spots down the board —
the "also in the mix" list — for the best WR and strongly consider taking
that instead. The engine's *ranking* of players within a position is
still trustworthy; it's the cross-position balance that's off.

*Chunk 69:* the recommendation now shows an inline ⚠️ **Reach** line when
its real ADP is 15+ picks early ("likely still there next round"), and
names one alternative who is genuinely at risk before your next turn.
It's a hint, not a rule — but it's exactly the "look down the board"
prompt this limitation calls for.

**Status.** Root cause is understood and precisely located. Three
separate fix attempts failed for real structural reasons. Accepted as a
known limitation for this draft rather than rushed.

---

## 2. It occasionally "plays it safe" and passes on an at-risk player

**What it is** (nicknamed "Track B"). Now and then the engine recommends a
safe bench-depth player over a higher-upside starter-quality player who is
genuinely about to be drafted by someone else — i.e. it doesn't fully
price in "this guy won't be here when I pick again."

**What you'll see.** Rare — happens on roughly 3% of your picks, and only
about 1 in 3 drafts has even a single instance. When it does, the top
recommendation is a solid-but-unexciting pick while an obviously better
player with a tight ADP is sitting right there.

**What to do.** If the #1 recommendation looks conservative and there's a
clearly better player who probably won't survive to your next turn, trust
your read and take the better player.

**Status.** Confirmed real but never pinned to an exact mechanism.
Low-frequency, so left for a later cycle.

---

## 3. The opponent model is slow (but not too slow)

**What it is.** Simulating the other 9 teams' picks is the most expensive
part of each recommendation — the bulk of the compute per pick. It has
never been optimized.

**What you'll see.** A recommendation takes a few seconds. Worst case
measured was ~8 seconds, comfortably inside the 60-second pick clock. Note
that that measurement predates some later additions to the math, so real
worst-case today could be somewhat higher — still expected to be well
under the clock, but it hasn't been re-timed.

**What to do.** Nothing during the draft. If a recommendation ever seems
to hang for 20+ seconds, fall back to the raw VBD board (the "full board"
in Draft Outlook) for that pick and move on.

**Status.** Known since early on, deliberately not touched. A real
optimization pass is a future project.

---

## 4. Only one league's format is truly wired in at a time

**What it is.** You can switch between Kiddos and Former Bradley Bums in
the UI for browsing, and it works — because both leagues have the
**identical** format (SUPERFLEX, full PPR, TE premium, 10 teams, same
roster slots). Under the hood, the actual scoring/replacement-level math
still reads one global config, not the per-league one. If a third league
with a *different* format were ever added, the browsing views could show
wrong numbers for it.

**What you'll see.** Nothing, for either real league. A mismatched
third-league request is rejected outright (HTTP 409) rather than silently
computing garbage.

**What to do.** Nothing. Just don't assume the league switcher would "just
work" for a differently-scored league without real work first.

---

## 5. ~~There's a stray, broken launch config one folder up~~ — FIXED (Chunk 68)

**What it was.** `Fantasy Football/.claude/launch.json` (the *parent* of
this repo) was an old, broken duplicate launcher entry, also named
"ff-draft-assistant" and also on port 8000 — it would fail to start the
app if picked up.

**Fixed in Chunk 68.** The stray parent-folder file was deleted. The one
correct launcher, `ff-draft-assistant/.claude/launch.json`, is now
committed to the repo. There is no longer a duplicate to trip over.

**If the app ever "won't start"** it's almost certainly port 8000 already
in use — kill any leftover `python`/`uvicorn` process and retry, or start
it by hand from **inside** the `ff-draft-assistant` folder:

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
