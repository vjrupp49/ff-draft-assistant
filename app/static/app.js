(function () {
  "use strict";

  // ---- element refs ----
  var setupEl = document.getElementById("setup");
  var screenEl = document.getElementById("screen");
  var mySlotInput = document.getElementById("my-slot");
  var modeButtons = document.querySelectorAll(".mode-btn");
  var mockOptions = document.getElementById("mock-options");
  var mockSeedInput = document.getElementById("mock-seed");
  var mockDelayInput = document.getElementById("mock-delay");
  var startBtn = document.getElementById("start-btn");
  var setupError = document.getElementById("setup-error");

  var roundLabel = document.getElementById("round-label");
  var pickLabel = document.getElementById("pick-label");
  var turnBadge = document.getElementById("turn-badge");
  var sessionPill = document.getElementById("session-pill");

  var heroCard = document.getElementById("hero-card");
  var heroPos = document.getElementById("hero-pos");
  var heroTeam = document.getElementById("hero-team");
  var heroTie = document.getElementById("hero-tie");
  var heroName = document.getElementById("hero-name");
  var heroScore = document.getElementById("hero-score");
  var heroWhy = document.getElementById("hero-why");
  var provisionalBanner = document.getElementById("provisional-banner");

  var altsList = document.getElementById("alts-list");

  var recalcBadge = document.getElementById("recalc-badge");
  var feedList = document.getElementById("feed-list");
  var cheapCountEl = document.getElementById("cheap-count");
  var expensiveCountEl = document.getElementById("expensive-count");

  var selectedMode = "live";
  var currentHeroScore = null;
  var feedHasItems = false;

  // ---- setup form ----

  modeButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      modeButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      selectedMode = btn.dataset.mode;
      mockOptions.classList.toggle("hidden", selectedMode !== "mock");
    });
  });

  startBtn.addEventListener("click", function () {
    setupError.classList.add("hidden");
    var mySlot = parseInt(mySlotInput.value, 10);
    if (!mySlot || mySlot < 1) {
      showSetupError("Enter a valid draft slot.");
      return;
    }
    startBtn.disabled = true;
    startBtn.textContent = "Starting...";

    var path = selectedMode === "mock" ? "/api/live/start-mock" : "/api/live/start-live";
    var body = selectedMode === "mock"
      ? {
          my_slot: mySlot,
          seed: parseInt(mockSeedInput.value, 10) || 1,
          delay_seconds: parseFloat(mockDelayInput.value) || 1.5,
        }
      : { my_slot: mySlot };

    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.text().then(function (t) {
            throw new Error(t || ("Request failed (" + resp.status + ")"));
          });
        }
        return resp.json();
      })
      .then(function (snapshot) {
        enterScreen(snapshot);
        connectWebSocket();
      })
      .catch(function (err) {
        showSetupError(err.message || "Could not start.");
        startBtn.disabled = false;
        startBtn.textContent = "Start Watching";
      });
  });

  function showSetupError(msg) {
    setupError.textContent = msg;
    setupError.classList.remove("hidden");
  }

  function enterScreen(snapshot) {
    setupEl.classList.add("hidden");
    screenEl.classList.remove("hidden");
    applySnapshot(snapshot);
  }

  // ---- websocket ----

  // Reconnect with backoff on drop -- found by actually restarting the
  // server mid-draft (Chunk 12 real-Sleeper dry run) that a dropped
  // connection just sat on "DISCONNECTED" forever with no retry. On a
  // real phone during a real draft (screen lock, wifi blip, brief server
  // hiccup) that's a silent-failure risk this app exists to prevent, so
  // this reconnects automatically rather than requiring a manual reload.
  // A fresh connection's register() always sends a full snapshot, which
  // applySnapshot() uses to resync the whole screen (headline, hero card,
  // feed, counts) -- no separate "catch up" path needed.
  var RECONNECT_DELAY_MS = 2000;
  var reconnectTimer = null;

  function connectWebSocket() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws/draft-live");
    ws.onopen = function () {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };
    ws.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      handleMessage(msg);
    };
    ws.onclose = function () {
      sessionPill.textContent = "RECONNECTING…";
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(function () {
          reconnectTimer = null;
          connectWebSocket();
        }, RECONNECT_DELAY_MS);
      }
    };
    ws.onerror = function () {
      ws.close();
    };
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "snapshot":
        applySnapshot(msg);
        break;
      case "pick":
        applyPick(msg);
        break;
      case "recalculating":
        setRecalculating(true);
        break;
      case "draft_score":
        setRecalculating(false);
        applyDraftScore(msg, false);
        break;
      case "draft_complete":
        applyDraftComplete();
        break;
      case "error":
        console.error("live draft error:", msg.message);
        break;
    }
  }

  // ---- rendering ----

  function applySnapshot(s) {
    if (s.mode) sessionPill.textContent = s.mode === "mock" ? "MOCK DRAFT" : "LIVE DRAFT";
    updateHeadline(s);
    if (s.last_pick_event) renderFeedFromEvent(s.last_pick_event);
    if (s.last_draft_score) applyDraftScore(s.last_draft_score, true);
    setRecalculating(!!s.is_recalculating);
    updateCounts(s.cheap_update_count, s.expensive_update_count);
  }

  function updateHeadline(s) {
    if (s.current_round) roundLabel.textContent = "ROUND " + s.current_round;
    if (s.current_pick_no) pickLabel.textContent = "PICK " + s.current_pick_no;

    if (s.status === "waiting") {
      turnBadge.textContent = "WAITING FOR DRAFT TO START";
      turnBadge.className = "turn-badge waiting";
    } else if (s.is_my_turn) {
      turnBadge.textContent = "YOU'RE ON THE CLOCK";
      turnBadge.className = "turn-badge on-clock";
    } else if (typeof s.picks_until_your_turn === "number") {
      turnBadge.textContent = s.picks_until_your_turn === 1
        ? "YOU'RE UP NEXT"
        : s.picks_until_your_turn + " PICKS UNTIL YOUR TURN";
      turnBadge.className = "turn-badge opp";
    }
  }

  function applyPick(evt) {
    updateHeadline(evt);
    renderFeedFromEvent(evt);
    updateCounts(undefined, undefined, 1, 0);
  }

  function renderFeedFromEvent(evt) {
    if (!feedHasItems) {
      feedList.innerHTML = "";
      feedHasItems = true;
    }
    var li = document.createElement("li");
    li.className = "feed-item" + (evt.is_my_pick ? " mine" : "");
    var pos = (evt.player && evt.player.position) || "";
    var name = (evt.player && evt.player.name) || "Unknown";
    li.innerHTML =
      '<span class="feed-pick-no">#' + evt.pick_no + '</span>' +
      '<span class="pos-pill pos-' + pos + '">' + (pos || "—") + '</span>' +
      '<span class="feed-player"><span class="feed-player-name">' + escapeHtml(name) +
      (evt.is_my_pick ? '<span class="feed-player-mine-tag">YOU</span>' : "") +
      '</span></span>';
    feedList.insertBefore(li, feedList.firstChild);
    while (feedList.children.length > 40) {
      feedList.removeChild(feedList.lastChild);
    }
  }

  function setRecalculating(active) {
    recalcBadge.classList.toggle("hidden", !active);
    heroCard.classList.toggle("recalculating", active);
  }

  function applyDraftScore(payload, isReplay) {
    var ds = payload.draft_score;
    var ex = payload.explanation;
    var alts = payload.alternatives_considered || [];
    if (!ds) return;

    heroPos.textContent = ds.position || "—";
    heroPos.className = "pos-pill pos-" + (ds.position || "");
    heroTeam.textContent = ds.team || "";
    heroName.textContent = ds.name || "—";
    heroTie.classList.toggle("hidden", !ds.statistically_tied_with_top_pick);

    animateScore(Math.round(ds.score));
    heroWhy.textContent = explanationToText(ex);
    renderAlts(alts);

    // Persistent, high-contrast signal that this number is a projection
    // against simulated opponent picks, not a confirmed result -- see
    // the .provisional CSS rule for why this replaced a subtle inline
    // parenthetical (Chunk 11 follow-up: it was too easy to miss).
    heroCard.classList.toggle("provisional", !!payload.is_provisional);
    provisionalBanner.classList.toggle("hidden", !payload.is_provisional);

    if (!isReplay) updateCounts(undefined, undefined, 0, 1);
    if (payload.current_round) updateHeadline(payload);
  }

  function explanationToText(ex) {
    if (!ex) return "";
    if (ex.projected_role === "starter") {
      return "Fills a real starting lineup slot on your roster right now.";
    }
    var pct = ex.bench_discount_applied != null ? Math.round(ex.bench_discount_applied * 100) + "%" : "a fraction of";
    return "Would mostly ride your bench (rank #" + (ex.bench_rank || "?") + " at the position) — valued at roughly " + pct + " full weight.";
  }

  function animateScore(target) {
    var start = currentHeroScore == null ? target : currentHeroScore;
    currentHeroScore = target;
    // Set the correct final value SYNCHRONOUSLY first -- found by actually
    // testing this (not just writing it): requestAnimationFrame can be
    // throttled to near-never on a backgrounded/unfocused tab, which left
    // the score stuck on its placeholder forever since the only place
    // textContent got set was inside the rAF callback. The animation below
    // is now pure enhancement on top of an already-correct value, not a
    // requirement for the value to display at all.
    heroScore.textContent = target.toLocaleString();
    if (start === target) return;

    var duration = 500;
    var startTime = performance.now();
    heroScore.classList.add("pop");
    function step(now) {
      var t = Math.min(1, (now - startTime) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      var value = Math.round(start + (target - start) * eased);
      heroScore.textContent = value.toLocaleString();
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        heroScore.textContent = target.toLocaleString();
        setTimeout(function () { heroScore.classList.remove("pop"); }, 200);
      }
    }
    requestAnimationFrame(step);
  }

  function renderAlts(alts) {
    if (!alts.length) {
      altsList.innerHTML = '<li class="alt-empty">No alternatives computed yet.</li>';
      return;
    }
    altsList.innerHTML = alts.map(function (a, i) {
      return (
        '<li class="alt-row">' +
        '<span class="alt-rank">' + (i + 2) + "</span>" +
        '<span class="pos-pill pos-' + a.position + '">' + a.position + "</span>" +
        '<span class="alt-name">' + escapeHtml(a.name) + "</span>" +
        '<span class="alt-score">' + Math.round(a.score).toLocaleString() + "</span>" +
        "</li>"
      );
    }).join("");
  }

  function updateCounts(cheapAbs, expensiveAbs, cheapDelta, expensiveDelta) {
    if (typeof cheapAbs === "number") {
      cheapCountEl.textContent = cheapAbs;
    } else if (cheapDelta) {
      cheapCountEl.textContent = (parseInt(cheapCountEl.textContent, 10) || 0) + cheapDelta;
    }
    if (typeof expensiveAbs === "number") {
      expensiveCountEl.textContent = expensiveAbs;
    } else if (expensiveDelta) {
      expensiveCountEl.textContent = (parseInt(expensiveCountEl.textContent, 10) || 0) + expensiveDelta;
    }
  }

  function applyDraftComplete() {
    turnBadge.textContent = "DRAFT COMPLETE";
    turnBadge.className = "turn-badge waiting";
    heroWhy.textContent = "This draft has finished.";
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str == null ? "" : str;
    return div.innerHTML;
  }

  // ---- resume an already-running session on page load ----
  // A browser refresh (or a second tab) shouldn't restart the draft --
  // the manager is a single shared session (app/services/draft_live.py),
  // so check its status first and jump straight to the live screen if
  // one's already in progress, instead of always showing setup again.
  fetch("/api/live/status")
    .then(function (resp) { return resp.json(); })
    .then(function (snapshot) {
      if (snapshot.status && snapshot.status !== "idle") {
        enterScreen(snapshot);
        connectWebSocket();
      }
    })
    .catch(function () { /* fine -- just show setup as normal */ });
})();
