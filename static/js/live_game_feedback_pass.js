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
  let editor = null;
  let renderQueued = false;
  let suppressClickUntil = 0;
  let drag = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('cb-real-game-feedback-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-real-game-feedback-styles';
    style.textContent = `
      .modal .modal-header .btn-close{width:46px!important;height:46px!important;min-width:46px!important;min-height:46px!important;padding:0!important;margin:-6px -6px -6px 8px!important;border-radius:12px!important;background-size:14px 14px!important;opacity:.72;touch-action:manipulation}
      .modal .modal-header .btn-close:active{background-color:rgba(0,0,0,.08)}
      #cb-live-field-editor .modal-dialog{max-width:760px}
      #cb-live-field-editor .modal-content{border:0;border-radius:16px;overflow:hidden}
      #cb-live-field-editor .modal-body{padding:12px}
      #cb-live-field-editor .cb-lf-help{font-size:.76rem;color:#667085;margin-bottom:9px}
      #cb-live-field-editor .cb-lf-alert{display:none;border-radius:10px;padding:8px 10px;margin-bottom:9px;font-size:.74rem}
      #cb-live-field-editor .cb-lf-alert.show{display:block}
      #cb-live-field-editor .cb-lf-alert.error{background:#fff1f0;border:1px solid #f0b9b5;color:#912d28}
      #cb-live-field-editor .cb-lf-alert.info{background:#eef5ff;border:1px solid #bfd2f0;color:#294a84}
      #cb-live-field-editor .cb-lf-field{position:relative;width:100%;aspect-ratio:1.42/1;border-radius:16px;overflow:hidden;background:linear-gradient(180deg,#4d995a 0 58%,#b98c56 58% 100%);border:1px solid rgba(23,32,51,.16);user-select:none;-webkit-user-select:none}
      #cb-live-field-editor .cb-lf-field:before{content:"";position:absolute;left:50%;bottom:-4%;width:47%;aspect-ratio:1/1;transform:translateX(-50%) rotate(45deg);background:#cda16a;border:2px solid rgba(255,255,255,.68)}
      #cb-live-field-editor .cb-lf-field:after{content:"";position:absolute;left:50%;bottom:6%;width:27%;aspect-ratio:1/1;transform:translateX(-50%) rotate(45deg);background:#4d995a;border:1px solid rgba(255,255,255,.68)}
      #cb-live-field-editor .cb-lf-spot{position:absolute;transform:translate(-50%,-50%);width:86px;min-height:54px;z-index:2;border:1px dashed rgba(255,255,255,.72);border-radius:12px;background:rgba(255,255,255,.18);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:3px}
      #cb-live-field-editor .cb-lf-spot.cb-drag-over,#cb-live-field-editor .cb-lf-bench.cb-drag-over{outline:4px solid rgba(22,107,56,.28);background:#edf8f1}
      #cb-live-field-editor .cb-lf-pos{font-size:.58rem;font-weight:900;color:#fff;text-shadow:0 1px 2px #000;line-height:1}
      #cb-live-field-editor .cb-lf-open{font-size:.65rem;color:rgba(255,255,255,.9);font-weight:750;margin-top:3px}
      #cb-live-field-editor .cb-lf-player{display:block;width:100%;border:1px solid #cfd6df;background:#fff;color:#172033;border-radius:9px;padding:7px 6px;font-size:.68rem;font-weight:850;line-height:1.12;text-align:center;box-shadow:0 2px 5px rgba(16,24,40,.13);touch-action:none;cursor:grab}
      #cb-live-field-editor .cb-lf-player.selected{outline:3px solid rgba(16,42,102,.28);border-color:#102a66}
      #cb-live-field-editor .cb-lf-player.pitch-blocked{border-color:#ddb5b2}
      #cb-live-field-editor .cb-lf-player small{display:block;font-size:.55rem;font-weight:650;color:#667085;margin-top:2px}
      #cb-live-field-editor .cb-lf-bench{margin-top:10px;border:2px dashed #cfd6df;border-radius:13px;background:#f8fafc;padding:9px;min-height:76px}
      #cb-live-field-editor .cb-lf-bench-title{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:7px}
      #cb-live-field-editor .cb-lf-bench-title strong{font-size:.76rem;color:#344054}
      #cb-live-field-editor .cb-lf-bench-title span{font-size:.66rem;color:#667085}
      #cb-live-field-editor .cb-lf-bench-list{display:flex;flex-wrap:wrap;gap:6px}
      #cb-live-field-editor .cb-lf-bench .cb-lf-player{width:auto;min-width:86px;max-width:150px}
      #cb-live-field-editor .cb-lf-pitcher-prompt{margin-top:9px;padding:9px;border:1px solid #d5dff4;border-radius:11px;background:#f7f9ff}
      #cb-live-field-editor .cb-lf-pitcher-prompt strong{display:block;font-size:.75rem;color:#172033;margin-bottom:6px}
      #cb-live-field-editor .cb-lf-prompt-actions{display:flex;flex-wrap:wrap;gap:5px}
      #cb-live-field-editor .cb-lf-prompt-actions .btn{font-size:.68rem;font-weight:800;padding:7px 9px}
      #cb-live-field-editor .cb-lf-footer{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7eaf0;padding:10px 12px calc(10px + env(safe-area-inset-bottom));display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:center}
      #cb-live-field-editor .cb-lf-save{min-height:48px;font-weight:850}
      #cb-live-field-editor .cb-lf-cancel{min-height:48px}
      #cb-live-field-editor .cb-lf-change-count{font-size:.68rem;color:#667085;margin-right:8px}
      #cb-live-field-editor .cb-lf-ghost{position:fixed;z-index:7000;pointer-events:none;width:104px;transform:translate(-50%,-50%) scale(1.04);border:2px solid #102a66;background:#fff;border-radius:10px;padding:8px;text-align:center;font-size:.7rem;font-weight:850;box-shadow:0 12px 28px rgba(16,24,40,.24)}
      #cb-bench-history-v2 .modal-dialog{max-width:700px}
      #cb-bench-history-v2 .cb-br2-summary{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
      #cb-bench-history-v2 .cb-br2-chip{border:1px solid #dfe4ea;border-radius:999px;padding:5px 8px;font-size:.68rem;font-weight:750;background:#f8fafc}
      #cb-bench-history-v2 .cb-br2-list{display:grid;gap:7px}
      #cb-bench-history-v2 .cb-br2-row{border:1px solid #e1e5ea;border-radius:11px;padding:9px 10px}
      #cb-bench-history-v2 .cb-br2-row.bench-now{border-color:#dfc477;background:#fffaf0}
      #cb-bench-history-v2 .cb-br2-top{display:flex;justify-content:space-between;gap:8px}
      #cb-bench-history-v2 .cb-br2-name{font-weight:850;color:#172033}
      #cb-bench-history-v2 .cb-br2-count{font-size:.64rem;font-weight:800;border-radius:999px;background:#eef2f6;padding:4px 7px;height:max-content}
      #cb-bench-history-v2 .cb-br2-detail{font-size:.7rem;color:#667085;line-height:1.4;margin-top:4px}
      #cb-bench-history-v2 .cb-br2-now{font-weight:800;color:#8b5c00}
      #cb-bench-history-v2 .cb-br2-plan{color:#294a84}
      @media(max-width:575.98px){#cb-live-field-editor .modal-dialog,#cb-bench-history-v2 .modal-dialog{margin:.35rem}#cb-live-field-editor .modal-body{padding:9px}#cb-live-field-editor .cb-lf-field{aspect-ratio:1.2/1;max-height:390px}#cb-live-field-editor .cb-lf-spot{width:72px;min-height:49px}#cb-live-field-editor .cb-lf-player{font-size:.62rem;padding:6px 4px}#cb-live-field-editor .cb-lf-bench .cb-lf-player{min-width:78px}}
    `;
    document.head.appendChild(style);
  }

  installStyles();

  let stateInflight = null;
  let stateInflightUntil = 0;
  window.fetch = function(input, init = {}) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    if (method === 'GET' && url && new URL(url, window.location.href).pathname === `/api/live-game/${gameId}/state`) {
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

  function fieldCoordinates() {
    return Number(state?.outfielder_count) === 4
      ? {LF:[10,20],LCF:[36,13],RCF:[64,13],RF:[90,20],SS:[38,43],'2B':[62,43],'3B':[18,56],'1B':[82,56],P:[50,63],C:[50,86]}
      : {LF:[13,20],CF:[50,12],RF:[87,20],SS:[38,43],'2B':[62,43],'3B':[18,56],'1B':[82,56],P:[50,63],C:[50,86]};
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

  function pitcherStatus(name) {
    return state?.pitch_count_summary?.[name] || {};
  }

  function pitcherBlocked(name) {
    const status = String(pitcherStatus(name)?.status || '').toLowerCase();
    return ['rest','unavailable','ineligible','incomplete','restriction','verify'].some(term => status.includes(term));
  }

  function toast(message, kind = 'success') {
    let host = document.getElementById('cb-feedback-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'cb-feedback-toast-host';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '8000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast align-items-center text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>`;
    host.appendChild(el);
    if (window.bootstrap?.Toast) {
      const instance = bootstrap.Toast.getOrCreateInstance(el, {delay: 2600});
      el.addEventListener('hidden.bs.toast', () => el.remove(), {once:true});
      instance.show();
    } else window.setTimeout(() => el.remove(), 2800);
  }

  async function readJson(url, options) {
    const response = await window.fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') {
      const error = new Error(data.message || `Request failed (${response.status}).`);
      error.data = data;
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function loadState(force = false) {
    if (!force && state && (socketHealthy || Date.now() - stateLoadedAt < 15000)) return state;
    const data = await readJson(stateUrl, {cache:'no-store'});
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
    if (!socket || socket.__cbFeedbackWired) return socket;
    socket.__cbFeedbackWired = true;
    socket.on?.('connect', () => { socketHealthy = true; });
    socket.on?.('disconnect', () => { socketHealthy = false; });
    socket.on?.('live_game_delta', applyDelta);
    return socket;
  }

  function wrapIo(factory) {
    if (typeof factory !== 'function' || factory.__cbFeedbackWrapped) return factory;
    const wrapped = function(...args) { return wireSocket(factory.apply(this, args)); };
    Object.keys(factory).forEach(key => { try { wrapped[key] = factory[key]; } catch (_) {} });
    wrapped.__cbFeedbackWrapped = true;
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

  function ensureEditorModal() {
    let modal = document.getElementById('cb-live-field-editor');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'cb-live-field-editor';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">On Field Now</h5><div class="small text-muted" data-cb-editor-subtitle></div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><div class="cb-lf-help">Drag a player to another position or down to the Bench. You can also tap a player, then tap the destination.</div><div class="cb-lf-alert" data-cb-editor-alert></div><div data-cb-editor-body></div></div><div class="cb-lf-footer"><button type="button" class="btn btn-outline-secondary cb-lf-cancel" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-primary cb-lf-save" data-cb-editor-save>Save Changes</button></div></div></div>`;
    document.body.appendChild(modal);

    modal.addEventListener('click', event => {
      if (Date.now() < suppressClickUntil) return;
      const outgoing = event.target.closest('[data-cb-outgoing-dest]');
      if (outgoing && editor?.pendingOutgoing) {
        const name = editor.pendingOutgoing;
        editor.pendingOutgoing = null;
        if (outgoing.dataset.cbOutgoingDest !== 'BENCH') movePlayer(name, outgoing.dataset.cbOutgoingDest);
        else renderEditor();
        return;
      }
      const reload = event.target.closest('[data-cb-review-latest]');
      if (reload) {
        loadState(true).then(() => {
          if (!editor) return;
          editor.baseSequence = sequenceFromState();
          editor.baseAlignment = {...(state.current_alignment || {})};
          editor.draft = {...editor.baseAlignment};
          editor.pendingOutgoing = null;
          editor.selected = '';
          renderEditor();
          setEditorAlert('Latest field loaded. Review it, then make your changes again.', 'info');
        }).catch(err => setEditorAlert(err.message, 'error'));
        return;
      }
      const player = event.target.closest('[data-cb-editor-player]');
      if (player) {
        editor.selected = player.dataset.cbEditorPlayer;
        renderEditor();
        return;
      }
      const drop = event.target.closest('[data-cb-editor-drop]');
      if (drop && editor?.selected) {
        movePlayer(editor.selected, drop.dataset.cbEditorDrop);
        return;
      }
      if (event.target.closest('[data-cb-editor-save]')) saveEditor();
    });

    modal.addEventListener('pointerdown', beginDrag, {passive:false});
    document.addEventListener('pointermove', continueDrag, {passive:false});
    document.addEventListener('pointerup', endDrag, {passive:false});
    document.addEventListener('pointercancel', cancelDrag, {passive:false});
    modal.addEventListener('hidden.bs.modal', () => { editor = null; cancelDrag(); });
    return modal;
  }

  function setEditorAlert(message = '', kind = 'error', extra = '') {
    const el = document.querySelector('#cb-live-field-editor [data-cb-editor-alert]');
    if (!el) return;
    el.className = `cb-lf-alert ${message ? 'show' : ''} ${kind}`;
    el.innerHTML = message ? `${esc(message)}${extra}` : '';
  }

  function locationOf(name, alignment = editor?.draft) {
    return Object.entries(alignment || {}).find(([, player]) => player === name)?.[0] || 'BENCH';
  }

  function locationOfNameIn(name, alignment) {
    return Object.entries(alignment || {}).find(([, player]) => player === name)?.[0] || '';
  }

  function changeCount() {
    if (!editor) return 0;
    const names = new Set([...(state?.roster || []).map(player => player.name), ...Object.values(editor.baseAlignment || {}), ...Object.values(editor.draft || {})]);
    let count = 0;
    names.forEach(name => { if (locationOf(name, editor.baseAlignment) !== locationOf(name, editor.draft)) count += 1; });
    return count;
  }

  function movePlayer(name, destination) {
    if (!editor || !name || !destination) return;
    const source = locationOf(name);
    if (source === destination) { editor.selected = ''; renderEditor(); return; }
    const draft = editor.draft;
    const occupant = destination === 'BENCH' ? '' : (draft[destination] || '');
    const incomingPitcher = destination === 'P' ? name : (source === 'P' && occupant ? occupant : null);
    if (incomingPitcher && pitcherBlocked(incomingPitcher)) {
      const status = pitcherStatus(incomingPitcher)?.status || 'not available';
      setEditorAlert(`${incomingPitcher} cannot pitch right now: ${status}.`, 'error');
      return;
    }
    if (destination === 'BENCH') {
      if (source !== 'BENCH') delete draft[source];
    } else {
      if (source !== 'BENCH') delete draft[source];
      draft[destination] = name;
      if (occupant && occupant !== name && source !== 'BENCH') draft[source] = occupant;
    }
    if (destination === 'P' && source === 'BENCH' && occupant) editor.pendingOutgoing = occupant;
    else if (editor.pendingOutgoing === name && destination !== 'BENCH') editor.pendingOutgoing = null;
    editor.selected = '';
    setEditorAlert();
    renderEditor();
  }

  function missingPositions() {
    return positions().filter(pos => !editor?.draft?.[pos]);
  }

  function renderEditor() {
    if (!editor) return;
    const modal = ensureEditorModal();
    const body = modal.querySelector('[data-cb-editor-body]');
    const title = modal.querySelector('.modal-title');
    const subtitle = modal.querySelector('[data-cb-editor-subtitle]');
    const save = modal.querySelector('[data-cb-editor-save]');
    const coords = fieldCoordinates();
    const draft = editor.draft || {};
    const assigned = new Set(Object.values(draft).filter(Boolean));
    const bench = (state?.roster || []).filter(player => !assigned.has(player.name));

    if (editor.mode === 'inning') {
      title.textContent = `End Inning ${editor.currentInning}`;
      subtitle.textContent = `Set the defense that will take the field for Inning ${editor.nextInning}.`;
      save.textContent = `Start Inning ${editor.nextInning}`;
    } else if (editor.pitcherFocus) {
      title.textContent = 'Change Pitcher';
      subtitle.textContent = 'Move the incoming pitcher to P, then adjust the rest of the defense.';
      save.textContent = 'Save Pitcher + Defense';
    } else {
      title.textContent = 'On Field Now';
      subtitle.textContent = `Inning ${state?.current_inning || '—'} — make all defensive changes before saving.`;
      save.textContent = 'Save Changes';
    }

    const spots = positions().map(pos => {
      const [left, top] = coords[pos] || [50,50];
      const name = draft[pos] || '';
      const status = pos === 'P' && name ? pitcherStatus(name)?.status : '';
      return `<div class="cb-lf-spot" style="left:${left}%;top:${top}%" data-cb-editor-drop="${esc(pos)}"><span class="cb-lf-pos">${esc(pos)}</span>${name ? `<button type="button" class="cb-lf-player ${editor.selected === name ? 'selected' : ''} ${pitcherBlocked(name) ? 'pitch-blocked' : ''}" data-cb-editor-player="${esc(name)}"><span>${esc(playerLabel(name))}</span>${pos === 'P' && status ? `<small>${esc(status)}</small>` : ''}</button>` : '<span class="cb-lf-open">Open</span>'}</div>`;
    }).join('');

    const benchMarkup = bench.length
      ? bench.map(player => `<button type="button" class="cb-lf-player ${editor.selected === player.name ? 'selected' : ''}" data-cb-editor-player="${esc(player.name)}"><span>${esc(playerLabel(player.name))}</span>${pitcherBlocked(player.name) ? `<small>${esc(pitcherStatus(player.name)?.status || '')}</small>` : ''}</button>`).join('')
      : '<span class="small text-muted">No players on the bench.</span>';

    const prompt = editor.pendingOutgoing
      ? `<div class="cb-lf-pitcher-prompt"><strong>Where should ${esc(editor.pendingOutgoing)} go?</strong><div class="cb-lf-prompt-actions"><button type="button" class="btn btn-outline-secondary" data-cb-outgoing-dest="BENCH">Bench</button>${positions().filter(pos => pos !== 'P').map(pos => `<button type="button" class="btn btn-outline-primary" data-cb-outgoing-dest="${pos}">${pos}${draft[pos] ? ` · ${esc(draft[pos])}` : ''}</button>`).join('')}</div></div>`
      : '';

    const missing = missingPositions();
    const changes = changeCount();
    body.innerHTML = `<div class="cb-lf-field">${spots}</div><div class="cb-lf-bench" data-cb-editor-drop="BENCH"><div class="cb-lf-bench-title"><strong>BENCH · ${bench.length}</strong><span>Drop a fielder here</span></div><div class="cb-lf-bench-list">${benchMarkup}</div></div>${prompt}<div class="d-flex justify-content-between align-items-center mt-2"><span class="cb-lf-change-count">${changes ? `${changes} player move${changes === 1 ? '' : 's'} staged` : 'No changes yet'}</span>${missing.length ? `<span class="small text-danger fw-semibold">Open: ${esc(missing.join(', '))}</span>` : ''}</div>`;
  }

  function beginDrag(event) {
    const player = event.target.closest('[data-cb-editor-player]');
    if (!player || !editor || event.button > 0) return;
    drag = {pointerId:event.pointerId,name:player.dataset.cbEditorPlayer,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY,active:false,ghost:null};
    try { player.setPointerCapture(event.pointerId); } catch (_) {}
  }

  function continueDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.x = event.clientX; drag.y = event.clientY;
    if (!drag.active) {
      if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < 9) return;
      drag.active = true;
      const ghost = document.createElement('div');
      ghost.className = 'cb-lf-ghost';
      ghost.textContent = playerLabel(drag.name);
      document.body.appendChild(ghost);
      drag.ghost = ghost;
    }
    event.preventDefault();
    drag.ghost.style.left = `${drag.x}px`; drag.ghost.style.top = `${drag.y}px`;
    document.querySelectorAll('#cb-live-field-editor [data-cb-editor-drop]').forEach(el => el.classList.remove('cb-drag-over'));
    const hit = document.elementFromPoint(drag.x, drag.y)?.closest?.('[data-cb-editor-drop]');
    if (hit) hit.classList.add('cb-drag-over');
  }

  function endDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const wasActive = drag.active;
    const name = drag.name;
    if (wasActive) {
      event.preventDefault();
      const hit = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-cb-editor-drop]');
      if (hit) movePlayer(name, hit.dataset.cbEditorDrop);
      suppressClickUntil = Date.now() + 350;
    }
    cancelDrag();
  }

  function cancelDrag() {
    document.querySelectorAll('#cb-live-field-editor [data-cb-editor-drop]').forEach(el => el.classList.remove('cb-drag-over'));
    drag?.ghost?.remove();
    drag = null;
  }

  async function openEditor(mode, options = {}) {
    try {
      await loadState(!socketHealthy && Date.now() - stateLoadedAt > 10000);
      if (!state?.game?.is_live) await loadState(true);
      if (!state?.game?.is_live) { toast('Live Game is not running.', 'danger'); return; }
      let draft = {...(state.current_alignment || {})};
      let nextInning = null;
      if (mode === 'inning') {
        const prep = await readJson(`/api/live-game/${gameId}/next-inning-prep`, {cache:'no-store'});
        nextInning = String(prep.next_inning || (Number(state.current_inning || 1) + 1));
        if (prep.confirmed?.alignment) {
          const data = await readJson(`/api/live-game/${gameId}/advance-inning`, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({alignment:prep.confirmed.alignment,base_sequence:sequenceFromState()}),
          });
          if (!data.delta) throw new Error('CoachBoard did not confirm the next inning.');
          applyDelta(data.delta);
          toast(`✓ Inning ${nextInning} started • Saved & Synced`);
          return;
        }
        if (prep.planned_alignment && Object.values(prep.planned_alignment).some(Boolean)) {
          draft = {...prep.planned_alignment};
          if (!draft.P && state.current_alignment?.P) draft.P = state.current_alignment.P;
          const duplicatePitcherPos = Object.entries(draft).find(([pos, name]) => pos !== 'P' && name === draft.P)?.[0];
          if (duplicatePitcherPos) draft = {...state.current_alignment};
        }
      }
      editor = {mode,pitcherFocus:Boolean(options.pitcherFocus),currentInning:String(state.current_inning || '1'),nextInning,baseSequence:sequenceFromState(),baseAlignment:{...(state.current_alignment || {})},draft,selected:'',pendingOutgoing:null,saving:false};
      renderEditor();
      setEditorAlert();
      bootstrap.Modal.getOrCreateInstance(ensureEditorModal()).show();
    } catch (err) { toast(err.message, 'danger'); }
  }

  async function saveEditor() {
    if (!editor || editor.saving) return;
    const missing = missingPositions();
    if (missing.length) { setEditorAlert(`Fill ${missing.join(', ')} before saving.`, 'error'); return; }
    const save = document.querySelector('#cb-live-field-editor [data-cb-editor-save]');
    editor.saving = true;
    if (save) { save.disabled = true; save.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…'; }
    try {
      let path;
      let payload = {alignment:editor.draft,base_sequence:editor.baseSequence};
      if (editor.mode === 'inning') path = `/api/live-game/${gameId}/advance-inning`;
      else if (editor.draft.P !== editor.baseAlignment.P) {
        const pitcher = playerByName(editor.draft.P);
        if (!pitcher) throw new Error('Choose a valid pitcher.');
        path = `/api/live-game/${gameId}/complete-pitcher-change`;
        payload = {...payload,new_pitcher_id:pitcher.id,fast:true};
      } else path = `/api/live-game/${gameId}/defense-edit`;

      const data = await readJson(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if (!data.delta) throw new Error('CoachBoard did not confirm the saved live state.');
      applyDelta(data.delta);
      const mode = editor.mode;
      const next = editor.nextInning;
      bootstrap.Modal.getOrCreateInstance(ensureEditorModal()).hide();
      toast(mode === 'inning' ? `✓ Inning ${next} started • Saved & Synced` : '✓ Defense saved & synced');
    } catch (err) {
      if (err.data?.code === 'stale_live_state') {
        if (state) {
          state.current_inning = String(err.data.current_inning || state.current_inning || '1');
          state.current_alignment = {...(err.data.current_alignment || state.current_alignment || {})};
          lastSequence = Math.max(lastSequence, Number(err.data.current_sequence) || 0);
          queuePatch();
        }
        setEditorAlert('Another coach changed the field while you were editing.', 'error', ' <button type="button" class="btn btn-sm btn-outline-danger ms-2" data-cb-review-latest>Review latest field</button>');
      } else setEditorAlert(err.message, 'error');
    } finally {
      if (editor) editor.saving = false;
      if (save) {
        save.disabled = false;
        save.textContent = editor?.mode === 'inning' ? `Start Inning ${editor.nextInning}` : (editor?.draft?.P !== editor?.baseAlignment?.P ? 'Save Pitcher + Defense' : 'Save Changes');
      }
    }
  }

  function eventSnapshotsForInning(inning) {
    const target = String(inning);
    const snapshots = [];
    const events = (state?.rotation_events || []).filter(event => !event?.reverted && String(event?.inning) === target).sort((a,b) => (Number(a.sequence)||0) - (Number(b.sequence)||0));
    events.forEach(event => {
      if (event.event_type === 'End Inning') {
        if (event.after_alignment) snapshots.push({...event.after_alignment});
      } else {
        if (event.before_alignment) snapshots.push({...event.before_alignment});
        if (event.after_alignment) snapshots.push({...event.after_alignment});
      }
    });
    if (!snapshots.length) {
      const actual = state?.actual_rotation?.[target];
      if (actual && typeof actual === 'object') snapshots.push({...actual});
    }
    return snapshots;
  }

  function positionHistoryFor(name, inning) {
    const found = [];
    eventSnapshotsForInning(inning).forEach(alignment => {
      const pos = Object.entries(alignment || {}).find(([, player]) => player === name)?.[0];
      if (pos && found[found.length - 1] !== pos) found.push(pos);
    });
    return found;
  }

  function completePlanned(alignment) {
    return positions().filter(pos => pos !== 'P').every(pos => String(alignment?.[pos] || '').trim());
  }

  function buildBenchRows() {
    const current = Number(state?.current_inning || 1);
    const completed = Object.keys(state?.actual_rotation || {}).map(value => Number(value)).filter(value => Number.isFinite(value) && value < current).sort((a,b) => a-b);
    const planned = state?.rotation?.innings && typeof state.rotation.innings === 'object' ? state.rotation.innings : {};
    const future = Object.entries(planned).map(([inning, alignment]) => ({inning:Number(inning), alignment})).filter(item => Number.isFinite(item.inning) && item.inning > current && completePlanned(item.alignment)).sort((a,b) => a.inning-b.inning);
    const assignedNow = new Set(Object.values(state?.current_alignment || {}).filter(Boolean));
    return (state?.roster || []).map(player => {
      const name = player.name;
      const fullSat = [];
      const played = [];
      completed.forEach(inning => {
        const positionsPlayed = positionHistoryFor(name, inning);
        if (positionsPlayed.length) played.push(`${inning}: ${positionsPlayed.join(' / ')}`);
        else fullSat.push(String(inning));
      });
      const currentPositions = positionHistoryFor(name, current);
      const currentBench = !assignedNow.has(name);
      const currentNow = currentBench ? (currentPositions.length ? `Bench now · played ${currentPositions.join(' / ')} earlier` : 'Bench now') : `Now: ${locationOfNameIn(name, state.current_alignment) || 'Field'}`;
      const plannedSat = future.filter(item => !Object.values(item.alignment || {}).includes(name)).map(item => String(item.inning));
      return {player,name,display:playerLabel(name),fullSat,played,currentBench,currentNow,plannedSat};
    }).sort((a,b) => {
      if (a.currentBench !== b.currentBench) return a.currentBench ? -1 : 1;
      if (a.fullSat.length !== b.fullSat.length) return b.fullSat.length - a.fullSat.length;
      return a.name.localeCompare(b.name);
    });
  }

  async function openBenchReport() {
    try {
      await loadState(!socketHealthy && Date.now() - stateLoadedAt > 10000);
      let modal = document.getElementById('cb-bench-history-v2');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'cb-bench-history-v2';
        modal.className = 'modal fade';
        modal.tabIndex = -1;
        modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Bench Report</h5><div class="small text-muted">Actual appearances, full innings sat, and planned bench time</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body" data-cb-br2-body></div><div class="modal-footer"><button type="button" class="btn btn-primary" data-bs-dismiss="modal">Back to Game</button></div></div></div>`;
        document.body.appendChild(modal);
      }
      const rows = buildBenchRows();
      const onBench = rows.filter(row => row.currentBench).length;
      modal.querySelector('[data-cb-br2-body]').innerHTML = `<div class="cb-br2-summary"><span class="cb-br2-chip">Inning ${esc(state.current_inning)}</span><span class="cb-br2-chip">Bench now: ${onBench}</span><span class="cb-br2-chip">Full inning only counts if player never appeared</span></div><div class="cb-br2-list">${rows.map(row => `<div class="cb-br2-row ${row.currentBench ? 'bench-now' : ''}"><div class="cb-br2-top"><div class="cb-br2-name">${esc(row.display)}</div><div class="cb-br2-count">${row.fullSat.length} full ${row.fullSat.length === 1 ? 'inning' : 'innings'} sat</div></div><div class="cb-br2-detail"><span class="cb-br2-now">${esc(row.currentNow)}</span></div><div class="cb-br2-detail"><strong>Full innings sat:</strong> ${row.fullSat.length ? esc(row.fullSat.join(', ')) : 'None'}</div>${row.played.length ? `<div class="cb-br2-detail"><strong>Actual positions:</strong> ${esc(row.played.join(' · '))}</div>` : ''}${row.plannedSat.length ? `<div class="cb-br2-detail cb-br2-plan"><strong>Planned to sit:</strong> ${esc(row.plannedSat.join(', '))}</div>` : ''}</div>`).join('')}</div>`;
      bootstrap.Modal.getOrCreateInstance(modal).show();
    } catch (err) { toast(err.message, 'danger'); }
  }

  function intercept(event) {
    const target = event.target.closest?.('#liveDefensiveChangeBtn,#liveChangePitcherBtn,#liveEndInningBtn,[data-cb-bench-report]');
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (target.id === 'liveDefensiveChangeBtn') openEditor('defense');
    else if (target.id === 'liveChangePitcherBtn') openEditor('defense', {pitcherFocus:true});
    else if (target.id === 'liveEndInningBtn') openEditor('inning');
    else openBenchReport();
  }

  document.addEventListener('click', intercept, true);

  const observer = new MutationObserver(queuePatch);
  const start = () => {
    observer.observe(document.body, {childList:true,subtree:true,attributes:true,attributeFilter:['disabled','class']});
    loadState(true).catch(() => {});
    queuePatch();
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && state?.game?.is_live && !socketHealthy) loadState(true).catch(() => {});
    });
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();