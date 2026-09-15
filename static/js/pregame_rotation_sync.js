// Single canonical pregame-rotation writer, shared by static/js/game_logic.js
// (which owns the inning-structure toolbar: Add/Remove/Clear Inning, Copy
// Previous, Paste, template load/apply, and the manual Save Rotation
// buttons) and static/js/live_game_board_prep.js (which owns the
// #pregame-defense-editor-v3 tap field). Both modules used to keep their
// own separate `state.rotation` copy and their own independent
// /save_rotation queue, so a field edit in one and, say, Add Another
// Inning in the other could race: whichever request finished last would
// overwrite the other's change with its own stale full-rotation snapshot.
//
// This store holds the one rotation object both modules read AND mutate
// in place (they hold the same reference, kept in sync via getRotation()),
// and the one save queue that builds every /save_rotation payload from
// that shared object at send time — so a payload always reflects every
// edit made by either module up to that moment, never a stale snapshot.
//
// This is pregame-only. Live play uses the server-authoritative
// /api/live-game/.../defense-edit path (Quick Field) and never touches
// this store.
window.CBPregameRotation = window.CBPregameRotation || (() => {
  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  const gameId = match ? Number(match[1]) : null;

  let rotation = null;

  // Bumped on every local edit from either module. lastSyncedRevision only
  // advances once a save covering that revision actually succeeds — never
  // on failure — so hasUnsyncedLocalState() stays true through a failed
  // save even after rotationSaveInProgress/pendingPayload both go idle.
  let localRevision = 0;
  let lastSyncedRevision = 0;

  let rotationSaveInProgress = false;
  let pendingPayload = null;
  let pendingRevision = null;
  let pendingIsManual = false;

  // localRevision/lastSyncedRevision alone only protect against a LOCAL
  // edit crossing a stale response — they never change when an accepted
  // SERVER snapshot is applied, so they cannot order two competing server
  // refreshes against each other. beginServerRefresh() hands out a
  // monotonically increasing token per attempted refresh (from either
  // module); lastAppliedRefreshToken remembers the newest one actually
  // applied, so a response whose refresh started before that no longer
  // wins even if every local-edit-safety check still passes.
  let refreshTokenCounter = 0;
  let lastAppliedRefreshToken = 0;

  let saveStatus = 'idle';
  let lastError = null;
  let statusResetTimer = null;

  const changeListeners = [];
  const statusListeners = [];

  function notifyChange() {
    changeListeners.forEach((fn) => {
      try { fn(); } catch (error) { console.error(error); }
    });
  }

  function notifyStatus(isManual) {
    statusListeners.forEach((fn) => {
      try { fn(saveStatus, lastError, Boolean(isManual)); } catch (error) { console.error(error); }
    });
  }

  function shapeInnings(innings) {
    if (typeof innings === 'string') {
      try { innings = JSON.parse(innings); } catch (_) { innings = {}; }
    }
    if (!innings || typeof innings !== 'object') innings = {};
    if (!Object.keys(innings).length) innings['1'] = {};
    return innings;
  }

  function ensure(defaultTitle) {
    if (!rotation) {
      rotation = {
        id: null,
        title: defaultTitle || 'Rotation',
        innings: {'1': {}},
        associated_game_id: gameId,
      };
    }
    rotation.innings = shapeInnings(rotation.innings);
    return rotation;
  }

  function hasUnsyncedLocalState() {
    return localRevision !== lastSyncedRevision;
  }

  function isSaveInFlightOrQueued() {
    return rotationSaveInProgress || pendingPayload !== null;
  }

  // Safe to call from any module's init or background-refresh path: a
  // server snapshot is only ever applied when nothing local is unsaved,
  // so it can never clobber a field edit or an inning-tool change made by
  // the other module (or this one) while the fetch was in flight.
  //
  // refreshToken is optional (the initial page-load hydration call has
  // none) — when given, it must be the value beginServerRefresh() handed
  // the caller for THIS refresh attempt, and only advances
  // lastAppliedRefreshToken forward, never backward, so a slower
  // in-flight refresh that started earlier can never re-apply after a
  // faster, later-started one already landed.
  function setFromServer(serverRotation, defaultTitle, refreshToken) {
    if (rotation && hasUnsyncedLocalState()) {
      return;
    }
    rotation = serverRotation ? {...serverRotation} : null;
    ensure(defaultTitle);
    if (refreshToken !== undefined && refreshToken > lastAppliedRefreshToken) {
      lastAppliedRefreshToken = refreshToken;
    }
    notifyChange();
  }

  function getRotation(defaultTitle) {
    return ensure(defaultTitle);
  }

  function setStatus(status, isManual) {
    saveStatus = status;
    if (statusResetTimer) {
      clearTimeout(statusResetTimer);
      statusResetTimer = null;
    }
    notifyStatus(isManual);

    if (status === 'saved') {
      statusResetTimer = setTimeout(() => {
        if (!isSaveInFlightOrQueued() && saveStatus === 'saved') {
          setStatus('idle', false);
        }
      }, 2000);
    }
    // 'failed' intentionally has no auto-hide timer: it stays visible and
    // retryable until a retry succeeds or a further edit re-queues a save.
  }

  function buildPayload(defaultTitle) {
    const current = ensure(defaultTitle);
    return {
      id: current.id,
      title: current.title || defaultTitle || 'Rotation',
      // Snapshot now so a later edit can't mutate an in-flight request.
      innings: JSON.parse(JSON.stringify(current.innings)),
      associated_game_id: gameId,
    };
  }

  async function flush() {
    if (rotationSaveInProgress || !pendingPayload) return;

    const payload = pendingPayload;
    const payloadRevision = pendingRevision;
    const payloadIsManual = pendingIsManual;
    pendingPayload = null;
    pendingRevision = null;
    pendingIsManual = false;
    rotationSaveInProgress = true;
    let succeeded = false;

    setStatus('saving', payloadIsManual);

    try {
      const response = await fetch('/save_rotation', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
        // Let Safari/iPad finish the request even if the coach navigates
        // away immediately after the edit.
        keepalive: true,
      });

      let result = {};
      try {
        result = await response.json();
      } catch (parseError) {
        throw new Error(`Save returned an invalid response (${response.status}).`);
      }

      // A malformed/empty HTTP 200 must fail closed, not be treated as a
      // silent success — only an explicit 'success' status counts.
      if (!response.ok || result.status !== 'success') {
        throw new Error(result.message || 'Failed to save rotation.');
      }

      if (result.new_id) {
        rotation.id = result.new_id;
        // If another edit queued a save while the first-ever rotation save
        // was still running, make sure it updates the newly-created
        // rotation instead of creating a duplicate.
        if (pendingPayload) pendingPayload.id = result.new_id;
      }

      succeeded = true;
      lastError = null;
    } catch (error) {
      lastError = error;
    } finally {
      rotationSaveInProgress = false;

      if (succeeded && payloadRevision > lastSyncedRevision) {
        lastSyncedRevision = payloadRevision;
      }

      if (pendingPayload) {
        // Another defensive/structural change happened during the
        // request (from either module); save the newest combined
        // snapshot next.
        void flush();
      } else if (succeeded) {
        setStatus('saved', payloadIsManual);
      } else {
        setStatus('failed', payloadIsManual);
      }
    }
  }

  function commitLocalChange(defaultTitle, isManual) {
    localRevision += 1;
    notifyChange();
    pendingPayload = buildPayload(defaultTitle);
    pendingRevision = localRevision;
    pendingIsManual = pendingIsManual || Boolean(isManual);
    lastError = null;
    void flush();
  }

  function retry(defaultTitle, isManual) {
    if (rotationSaveInProgress || pendingPayload) return;
    commitLocalChange(defaultTitle, isManual);
  }

  // refreshToken is optional for callers that only care about local-edit
  // safety (existing call sites that predate the token mechanism keep
  // working unchanged); pass the value beginServerRefresh() returned for
  // this refresh to ALSO reject a response whose refresh started before
  // one that has already been applied, even when every local-edit check
  // below passes.
  function canApplyRefresh(revisionAtStart, refreshToken) {
    if (
      rotationSaveInProgress ||
      pendingPayload ||
      localRevision !== revisionAtStart ||
      hasUnsyncedLocalState()
    ) {
      return false;
    }
    if (refreshToken !== undefined && refreshToken < lastAppliedRefreshToken) {
      return false;
    }
    return true;
  }

  // Call once, right before starting a server-refresh fetch (from either
  // module), and pass the returned token through to canApplyRefresh() and
  // setFromServer() when that fetch resolves. Tokens are handed out in
  // the exact order refreshes actually start, across both modules, so
  // whichever refresh's response is applied LAST (in start order) always
  // wins ordering — never whichever response merely ARRIVES last.
  function beginServerRefresh() {
    refreshTokenCounter += 1;
    return refreshTokenCounter;
  }

  return {
    gameId,
    setFromServer,
    getRotation,
    commitLocalChange,
    retry,
    hasUnsyncedLocalState,
    isSaveInFlightOrQueued,
    canApplyRefresh,
    beginServerRefresh,
    getLocalRevision: () => localRevision,
    getStatus: () => saveStatus,
    getLastError: () => lastError,
    onChange: (fn) => changeListeners.push(fn),
    onStatusChange: (fn) => statusListeners.push(fn),
  };
})();
