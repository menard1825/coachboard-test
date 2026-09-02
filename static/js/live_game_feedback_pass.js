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
  window.fetch = function(input, init = {}) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    if (method === 'GET' && url && new URL(url, window.location.href).pathname === stateUrl) {
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
      return promise.then(response => response.clone());
    }
    return nativeFetch(input, init);
  };

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

  async function loadState(force = false) {
    if (!force && state && (socketHealthy || Date.now() - stateLoadedAt < 15000)) return state;
    const response = await window.fetch(stateUrl, {cache:'no-store'});
    if (!response.ok) return state;
    const data = await response.json().catch(() => null);
    if (!data) return state;
    state = data;
    stateLoadedAt = Date.now();
    lastSequence = Math.max(lastSequence, sequenceFromState(data));
    queuePatch();
    return state;
  }

  function applyDelta(delta) {
    if (!delta || Number(delta.game_id) !== gameId) return;
    const sequence = Number(delta.sequence) || 0;
    if (sequence && sequence < lastSequence) return;
    if (sequence && lastSequence && sequence > lastSequence + 1) loadState(true).catch(() => {});
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
    document.dispatchEvent(new CustomEvent('coachboard:live-delta', {detail:delta}));
  }

  function wireSocket(socket) {
    if (!socket || socket.__cbStateSyncWired) return socket;
    socket.__cbStateSyncWired = true;
    socket.on?.('connect', () => { socketHealthy = true; });
    socket.on?.('disconnect', () => { socketHealthy = false; });
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
    if (document.querySelector('#cbQuickDefense .cb-main-draft-banner, #cbQuickDefense .cb-main-open')) return;

    const alignment = state.current_alignment || {};
    const inning = String(state.current_inning || state.game?.live_current_inning || '1');
    const inningEl = document.getElementById('live-inning-display');
    if (inningEl && inningEl.textContent.trim() !== inning) inningEl.textContent = inning;

    const pitcher = document.getElementById('live-current-pitcher');
    if (pitcher && alignment.P && pitcher.textContent.trim() !== alignment.P) pitcher.textContent = alignment.P;

    document.querySelectorAll('#cbQuickDefense .cb-qd-spot[data-cb-position]').forEach(spot => {
      const pos = spot.dataset.cbPosition;
      const name = alignment[pos] || '';
      const label = spot.querySelector('.cb-qd-name');
      if (label) label.textContent = name ? playerLabel(name) : 'Open';
      spot.dataset.cbMovePlayer = name || 'Open';
      spot.disabled = !name;
    });

    const assigned = new Set(Object.values(alignment).filter(Boolean));
    const benchPlayers = (state.roster || []).filter(player => !assigned.has(player.name));
    const bench = document.querySelector('#cbQuickDefense .cb-qd-bench');
    if (bench) {
      const wanted = benchPlayers.length
        ? benchPlayers.map(player => `<button type="button" class="cb-qd-bench-player" data-cb-move-player="${esc(player.name)}"><span>${esc(playerLabel(player.name))}</span><span class="cb-bench-note">Bench now</span></button>`).join('')
        : '<span class="small text-muted">No players are on the bench.</span>';
      if (bench.innerHTML !== wanted) bench.innerHTML = wanted;
    }

    ['desktop','mobile'].forEach(mode => {
      positions().forEach(pos => {
        const zone = document.getElementById(`pos-${mode}-${pos}`);
        if (!zone) return;
        zone.querySelectorAll('.player-tag').forEach(tag => tag.remove());
        const name = alignment[pos];
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

  const observer = new MutationObserver(queuePatch);
  const start = () => {
    installSharedGameModalStyles();
    observer.observe(document.body, {childList:true, subtree:true});
    loadState(true).catch(() => {});
    queuePatch();
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && state?.game?.is_live && !socketHealthy) loadState(true).catch(() => {});
    });
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
