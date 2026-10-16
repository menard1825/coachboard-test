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

  // Two coaches, one plan. serverBase is the plan as stored on the server
  // that this page's rotation was built from; every save sends it as
  // base_innings, so the server can tell when another coach saved in
  // between. It then merges position by position, or refuses with
  // code 'rotation_conflict' (rotation_merge.py) -- never overwrites.
  // A refused save keeps this coach's changes on screen (unsynced) until
  // they choose: resolveConflict('theirs' | 'mine').
  let serverBase = null;
  let conflict = null;

  const changeListeners = [];
  const statusListeners = [];
  const conflictListeners = [];

  // info.source === 'server' when another coach's saved changes were just
  // brought into this page's plan (after a save that merged them).
  function notifyChange(info) {
    changeListeners.forEach((fn) => {
      try { fn(info || {}); } catch (error) { console.error(error); }
    });
  }

  function notifyConflict() {
    conflictListeners.forEach((fn) => {
      try { fn(conflict); } catch (error) { console.error(error); }
    });
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value || {}));
  }

  // The server's form of a plan (rotation_merge.normalize): open positions
  // left out, an inning with none kept.
  function normalize(innings) {
    const clean = {};
    Object.entries(innings || {}).forEach(([inning, alignment]) => {
      const positions = {};
      Object.entries(alignment && typeof alignment === 'object' ? alignment : {}).forEach(([pos, name]) => {
        const player = String(name ?? '').trim();
        if (player) positions[String(pos)] = player;
      });
      clean[String(inning)] = positions;
    });
    return clean;
  }

  function sameDeep(a, b) {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    if (ka.join('\u0000') !== kb.join('\u0000')) return false;
    return ka.every((key) => {
      const pa = a[key] || {};
      const pb = b[key] || {};
      const pka = Object.keys(pa).sort();
      return pka.join('\u0000') === Object.keys(pb).sort().join('\u0000') && pka.every((pos) => pa[pos] === pb[pos]);
    });
  }

  // Bring the other coach's saved changes into this page's plan, by the
  // server's rule (rotation_merge.py): a position only this coach changed
  // since `base` keeps this coach's player, a position only the other coach
  // changed takes theirs. Where both changed a position differently it is a
  // conflict: `prefer` ('mine' | 'theirs') decides it, or, without one, it
  // is reported and the other coach's player is used.
  // Returns {innings, conflicts}.
  function rebase(base, mine, theirs, prefer) {
    const b = normalize(base);
    const m = normalize(mine);
    const t = normalize(theirs);
    const innings = {};
    const conflicts = [];
    const pick = (mv, tv, inning, position) => {
      if (prefer === 'mine') return mv;
      if (prefer === 'theirs') return tv;
      conflicts.push({inning, position, yours: mv ?? null, theirs: tv ?? null});
      return tv;
    };
    new Set([...Object.keys(b), ...Object.keys(m), ...Object.keys(t)]).forEach((inning) => {
      const inBase = inning in b;
      const inMine = inning in m;
      const inTheirs = inning in t;
      const bi = b[inning] || {};
      const mi = m[inning] || {};
      const ti = t[inning] || {};
      const alignment = {};
      new Set([...Object.keys(bi), ...Object.keys(mi), ...Object.keys(ti)]).forEach((pos) => {
        const bv = bi[pos];
        const mv = mi[pos];
        const tv = ti[pos];
        let value;
        if (mv === bv) value = tv;
        else if (tv === bv || mv === tv) value = mv;
        else value = pick(mv, tv, inning, pos);
        if (value) alignment[pos] = value;
      });
      // An inning added or removed is a change of its own. Removing an
      // inning the other coach changed is a conflict.
      const mineChanged = inMine !== inBase || !sameDeep({x: mi}, {x: bi});
      const theirsChanged = inTheirs !== inBase || !sameDeep({x: ti}, {x: bi});
      let present = inMine !== inBase ? inMine : inTheirs;
      if (inMine !== inTheirs && mineChanged && theirsChanged) {
        present = Boolean(pick(inMine ? 'kept' : null, inTheirs ? 'kept' : null, inning, null));
      }
      if (present) innings[inning] = alignment;
    });
    return {innings, conflicts};
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
    serverBase = normalize(serverRotation ? shapeInnings(clone(serverRotation.innings)) : {});
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
      // The stored plan this one was built from (see serverBase).
      base_innings: clone(serverBase || {}),
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
    let mergedFromServer = false;

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

      if (response.status === 409 && result.code === 'rotation_conflict') {
        // Another coach changed the same positions. Nothing was saved; this
        // coach's changes stay on screen until they choose.
        conflict = {
          base: clone(payload.base_innings),
          theirs: normalize(result.innings),
          conflicts: Array.isArray(result.conflicts) ? result.conflicts : [],
          message: result.message,
        };
        const error = new Error(result.message || 'Another coach changed the same part of this defense.');
        error.code = 'rotation_conflict';
        error.conflicts = conflict.conflicts;
        throw error;
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

      if (result.innings && typeof result.innings === 'object') {
        // The plan as stored, which may include another coach's merged
        // changes: bring them in, keeping every edit made since this save
        // was sent, and start the next save from it.
        const stored = normalize(result.innings);
        if (!sameDeep(stored, normalize(payload.innings))) {
          const sent = normalize(payload.innings);
          const rebased = rebase(sent, rotation.innings, stored, null);
          if (rebased.conflicts.length) {
            // An edit made while this save was on its way touched a
            // position the other coach changed: ask, don't overwrite.
            conflict = {
              base: sent,
              theirs: stored,
              conflicts: rebased.conflicts,
              message: 'Another coach changed the same part of this defense. Your latest change wasn\u2019t saved yet.',
            };
          } else {
            rotation.innings = shapeInnings(rebased.innings);
            if (pendingPayload) {
              pendingPayload.innings = JSON.parse(JSON.stringify(rotation.innings));
            }
            mergedFromServer = true;
          }
        }
        serverBase = stored;
        if (pendingPayload) pendingPayload.base_innings = clone(stored);
      } else {
        serverBase = normalize(payload.innings);
        if (pendingPayload) pendingPayload.base_innings = clone(serverBase);
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
      if (mergedFromServer) notifyChange({source: 'server'});

      if (conflict) {
        // Hold the queue until the coach chooses; their edits stay local.
        if (!lastError) {
          lastError = new Error(conflict.message);
          lastError.code = 'rotation_conflict';
          lastError.conflicts = conflict.conflicts;
        }
        pendingPayload = null;
        pendingRevision = null;
        pendingIsManual = false;
        setStatus('failed', payloadIsManual);
        notifyConflict();
      } else if (pendingPayload) {
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
    if (conflict) {
      // Still waiting for the coach's choice: keep the edit, don't send it.
      notifyStatus(isManual);
      notifyConflict();
      return;
    }
    pendingPayload = buildPayload(defaultTitle);
    pendingRevision = localRevision;
    pendingIsManual = pendingIsManual || Boolean(isManual);
    lastError = null;
    void flush();
  }

  function retry(defaultTitle, isManual) {
    if (conflict) {
      // A retry would meet the same conflict: ask the coach instead.
      notifyConflict();
      return;
    }
    if (rotationSaveInProgress || pendingPayload) return;
    commitLocalChange(defaultTitle, isManual);
  }

  // The coach's answer to a conflict: 'theirs' takes the other coach's
  // player where both changed a position, 'mine' keeps this coach's. Every
  // other change from either coach is kept, and the result is saved.
  function resolveConflict(choice, defaultTitle) {
    if (!conflict || (choice !== 'theirs' && choice !== 'mine')) return;
    const current = ensure(defaultTitle);
    const {base, theirs} = conflict;
    current.innings = shapeInnings(rebase(base, current.innings, theirs, choice).innings);
    serverBase = clone(theirs);
    conflict = null;
    lastError = null;
    notifyChange({source: 'server'});
    if (sameDeep(normalize(current.innings), theirs)) {
      // Nothing of this coach's left to save.
      lastSyncedRevision = localRevision;
      setStatus('saved', true);
      return;
    }
    commitLocalChange(defaultTitle, true);
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
    getConflict: () => conflict,
    resolveConflict,
    onChange: (fn) => changeListeners.push(fn),
    onStatusChange: (fn) => statusListeners.push(fn),
    onConflict: (fn) => conflictListeners.push(fn),
  };
})();
