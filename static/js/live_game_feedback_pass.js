(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const nativeFetch = window.fetch.bind(window);
  const stateUrl = `/api/live-game/${gameId}/state`;
  let state = null;
  let stateLoadedAt = 0;
  let lastSequence = 0;
  let socketHealthy = false;
  let renderQueued = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installSharedGameModalStyles() {
    if (document.getElementById('cb-live-state-sync-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-live-state-sync-styles';
    style.textContent = `
      .modal .modal-header .btn-close{width:46px!important;height:46px!important;min-width:46px!important;min-height:46px!important;padding:0!important;margin:-6px -6px -6px 8px!important;border-radius:12px!important;background-size:14px 14px!important;opacity:.72;touch-action:manipulation}
      .modal .modal-header .btn-close:active{background-color:rgba(0,0,0,.08)}
    `;
    document.head.appendChild(style);
  }

  let stateInflight = null;
  let stateInflightUntil = 0;

  // Every /state the page reads -- the polls, Undo, End Inning, a
  // reconnect -- is the game as the server has it. A read newer than the
  // state this page shows becomes it, and is published (coachboard:live-
  // state) so the header, tabs and action labels move together; an older
  // one (sent before a change that has since landed) is ignored.
  // init.cbCarrier: loadState below, which publishes its own read.
  function shareRead(promise, init) {
    if (init?.cbCarrier) return;
    promise.then(response => {
      if (!response.ok) return;
      response.clone().json().then(data => {
        // After the caller's own handling, which may publish it first.
        window.setTimeout(() => adoptRead(data, 'read'), 0);
      }, () => {});
    }, () => {});
  }

  window.fetch = function(input, init = {}) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    const isState = method === 'GET' && url && new URL(url, window.location.href).pathname === stateUrl;
    // init.cbFresh: the caller needs a read that starts now (End Inning).
    if (isState && !init?.cbFresh) {
      const now = Date.now();
      if (stateInflight && now < stateInflightUntil) return stateInflight.then(response => response.clone());
      const promise = nativeFetch(input, init);
      stateInflight = promise;
      stateInflightUntil = now + 500;
      window.setTimeout(() => {
        if (stateInflight === promise) {
          stateInflight = null;
          stateInflightUntil = 0;
        }
      }, 550);
      shareRead(promise, init);
      return promise.then(response => response.clone());
    }
    const result = nativeFetch(input, init);
    if (isState) shareRead(result, init);
    return result;
  };

  // How far along the game's history a state is. Every live write adds an
  // event (a higher sequence) or reverts one (Undo), so this only grows --
  // unlike the highest unreverted sequence, which an Undo lowers.
  function liveVersion(value) {
    const events = Array.isArray(value?.rotation_events) ? value.rotation_events : [];
    let high = 0;
    let reverted = 0;
    events.forEach(event => {
      high = Math.max(high, Number(event?.sequence) || 0);
      if (event?.reverted) reverted += 1;
    });
    return [high, reverted];
  }

  function compareVersions(a, b) {
    return (a[0] - b[0]) || (a[1] - b[1]);
  }

  function isOlder(next) {
    return Boolean(state?.rotation_events) && compareVersions(liveVersion(next), liveVersion(state)) < 0;
  }

  function publishState(data, source) {
    document.dispatchEvent(
      new CustomEvent('coachboard:live-state', {
        detail: {
          game_id: gameId,
          state: data,
          source,
        },
      })
    );
  }

  // A read made elsewhere on the page: adopt and publish it if it is newer
  // than what this page shows (or shows another inning).
  function adoptRead(data, source) {
    if (!data || Number(data?.game?.id) !== gameId) return false;
    // Going live or ending is live_game_v2.js's to show (its lifecycle,
    // with the slow check in live_game_postgame_cleanup.js when there is no
    // socket); a read that crosses it is left to them.
    if (Boolean(data?.game?.is_live) !== Boolean(state?.game?.is_live)) return false;
    const newer = !state?.rotation_events ||
      compareVersions(liveVersion(data), liveVersion(state)) > 0 ||
      (!isOlder(data) && String(data.current_inning || '') !== String(state.current_inning || ''));
    if (!newer) return false;
    state = data;
    stateLoadedAt = Date.now();
    lastSequence = sequenceFromState(data);
    queuePatch();
    publishState(data, source);
    return true;
  }

  function sequenceFromState(value = state) {
    const events = Array.isArray(value?.rotation_events) ? value.rotation_events : [];
    return events.reduce((max, event) => event?.reverted ? max : Math.max(max, Number(event?.sequence) || 0), 0);
  }

  function positions() {
    return Number(state?.outfielder_count) === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function playerByName(name) {
    return (state?.roster || []).find(player => player.name === name) || null;
  }

  function playerLabel(name) {
    const player = playerByName(name);
    if (!player) return name || 'Open';
    const number = String(player.number ?? '').trim();
    return number ? `#${number} ${player.name}` : player.name;
  }

  async function loadState(
    force = false,
    source = 'state-load',
    {fresh = false} = {}
  ) {
    if (!force && state && (socketHealthy || Date.now() - stateLoadedAt < 15000)) return state;
    const response = await window.fetch(stateUrl, {cache:'no-store', cbCarrier: true, ...(fresh ? {cbFresh: true} : {})});
    if (!response.ok) return state;
    const data = await response.json().catch(() => null);
    if (!data) return state;
    // A read sent before a change that has since landed is older than what
    // the page shows: keep the newer state.
    if (isOlder(data)) return state;
    state = data;
    stateLoadedAt = Date.now();
    lastSequence = sequenceFromState(data);

    queuePatch();
    publishState(data, source);

    return state;
  }

  // The live state this page shows, for scripts that label or act on it.
  window.CBLiveState = Object.freeze({
    current: () => state,
    // A new read (never one already in the air), published if newer.
    refresh: source => loadState(true, source || 'refresh', {fresh: true}),
    // A read the caller made itself: adopted and published if newer.
    adopt: (data, source) => adoptRead(data, source || 'read'),
  });

  // Each live change is handled once, whichever copy arrives first: the
  // Socket.IO broadcast, or the same delta from this page's own write
  // response (End Inning, Change Pitcher, a drag), published as
  // coachboard:live-delta. The page's own changes then show even while the
  // live connection is down.
  const handledDeltas = new Set();
  let publishing = false;

  function deltaKey(delta) {
    const sequence = Number(delta.sequence) || 0;
    if (!sequence) return '';
    return `${sequence}:${Number(delta.event?.id) || 0}:${delta.current_inning || ''}`;
  }

  function applyDelta(delta, {fromPage = false} = {}) {
    if (!delta || Number(delta.game_id) !== gameId) return;

    const incomingEventId =
      Number(delta.event?.id) || 0;

    const incomingSequence =
      Number(delta.event?.sequence) ||
      Number(delta.sequence) ||
      0;

    const matchesRevertedEvent =
      Array.isArray(state?.rotation_events) &&
      state.rotation_events.some(existing => {
        if (!existing?.reverted) return false;

        const existingId =
          Number(existing?.id) || 0;

        const existingSequence =
          Number(existing?.sequence) || 0;

        if (
          incomingEventId &&
          existingId === incomingEventId
        ) {
          return true;
        }

        if (
          !incomingEventId &&
          incomingSequence &&
          existingSequence === incomingSequence
        ) {
          return true;
        }

        return false;
      });

    if (matchesRevertedEvent) {
      return;
    }

    const sequence = Number(delta.sequence) || 0;
    if (sequence && sequence < lastSequence) return;

    const key = deltaKey(delta);
    if (key) {
      if (handledDeltas.has(key)) return;
      handledDeltas.add(key);
      if (handledDeltas.size > 100) handledDeltas.delete(handledDeltas.values().next().value);
    }

    /*
     * A live delta proves that any /state GET which began before this
     * delta may describe an older live-game version.
     *
     * Do not let later callers (notably Quick Field drag/drop) reuse
     * that older in-flight response. The original request may finish
     * normally for its original consumer; new callers must perform a
     * fresh authoritative GET.
     */
    stateInflight = null;
    stateInflightUntil = 0;

    if (
      sequence &&
      lastSequence &&
      sequence > lastSequence + 1
    ) {
      loadState(true, 'sequence-gap').catch(() => {});
    }
    lastSequence = Math.max(lastSequence, sequence);

    if (!state) state = {game:{id:gameId,is_live:true}, roster:[], actual_rotation:{}, rotation_events:[]};
    if (!state.game) state.game = {id:gameId,is_live:true};
    state.game.is_live = true;
    state.game.live_current_inning = String(delta.current_inning || state.game.live_current_inning || '1');
    state.current_inning = String(delta.current_inning || state.current_inning || '1');
    state.current_alignment = {...(delta.current_alignment || {})};
    state.current_pitcher = delta.current_pitcher || state.current_alignment.P || null;
    state.actual_rotation = state.actual_rotation || {};
    state.actual_rotation[state.current_inning] = {...state.current_alignment};
    if (Array.isArray(delta.bench)) state.bench = delta.bench;
    if (delta.event) {
      state.rotation_events = Array.isArray(state.rotation_events) ? state.rotation_events : [];
      const index = state.rotation_events.findIndex(event => Number(event.id) === Number(delta.event.id));
      if (index >= 0) state.rotation_events[index] = delta.event;
      else state.rotation_events.push(delta.event);
    }
    stateLoadedAt = Date.now();
    queuePatch();
    // A delta from this page was already published to every listener.
    if (!fromPage) {
      publishing = true;
      try {
        document.dispatchEvent(new CustomEvent('coachboard:live-delta', {detail:delta}));
      } finally {
        publishing = false;
      }
    }

    // A delta carries the field, not pitching eligibility. After a pitcher
    // leaves the mound (a pitching change, or a new pitcher at End Inning)
    // read the full state once so every screen knows who may not return.
    const type = delta.event?.event_type;
    if (type === 'Pitcher Change' || type === 'End Inning') {
      loadState(true, 'pitching-change').catch(() => {});
    }
  }

  document.addEventListener('coachboard:live-delta', event => {
    if (!publishing) applyDelta(event.detail, {fromPage: true});
  });

  function wireSocket(socket) {
    if (!socket || socket.__cbStateSyncWired) return socket;
    socket.__cbStateSyncWired = true;
    socket.on?.('connect', () => {
      const source = socket.__cbConnectedOnce
        ? 'socket-reconnect'
        : 'socket-connect';

      socket.__cbConnectedOnce = true;
      socketHealthy = true;

      // A reconnect can miss every delta that occurred while the
      // browser had no network. Always pull the complete current
      // game state rather than trusting the old in-memory lineup.
      loadState(true, source).catch(() => {});
    });

    socket.on?.('disconnect', () => {
      socketHealthy = false;
    });
    socket.on?.('live_game_delta', applyDelta);
    return socket;
  }

  function wrapIo(factory) {
    if (typeof factory !== 'function' || factory.__cbStateSyncWrapped) return factory;
    const wrapped = function(...args) { return wireSocket(factory.apply(this, args)); };
    Object.keys(factory).forEach(key => { try { wrapped[key] = factory[key]; } catch (_) {} });
    wrapped.__cbStateSyncWrapped = true;
    wrapped.__cbOriginal = factory;
    return wrapped;
  }

  if (typeof window.io === 'function') window.io = wrapIo(window.io);
  else {
    try {
      let ioValue;
      Object.defineProperty(window, 'io', {
        configurable: true,
        enumerable: true,
        get() { return ioValue; },
        set(value) { ioValue = wrapIo(value); }
      });
    } catch (_) {}
  }

  function queuePatch() {
    if (renderQueued) return;
    renderQueued = true;
    window.requestAnimationFrame(() => {
      renderQueued = false;
      patchVisibleState();
      relaxLineupGate();
    });
  }

  function patchVisibleState() {
    if (!state?.game?.is_live) return;

    const alignment = state.current_alignment || {};
    const inning = String(state.current_inning || state.game?.live_current_inning || '1');
    const inningEl = document.getElementById('live-inning-display');
    if (inningEl && inningEl.textContent.trim() !== inning) inningEl.textContent = inning;

    const pitcher = document.getElementById('live-current-pitcher');
    if (pitcher && alignment.P && pitcher.textContent.trim() !== alignment.P) pitcher.textContent = alignment.P;

    /*
     * #cbQuickDefense has exactly one renderer:
     * live_game_dugout_mode.js.
     *
     * This sync module owns transport/state recovery only. Writing
     * directly into the NOW field here creates two independent DOM
     * painters and can resurrect stale pre-Undo player names.
     */

    ['desktop','mobile'].forEach(mode => {
      positions().forEach(pos => {
        const zone = document.getElementById(`pos-${mode}-${pos}`);
        if (!zone) return;
        const name = alignment[pos];
        // Already showing this player: rewriting it anyway re-ran this patch
        // (the page's MutationObserver) every animation frame.
        const tags = zone.querySelectorAll('.player-tag');
        if (name ? tags.length === 1 && tags[0].dataset.playerName === name : !tags.length) return;
        tags.forEach(tag => tag.remove());
        if (name) zone.insertAdjacentHTML('beforeend', `<div class="player-tag" data-player-name="${esc(name)}">${esc(name)}</div>`);
      });
    });
  }

  function relaxLineupGate() {
    if (state?.game?.is_live) return;
    const button = document.getElementById('startLiveGameBtnAction');
    const note = document.getElementById('cb-quick-start-note');
    if (!button || !note || button.dataset.cbStartAllowed === '1') return;
    const text = String(note.textContent || '').replace('First-pitch setup', '').trim();
    if (!text.includes('Set the batting order')) return;
    const remaining = text.split('·').map(item => item.trim()).filter(Boolean).filter(item => item !== 'Set the batting order');
    if (remaining.length) return;
    button.disabled = false;
    button.classList.remove('disabled');
    button.dataset.cbStartAllowed = '1';
    button.dataset.cbStartMode = 'quick';
    note.className = 'quick';
    note.innerHTML = '<strong>First-pitch essentials are ready.</strong>Batting order is optional and can be added later.';
  }

  function applySharedLiveState(event) {
    const detail = event?.detail || {};

    if (Number(detail.game_id) !== gameId) {
      return;
    }

    const next = detail.state;

    if (
      !next ||
      Number(next?.game?.id) !== gameId
    ) {
      return;
    }

    // Published by another script from an older read: keep the newer state.
    if (isOlder(next)) return;

    state = next;
    stateLoadedAt = Date.now();
    lastSequence = sequenceFromState(next);
    queuePatch();
  }

  const observer = new MutationObserver(queuePatch);
  const start = () => {
    installSharedGameModalStyles();

    document.addEventListener(
      'coachboard:live-state',
      applySharedLiveState
    );
    observer.observe(document.body, {childList:true, subtree:true});
    loadState(true, 'initial').catch(() => {});
    queuePatch();

    document.addEventListener(
      'visibilitychange',
      () => {
        if (
          !document.hidden &&
          state?.game?.is_live
        ) {
          loadState(
            true,
            'visibility'
          ).catch(() => {});
        }
      }
    );

    // iOS/Safari can restore network before Socket.IO finishes its
    // reconnect handshake. Recover from the HTTP state endpoint too.
    window.addEventListener('online', () => {
      [0, 700, 2000].forEach(delay => {
        window.setTimeout(() => {
          if (!state?.game?.is_live) return;

          loadState(
            true,
            'online'
          ).catch(() => {});
        }, delay);
      });
    });
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
