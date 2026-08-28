(function () {
  "use strict";

  // ---- CHUNK 53/54: app nav (section switcher + league switcher) + the
  // Draft Outlook view (Top Draft Score picks, per-league star targets,
  // pick-N board risk, full VBD board). Deliberately self-contained at the
  // top of the SAME file/IIFE rather than a new script: it only ever
  // touches its own elements (#section-live/#section-rankings/etc) and
  // never reaches into the live-draft refs or logic below this block.
  var navTabs = document.querySelectorAll(".nav-tab");
  var sectionLive = document.getElementById("section-live");
  var sectionRankings = document.getElementById("section-rankings");
  var sectionLineup = document.getElementById("section-lineup");
  var sectionTrade = document.getElementById("section-trade");
  var leagueButtons = document.querySelectorAll(".league-btn");
  var posFilterButtons = document.querySelectorAll(".pos-filter-btn");
  var rankingsList = document.getElementById("rankings-list");
  var rankingsError = document.getElementById("rankings-error");
  var rankingsLeagueKicker = document.getElementById("rankings-league-kicker");
  var outlookMySlotInput = document.getElementById("outlook-my-slot");
  var draftScoreList = document.getElementById("draft-score-list");
  var draftScoreError = document.getElementById("draft-score-error");
  var pickLookupInput = document.getElementById("pick-lookup-input");
  var pickLookupBtn = document.getElementById("pick-lookup-btn");
  var survivalList = document.getElementById("survival-list");
  var survivalError = document.getElementById("survival-error");

  // CHUNK 55 -- Lineup Optimizer refs
  var lineupLeagueKicker = document.getElementById("lineup-league-kicker");
  var lineupSearchInput = document.getElementById("lineup-search-input");
  var lineupSearchResults = document.getElementById("lineup-search-results");
  var lineupRosterList = document.getElementById("lineup-roster-list");
  var lineupRosterCount = document.getElementById("lineup-roster-count");
  var lineupOptimizeBtn = document.getElementById("lineup-optimize-btn");
  var lineupClearBtn = document.getElementById("lineup-clear-btn");
  var lineupRosterIdInput = document.getElementById("lineup-roster-id-input");
  var lineupLoadLiveBtn = document.getElementById("lineup-load-live-btn");
  var lineupError = document.getElementById("lineup-error");
  var lineupNote = document.getElementById("lineup-note");
  var lineupResultsBlock = document.getElementById("lineup-results-block");
  var lineupBenchBlock = document.getElementById("lineup-bench-block");
  var lineupStartersList = document.getElementById("lineup-starters-list");
  var lineupBenchList = document.getElementById("lineup-bench-list");

  // CHUNK 56 -- roster browser + Trade Suggester skeleton refs
  var tradeLeagueKicker = document.getElementById("trade-league-kicker");
  var tradeRosterSelect = document.getElementById("trade-roster-select");
  var tradeRosterError = document.getElementById("trade-roster-error");
  var tradeRosterViewList = document.getElementById("trade-roster-view-list");
  var tradeSearchInputs = { a: document.getElementById("trade-search-a"), b: document.getElementById("trade-search-b") };
  var tradeSearchResultsEls = { a: document.getElementById("trade-search-results-a"), b: document.getElementById("trade-search-results-b") };
  var tradeSideListEls = { a: document.getElementById("trade-side-a-list"), b: document.getElementById("trade-side-b-list") };
  var tradeSideVbdEls = { a: document.getElementById("trade-side-a-vbd"), b: document.getElementById("trade-side-b-vbd") };
  var tradeSideProjEls = { a: document.getElementById("trade-side-a-proj"), b: document.getElementById("trade-side-b-proj") };
  var tradeCompareBtn = document.getElementById("trade-compare-btn");
  var tradeClearBtn = document.getElementById("trade-clear-btn");
  var tradeError = document.getElementById("trade-error");
  var tradeResult = document.getElementById("trade-result");
  var tradeDifferentialText = document.getElementById("trade-differential-text");
  var tradeMethodNote = document.getElementById("trade-method-note");

  var LEAGUE_NAMES = { kiddos: "KIDDOS", former_bradley_bums: "FORMER BRADLEY BUMS" };
  var selectedLeagueKey = "kiddos";
  var selectedPosFilter = "";
  var rankingsLoadedOnce = false;
  var targetedIds = {}; // player_id -> true, for the CURRENT selectedLeagueKey only
  var lastSurvivalPickNo = null;
  var lineupPlayersCache = null; // full /api/rankings player list, cached for the search box (shared by Lineup AND Trade)
  var lineupRoster = []; // ordered list of {player_id, name, position, team} the user has added
  var tradeRostersData = null; // last /api/rosters response for the CURRENT selectedLeagueKey
  var tradeSides = { a: [], b: [] }; // ordered lists of {player_id, name, position, team}

  navTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      navTabs.forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      var section = tab.dataset.section;
      sectionLive.classList.toggle("hidden", section !== "live");
      sectionRankings.classList.toggle("hidden", section !== "rankings");
      sectionLineup.classList.toggle("hidden", section !== "lineup");
      sectionTrade.classList.toggle("hidden", section !== "trade");
      if (section === "rankings") {
        loadOutlook();
      } else if (section === "lineup") {
        lineupLeagueKicker.textContent = LEAGUE_NAMES[selectedLeagueKey] + " LEAGUE · LINEUP OPTIMIZER";
      } else if (section === "trade") {
        tradeLeagueKicker.textContent = LEAGUE_NAMES[selectedLeagueKey] + " LEAGUE · ROSTERS & TRADE";
        loadRosterBrowser();
      }
    });
  });

  leagueButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      leagueButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      selectedLeagueKey = btn.dataset.league;
      rankingsLeagueKicker.textContent = LEAGUE_NAMES[selectedLeagueKey] + " LEAGUE · DRAFT OUTLOOK";
      // NOTE: the league switcher only drives this Draft Outlook (planning)
      // section's fetches -- the Live Draft section (below) keeps using
      // the single active-league backend config throughout, unchanged
      // (Chunk 53 scope: live-draft-path stays out of per-request league
      // switching). Targets are ALSO per-league (Chunk 54) -- switching
      // leagues here re-fetches this league's own star list, never the
      // other league's.
      //
      // The survival (pick-N) panel is query-driven, not auto-refreshed on
      // every league switch -- reset it rather than leave a stale result
      // (including a stale star state) visibly attributed to the wrong
      // league until the next "Check the board" click.
      survivalList.innerHTML = '<li class="alt-empty">Enter a pick number and check the board.</li>';
      lastSurvivalPickNo = null;
      if (!sectionRankings.classList.contains("hidden")) loadOutlook();

      // Lineup tab (Chunk 55): the kicker follows the league switch; the
      // built roster is NOT cleared (it's just a list of player_ids the
      // user is trying out, not tied to league state), but the player
      // SEARCH cache is, since /api/rankings' player pool is echoed
      // per-league (identical today, but this stays correct if that ever
      // changes -- see _shared.py's Chunk 53 scope note).
      lineupLeagueKicker.textContent = LEAGUE_NAMES[selectedLeagueKey] + " LEAGUE · LINEUP OPTIMIZER";
      lineupPlayersCache = null;

      // Trade tab (Chunk 56): the roster browser is genuinely per-league
      // data (different rosters/owners) -- reload it if visible. The
      // trade-comparison sides are NOT cleared (same reasoning as
      // lineupRoster above: just a list of player_ids being tried out).
      tradeLeagueKicker.textContent = LEAGUE_NAMES[selectedLeagueKey] + " LEAGUE · ROSTERS & TRADE";
      tradeRostersData = null;
      if (!sectionTrade.classList.contains("hidden")) loadRosterBrowser();
    });
  });

  posFilterButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      posFilterButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      selectedPosFilter = btn.dataset.pos || "";
      fetchRankings();
    });
  });

  outlookMySlotInput.addEventListener("change", function () {
    fetchDraftScore();
  });

  pickLookupBtn.addEventListener("click", function () {
    fetchSurvival();
  });

  function loadOutlook() {
    fetchTargets().then(function () {
      fetchRankings();
      fetchDraftScore();
    });
  }

  // ---- per-league star/target persistence (Chunk 54, app/routers/targets.py) ----

  function fetchTargets() {
    return fetch("/api/targets?league_key=" + encodeURIComponent(selectedLeagueKey))
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        targetedIds = {};
        (data.player_ids || []).forEach(function (pid) { targetedIds[pid] = true; });
      })
      .catch(function () { targetedIds = {}; });
  }

  function toggleTarget(playerId, btn) {
    var isTargeted = !!targetedIds[playerId];
    var req = isTargeted
      ? fetch("/api/targets/" + encodeURIComponent(playerId) + "?league_key=" + encodeURIComponent(selectedLeagueKey), { method: "DELETE" })
      : fetch("/api/targets", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: playerId, league_key: selectedLeagueKey }),
        });
    req.then(function (resp) { return resp.json(); })
      .then(function () {
        targetedIds[playerId] = !isTargeted;
        // Re-render every visible list so the star state stays consistent
        // across the Draft Score panel, the survival panel, and the full
        // VBD board -- the same player can appear in all three.
        document.querySelectorAll('.star-btn[data-player-id="' + playerId + '"]').forEach(function (b) {
          b.classList.toggle("active", !isTargeted);
          b.textContent = !isTargeted ? "★" : "☆";
        });
      })
      .catch(function () { /* leave UI state as-is on failure */ });
  }

  function starButtonHtml(playerId) {
    var active = !!targetedIds[playerId];
    return '<button class="star-btn' + (active ? " active" : "") + '" data-player-id="' + playerId + '" title="Target this player" type="button">' + (active ? "★" : "☆") + "</button>";
  }

  function wireStarButtons(container) {
    container.querySelectorAll(".star-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        toggleTarget(btn.dataset.playerId, btn);
      });
    });
  }

  // ---- full VBD board (Chunk 53, unchanged math -- app/routers/rankings.py) ----

  function fetchRankings() {
    rankingsError.classList.add("hidden");
    var requestedLeagueKey = selectedLeagueKey; // see fetchSurvival's identical stale-response note
    var params = new URLSearchParams({ league_key: requestedLeagueKey });
    if (selectedPosFilter) params.set("position", selectedPosFilter);
    if (!rankingsLoadedOnce) {
      rankingsList.innerHTML = '<li class="alt-empty">Loading…</li>';
    }
    fetch("/api/rankings?" + params.toString())
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        if (data.error) {
          rankingsError.textContent = data.error;
          rankingsError.classList.remove("hidden");
          rankingsList.innerHTML = "";
          return;
        }
        rankingsLoadedOnce = true;
        renderRankings(data.players || []);
      })
      .catch(function (err) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        rankingsError.textContent = err.message || "Could not load rankings.";
        rankingsError.classList.remove("hidden");
      });
  }

  function renderRankings(players) {
    if (!players.length) {
      rankingsList.innerHTML = '<li class="alt-empty">No players.</li>';
      return;
    }
    rankingsList.innerHTML = players.slice(0, 60).map(function (p, i) {
      return (
        '<li class="ranking-row">' +
        '<span class="ranking-rank">' + (i + 1) + "</span>" +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<span class="ranking-vbd">' + Math.round(p.vbd).toLocaleString() + "</span>" +
        starButtonHtml(p.player_id) +
        "</li>"
      );
    }).join("");
    wireStarButtons(rankingsList);
  }

  // ---- Top Draft Score picks (Chunk 54 -- real MCTS engine, app/routers/mcts.py) ----

  function fetchDraftScore() {
    draftScoreError.classList.add("hidden");
    draftScoreList.innerHTML = '<li class="alt-empty">Running the Draft Score engine…</li>';
    var mySlot = parseInt(outlookMySlotInput.value, 10) || 1;
    var requestedLeagueKey = selectedLeagueKey; // see fetchSurvival's identical stale-response note
    var params = new URLSearchParams({ my_slot: String(mySlot), league_key: requestedLeagueKey, top_n: "12" });
    fetch("/api/outlook/top-picks?" + params.toString())
      .then(function (resp) {
        if (!resp.ok) return resp.json().then(function (b) { throw new Error(b.detail || "Request failed"); });
        return resp.json();
      })
      .then(function (data) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        if (data.note) {
          draftScoreError.textContent = data.note;
          draftScoreError.classList.remove("hidden");
          draftScoreError.classList.add("outlook-note");
        } else {
          draftScoreError.classList.remove("outlook-note");
        }
        renderDraftScore((data.recommendations || []));
      })
      .catch(function (err) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        draftScoreError.textContent = err.message || "Could not run the Draft Score engine.";
        draftScoreError.classList.remove("hidden");
        draftScoreError.classList.remove("outlook-note");
        draftScoreList.innerHTML = "";
      });
  }

  function renderDraftScore(recs) {
    if (!recs.length) {
      draftScoreList.innerHTML = '<li class="alt-empty">No recommendations.</li>';
      return;
    }
    draftScoreList.innerHTML = recs.map(function (p, i) {
      return (
        '<li class="ranking-row">' +
        '<span class="ranking-rank">' + (i + 1) + "</span>" +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<span class="ranking-score">' + Math.round(p.mcts_score).toLocaleString() + "</span>" +
        starButtonHtml(p.player_id) +
        "</li>"
      );
    }).join("");
    wireStarButtons(draftScoreList);
  }

  // ---- Likely available at pick N (Chunk 54 -- app/services/survival.py reuse) ----

  function fetchSurvival() {
    survivalError.classList.add("hidden");
    var pickNo = parseInt(pickLookupInput.value, 10);
    if (!pickNo || pickNo < 1) {
      survivalError.textContent = "Enter a valid pick number.";
      survivalError.classList.remove("hidden");
      return;
    }
    lastSurvivalPickNo = pickNo;
    // Captured at fetch-start -- a slow request from a league the user has
    // since switched AWAY from must not clobber the newly-selected league's
    // (possibly already-reset) panel when it finally resolves.
    var requestedLeagueKey = selectedLeagueKey;
    survivalList.innerHTML = '<li class="alt-empty">Simulating the board…</li>';
    var params = new URLSearchParams({ league_key: requestedLeagueKey, pick_no: String(pickNo), top_n: "30" });
    fetch("/api/outlook/survival?" + params.toString())
      .then(function (resp) {
        if (!resp.ok) return resp.json().then(function (b) { throw new Error(b.detail || "Request failed"); });
        return resp.json();
      })
      .then(function (data) {
        if (requestedLeagueKey !== selectedLeagueKey) return; // stale -- league changed while this was in flight
        renderSurvival(data.players || [], data.pick_no);
      })
      .catch(function (err) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        survivalError.textContent = err.message || "Could not estimate board risk.";
        survivalError.classList.remove("hidden");
        survivalList.innerHTML = "";
      });
  }

  function renderSurvival(players, pickNo) {
    if (!players.length) {
      survivalList.innerHTML = '<li class="alt-empty">No players.</li>';
      return;
    }
    survivalList.innerHTML = players.map(function (p) {
      var pct = Math.round(p.survival_probability * 100);
      var riskClass = pct >= 66 ? "risk-low" : pct >= 33 ? "risk-mid" : "risk-high";
      var adp = p.market_adp != null ? p.market_adp.toFixed(1) : "—";
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="survival-adp">ADP ' + adp + "</span>" +
        '<span class="survival-pct ' + riskClass + '">' + pct + "%</span>" +
        starButtonHtml(p.player_id) +
        "</li>"
      );
    }).join("");
    wireStarButtons(survivalList);
  }

  // ---- Lineup Optimizer (Chunk 55 -- app/routers/lineup.py) ----

  lineupSearchInput.addEventListener("input", function () {
    var query = lineupSearchInput.value.trim().toLowerCase();
    if (!query) {
      lineupSearchResults.classList.add("hidden");
      lineupSearchResults.innerHTML = "";
      return;
    }
    ensureLineupPlayersLoaded().then(function () {
      var matches = lineupPlayersCache
        .filter(function (p) { return p.name && p.name.toLowerCase().indexOf(query) !== -1; })
        .slice(0, 12);
      renderLineupSearchResults(matches);
    });
  });

  lineupClearBtn.addEventListener("click", function () {
    lineupRoster = [];
    renderLineupRoster();
    hideLineupResults();
  });

  lineupOptimizeBtn.addEventListener("click", function () {
    optimizeLineup({ player_ids: lineupRoster.map(function (p) { return p.player_id; }), league_key: selectedLeagueKey });
  });

  lineupLoadLiveBtn.addEventListener("click", function () {
    var rosterId = parseInt(lineupRosterIdInput.value, 10);
    if (!rosterId || rosterId < 1) {
      showLineupError("Enter a valid roster_id.");
      return;
    }
    optimizeLineup({ use_live_roster: true, roster_id: rosterId, league_key: selectedLeagueKey });
  });

  function ensureLineupPlayersLoaded() {
    if (lineupPlayersCache) return Promise.resolve();
    var params = new URLSearchParams({ league_key: selectedLeagueKey });
    return fetch("/api/rankings?" + params.toString())
      .then(function (resp) { return resp.json(); })
      .then(function (data) { lineupPlayersCache = data.players || []; });
  }

  function renderLineupSearchResults(matches) {
    if (!matches.length) {
      lineupSearchResults.innerHTML = '<li class="alt-empty">No matches.</li>';
      lineupSearchResults.classList.remove("hidden");
      return;
    }
    var rosterIds = {};
    lineupRoster.forEach(function (p) { rosterIds[p.player_id] = true; });
    lineupSearchResults.innerHTML = matches.map(function (p) {
      var already = !!rosterIds[p.player_id];
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<button class="add-btn" data-player-id="' + p.player_id + '" type="button"' + (already ? " disabled" : "") + ">" +
        (already ? "Added" : "+ Add") +
        "</button></li>"
      );
    }).join("");
    lineupSearchResults.classList.remove("hidden");
    lineupSearchResults.querySelectorAll(".add-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var player = lineupPlayersCache.find(function (p) { return p.player_id === btn.dataset.playerId; });
        if (player) addToLineupRoster(player);
      });
    });
  }

  function addToLineupRoster(player) {
    if (lineupRoster.some(function (p) { return p.player_id === player.player_id; })) return;
    lineupRoster.push({ player_id: player.player_id, name: player.name, position: player.position, team: player.team });
    renderLineupRoster();
    // Refresh the search results' "Added" state without re-querying.
    var query = lineupSearchInput.value.trim().toLowerCase();
    if (query) {
      var matches = lineupPlayersCache.filter(function (p) { return p.name && p.name.toLowerCase().indexOf(query) !== -1; }).slice(0, 12);
      renderLineupSearchResults(matches);
    }
  }

  function removeFromLineupRoster(playerId) {
    lineupRoster = lineupRoster.filter(function (p) { return p.player_id !== playerId; });
    renderLineupRoster();
  }

  function renderLineupRoster() {
    lineupRosterCount.textContent = String(lineupRoster.length);
    if (!lineupRoster.length) {
      lineupRosterList.innerHTML = '<li class="alt-empty">No players added yet.</li>';
      return;
    }
    lineupRosterList.innerHTML = lineupRoster.map(function (p) {
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<button class="remove-btn" data-player-id="' + p.player_id + '" type="button">Remove</button>' +
        "</li>"
      );
    }).join("");
    lineupRosterList.querySelectorAll(".remove-btn").forEach(function (btn) {
      btn.addEventListener("click", function () { removeFromLineupRoster(btn.dataset.playerId); });
    });
  }

  function showLineupError(msg) {
    lineupError.textContent = msg;
    lineupError.classList.remove("hidden");
  }

  function hideLineupResults() {
    lineupError.classList.add("hidden");
    lineupNote.classList.add("hidden");
    lineupResultsBlock.classList.add("hidden");
    lineupBenchBlock.classList.add("hidden");
  }

  function optimizeLineup(body) {
    lineupError.classList.add("hidden");
    lineupNote.classList.add("hidden");
    fetch("/api/lineup/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        if (!resp.ok) return resp.json().then(function (b) { throw new Error(b.detail || "Request failed"); });
        return resp.json();
      })
      .then(function (data) {
        if (data.note) {
          lineupNote.textContent = data.note;
          lineupNote.classList.remove("hidden");
        }
        renderLineupResults(data.starters || [], data.bench || []);
      })
      .catch(function (err) {
        showLineupError(err.message || "Could not optimize this roster.");
        lineupResultsBlock.classList.add("hidden");
        lineupBenchBlock.classList.add("hidden");
      });
  }

  function lineupRowHtml(p) {
    var injuryBadge = p.injury_status ? '<span class="injury-badge">' + escapeHtmlTop(p.injury_status) + "</span>" : "";
    return (
      '<li class="ranking-row">' +
      '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
      '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
      '<span class="ranking-team">' + (p.team || "") + "</span>" +
      '<span class="ranking-vbd">' + (p.projected_points != null ? Math.round(p.projected_points) : "—") + "</span>" +
      injuryBadge +
      "</li>"
    );
  }

  function renderLineupResults(starters, bench) {
    if (!starters.length && !bench.length) {
      lineupResultsBlock.classList.add("hidden");
      lineupBenchBlock.classList.add("hidden");
      return;
    }
    lineupStartersList.innerHTML = starters.length
      ? starters.map(lineupRowHtml).join("")
      : '<li class="alt-empty">No starters.</li>';
    lineupBenchList.innerHTML = bench.length
      ? bench.map(lineupRowHtml).join("")
      : '<li class="alt-empty">Empty bench.</li>';
    lineupResultsBlock.classList.remove("hidden");
    lineupBenchBlock.classList.remove("hidden");
  }

  // ---- Roster Browser (Chunk 56 Task 3, app/routers/rosters.py) ----

  function loadRosterBrowser() {
    tradeRosterError.classList.add("hidden");
    tradeRosterViewList.innerHTML = '<li class="alt-empty">Loading rosters…</li>';
    var requestedLeagueKey = selectedLeagueKey; // see fetchSurvival's stale-response note (Chunk 54) -- same pattern
    var params = new URLSearchParams({ league_key: requestedLeagueKey });
    fetch("/api/rosters?" + params.toString())
      .then(function (resp) {
        if (!resp.ok) return resp.json().then(function (b) { throw new Error(b.detail || "Request failed"); });
        return resp.json();
      })
      .then(function (data) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        tradeRostersData = data;
        populateRosterSelect(data);
        renderRosterView(tradeRosterSelect.value);
      })
      .catch(function (err) {
        if (requestedLeagueKey !== selectedLeagueKey) return;
        tradeRosterError.textContent = err.message || "Could not load rosters.";
        tradeRosterError.classList.remove("hidden");
        tradeRosterViewList.innerHTML = "";
      });
  }

  function populateRosterSelect(data) {
    tradeRosterSelect.innerHTML = data.rosters.map(function (r) {
      var label = r.team_name + (r.is_mine ? " (You)" : "") + " -- " + r.player_count + " players";
      return '<option value="' + r.roster_id + '">' + escapeHtmlTop(label) + "</option>";
    }).join("");
  }

  tradeRosterSelect.addEventListener("change", function () {
    renderRosterView(tradeRosterSelect.value);
  });

  function renderRosterView(rosterId) {
    if (!tradeRostersData) return;
    var roster = tradeRostersData.rosters.find(function (r) { return String(r.roster_id) === String(rosterId); });
    if (!roster) {
      tradeRosterViewList.innerHTML = '<li class="alt-empty">No roster selected.</li>';
      return;
    }
    if (!roster.players.length) {
      tradeRosterViewList.innerHTML = '<li class="alt-empty">' + (roster.is_mine ? "Your" : "This") + " roster has no players yet (pre-draft).</li>";
      return;
    }
    tradeRosterViewList.innerHTML = roster.players.map(function (p) {
      var mineBadge = roster.is_mine ? '<span class="mine-badge">YOU</span>' : "";
      var injuryBadge = p.injury_status ? '<span class="injury-badge">' + escapeHtmlTop(p.injury_status) + "</span>" : "";
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + (p.position || "") + '">' + (p.position || "?") + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name || p.player_id) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<span class="ranking-vbd">' + (p.projected_points != null ? Math.round(p.projected_points) : "—") + "</span>" +
        injuryBadge + mineBadge +
        "</li>"
      );
    }).join("");
  }

  // ---- Trade Suggester SKELETON (Chunk 56 Task 4, app/routers/trade.py) --
  // Two independent search-and-add sides (reusing Lineup's exact
  // search/add/remove pattern, and its SAME lineupPlayersCache/
  // ensureLineupPlayersLoaded -- one shared player-search cache per
  // league, not fetched twice for two different tabs) + a raw VBD/points
  // comparison. Deliberately not roster-aware and not any smarter than
  // that -- see trade.py's module docstring.

  ["a", "b"].forEach(function (side) {
    tradeSearchInputs[side].addEventListener("input", function () {
      var query = tradeSearchInputs[side].value.trim().toLowerCase();
      if (!query) {
        tradeSearchResultsEls[side].classList.add("hidden");
        tradeSearchResultsEls[side].innerHTML = "";
        return;
      }
      ensureLineupPlayersLoaded().then(function () {
        var matches = lineupPlayersCache
          .filter(function (p) { return p.name && p.name.toLowerCase().indexOf(query) !== -1; })
          .slice(0, 12);
        renderTradeSearchResults(side, matches);
      });
    });
  });

  function renderTradeSearchResults(side, matches) {
    var container = tradeSearchResultsEls[side];
    if (!matches.length) {
      container.innerHTML = '<li class="alt-empty">No matches.</li>';
      container.classList.remove("hidden");
      return;
    }
    var sideIds = {};
    tradeSides[side].forEach(function (p) { sideIds[p.player_id] = true; });
    container.innerHTML = matches.map(function (p) {
      var already = !!sideIds[p.player_id];
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<button class="add-btn" data-player-id="' + p.player_id + '" data-side="' + side + '" type="button"' + (already ? " disabled" : "") + ">" +
        (already ? "Added" : "+ Add") +
        "</button></li>"
      );
    }).join("");
    container.classList.remove("hidden");
    container.querySelectorAll(".add-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var player = lineupPlayersCache.find(function (p) { return p.player_id === btn.dataset.playerId; });
        if (player) addToTradeSide(btn.dataset.side, player);
      });
    });
  }

  function addToTradeSide(side, player) {
    if (tradeSides[side].some(function (p) { return p.player_id === player.player_id; })) return;
    tradeSides[side].push({ player_id: player.player_id, name: player.name, position: player.position, team: player.team });
    renderTradeSide(side);
    var query = tradeSearchInputs[side].value.trim().toLowerCase();
    if (query) {
      var matches = lineupPlayersCache.filter(function (p) { return p.name && p.name.toLowerCase().indexOf(query) !== -1; }).slice(0, 12);
      renderTradeSearchResults(side, matches);
    }
  }

  function removeFromTradeSide(side, playerId) {
    tradeSides[side] = tradeSides[side].filter(function (p) { return p.player_id !== playerId; });
    renderTradeSide(side);
  }

  function renderTradeSide(side) {
    var list = tradeSideListEls[side];
    if (!tradeSides[side].length) {
      list.innerHTML = '<li class="alt-empty">No players added.</li>';
      return;
    }
    list.innerHTML = tradeSides[side].map(function (p) {
      return (
        '<li class="ranking-row">' +
        '<span class="pos-pill pos-' + p.position + '">' + p.position + "</span>" +
        '<span class="ranking-name">' + escapeHtmlTop(p.name) + "</span>" +
        '<span class="ranking-team">' + (p.team || "") + "</span>" +
        '<button class="remove-btn" data-player-id="' + p.player_id + '" data-side="' + side + '" type="button">Remove</button>' +
        "</li>"
      );
    }).join("");
    list.querySelectorAll(".remove-btn").forEach(function (btn) {
      btn.addEventListener("click", function () { removeFromTradeSide(btn.dataset.side, btn.dataset.playerId); });
    });
  }

  tradeClearBtn.addEventListener("click", function () {
    tradeSides = { a: [], b: [] };
    renderTradeSide("a");
    renderTradeSide("b");
    tradeResult.classList.add("hidden");
    tradeError.classList.add("hidden");
    tradeSideVbdEls.a.textContent = "0";
    tradeSideProjEls.a.textContent = "0";
    tradeSideVbdEls.b.textContent = "0";
    tradeSideProjEls.b.textContent = "0";
  });

  tradeCompareBtn.addEventListener("click", function () {
    tradeError.classList.add("hidden");
    var body = {
      league_key: selectedLeagueKey,
      side_a_player_ids: tradeSides.a.map(function (p) { return p.player_id; }),
      side_b_player_ids: tradeSides.b.map(function (p) { return p.player_id; }),
    };
    fetch("/api/trade/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        if (!resp.ok) return resp.json().then(function (b) { throw new Error(b.detail || "Request failed"); });
        return resp.json();
      })
      .then(function (data) {
        tradeSideVbdEls.a.textContent = data.side_a.total_vbd;
        tradeSideProjEls.a.textContent = data.side_a.total_projected_points;
        tradeSideVbdEls.b.textContent = data.side_b.total_vbd;
        tradeSideProjEls.b.textContent = data.side_b.total_projected_points;

        // vbd_differential = (value given up) - (value received). Framed
        // in "you give / you receive" terms to match the UI's own labels,
        // not "Side A/Side B" jargon.
        var diff = data.vbd_differential;
        var diffText;
        if (diff > 0.05) {
          diffText = 'You give up <span class="favor-b">' + diff.toFixed(1) + " more raw VBD</span> than you receive -- favors the other side.";
        } else if (diff < -0.05) {
          diffText = 'You receive <span class="favor-a">' + Math.abs(diff).toFixed(1) + " more raw VBD</span> than you give up -- favors you.";
        } else {
          diffText = "Dead even on raw VBD.";
        }
        tradeDifferentialText.innerHTML = diffText;
        tradeMethodNote.textContent = data.method_note;
        tradeResult.classList.remove("hidden");
      })
      .catch(function (err) {
        tradeError.textContent = err.message || "Could not compare this trade.";
        tradeError.classList.remove("hidden");
        tradeResult.classList.add("hidden");
      });
  });

  function escapeHtmlTop(str) {
    var div = document.createElement("div");
    div.textContent = str == null ? "" : str;
    return div.innerHTML;
  }

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
