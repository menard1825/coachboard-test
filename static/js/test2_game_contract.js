(() => {
  'use strict';

  const route = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!route) return;

  const gameId = Number(route[1]);
  const MODE_KEY = `coachboard:test2-pregame-mode:${gameId}`;
  const MODE_ID = 'cb-test2-pregame-modes';
  const HUDDLE_ID = 'cb-test2-huddle-modal';
  let mode = window.sessionStorage.getItem(MODE_KEY) === 'full-plan' ? 'full-plan' : 'first-pitch';
  let queued = false;
  let huddleBusy = false;
  let huddlePrep = null;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[char]));
  const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));
  const setText = (element, value) => {
    if (element && element.textContent !== value) element.textContent = value;
  };

  function installStyles() {
    if ($('cb-test2-contract-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-test2-contract-styles';
    style.textContent = `
      #${MODE_ID}{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 12px;padding:9px 10px;border:1px solid #dfe4ea;border-radius:12px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.04)}
      #${MODE_ID} .cb-t2-mode-copy{min-width:0}.cb-t2-mode-kicker{font-size:.58rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#667085}.cb-t2-mode-help{font-size:.67rem;color:#667085;line-height:1.3;margin-top:2px}
      #${MODE_ID} .cb-t2-mode-buttons{display:flex;gap:5px;flex:0 0 auto;padding:3px;border:1px solid #d9dee5;border-radius:10px;background:#f4f6f8}
      #${MODE_ID} .cb-t2-mode-buttons .btn{border:0!important;border-radius:7px!important;min-height:36px;padding:6px 10px;font-size:.69rem;font-weight:850;box-shadow:none!important}
      #${MODE_ID} .cb-t2-mode-buttons .active{background:#172033!important;color:#fff!important}
      #cb-quick-start-launch,#cb-quick-start-modal{display:none!important}
      body.cb-test2-first-pitch #lineup-card-container,
      body.cb-test2-first-pitch #pitching-log-container,
      body.cb-test2-first-pitch #pitching-board-v2{display:none!important}
      body.cb-test2-first-pitch #coach-game-readiness-v2 [data-cgr-action="lineup"]{display:none!important}
      body.cb-test2-first-pitch #rotation-card-container>.card>.card-header{display:none!important}
      body.cb-test2-first-pitch #rotation-board>*:not(#pregame-defense-editor-v3){display:none!important}
      #${HUDDLE_ID} .modal-content{border:0;border-radius:16px;overflow:hidden}
      #${HUDDLE_ID} .modal-header{padding:12px 14px;border-bottom:1px solid #e7ebef}
      #${HUDDLE_ID} .cb-t2-huddle-kicker{font-size:.59rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#667085}
      #${HUDDLE_ID} .modal-title{font-size:1.08rem;font-weight:900;color:#172033;margin-top:1px}
      #${HUDDLE_ID} .cb-t2-huddle-sub{font-size:.68rem;color:#667085;margin-top:2px}
      #${HUDDLE_ID} .modal-body{background:#f7f9fb;padding:11px 12px}
      #${HUDDLE_ID} .cb-t2-huddle-status{border:1px solid #dfe4ea;border-radius:11px;background:#fff;padding:9px 10px;margin-bottom:9px}
      #${HUDDLE_ID} .cb-t2-huddle-status.ready{border-color:#b8dcc4;background:#f5fbf7}
      #${HUDDLE_ID} .cb-t2-huddle-status strong{display:block;color:#172033;font-size:.82rem}
      #${HUDDLE_ID} .cb-t2-huddle-status span{display:block;color:#667085;font-size:.69rem;line-height:1.35;margin-top:2px}
      #${HUDDLE_ID} .cb-t2-moves{display:grid;gap:6px;margin:8px 0}
      #${HUDDLE_ID} .cb-t2-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e2e6eb;border-radius:9px;background:#fff;padding:7px 9px}
      #${HUDDLE_ID} .cb-t2-move strong{font-size:.75rem;color:#172033}#${HUDDLE_ID} .cb-t2-move small{display:block;color:#667085;font-size:.63rem;margin-top:1px}
      #${HUDDLE_ID} .cb-t2-dest{min-width:48px;text-align:center;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;font-size:.65rem;font-weight:850}#${HUDDLE_ID} .cb-t2-dest.bench{background:#eef1f5;color:#475467}
      #${HUDDLE_ID} .cb-t2-huddle-actions{display:grid;gap:7px;margin-top:9px}#${HUDDLE_ID} .cb-t2-huddle-actions.two{grid-template-columns:1fr 1fr}
      #${HUDDLE_ID} .cb-t2-huddle-actions .btn{min-height:46px;border-radius:10px;font-weight:820}
      #${HUDDLE_ID} .cb-t2-error{display:none;border:1px solid #efbbb6;border-radius:9px;background:#fff2f0;color:#912d28;padding:8px 9px;font-size:.7rem;margin-top:8px}#${HUDDLE_ID} .cb-t2-error.show{display:block}
      #${HUDDLE_ID} .cb-t2-start{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7ebef;padding:10px 12px calc(10px + env(safe-area-inset-bottom))}
      #${HUDDLE_ID} .cb-t2-start .btn{width:100%;min-height:50px;border-radius:10px;font-weight:900}
      @media(max-width:575.98px){
        #${MODE_ID}{display:grid;grid-template-columns:1fr;padding:8px 9px}#${MODE_ID} .cb-t2-mode-buttons{width:100%}#${MODE_ID} .cb-t2-mode-buttons .btn{flex:1}
        #${HUDDLE_ID} .modal-dialog{margin:.35rem}#${HUDDLE_ID} .cb-t2-huddle-actions.two{grid-template-columns:1fr}
      }
    `;
    document.head.appendChild(style);
  }

  function ensureClockControls() {
    if ([...document.scripts].some(script => /\/live_game_clock_controls\.js(?:\?|$)/.test(script.src || ''))) return;
    const script = document.createElement('script');
    script.src = '/static/js/live_game_clock_controls.js?v=test2';
    script.dataset.cbTest2ClockControls = 'true';
    document.head.appendChild(script);
  }

  function isLive() {
    const overlay = $('live-game-overlay');
    return document.body.classList.contains('cb-dugout') || Boolean(overlay && !overlay.classList.contains('d-none'));
  }

  function forceInningOne() {
    if (mode !== 'first-pitch' || isLive()) return;
    const inningOne = document.querySelector('#inning-btn-group input[name="inning-radio"][value="1"]');
    if (inningOne && !inningOne.checked) inningOne.click();
  }

  function polishPregameDefense() {
    if (isLive()) return;
    const panel = $('pregame-defense-editor-v3');
    if (!panel) return;
    if (mode === 'first-pitch') {
      setText(panel.querySelector('.pde-kicker'), 'First Pitch');
      setText(panel.querySelector('.pde-title'), 'First-pitch defense');
      setText(panel.querySelector('.pde-help'), 'Set only the defense needed to start the game. Full Plan is available when you want later innings.');
      return;
    }
    const selectedInning = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked')?.value || '1';
    setText(panel.querySelector('.pde-kicker'), 'Defense Setup');
    setText(panel.querySelector('.pde-title'), `Set Defense — Inning ${selectedInning}`);
    setText(panel.querySelector('.pde-help'), 'Set the defense for this inning, or use the full-game planning tools for later innings.');
  }

  function updateModeButtons() {
    const bar = $(MODE_ID);
    if (!bar) return;
    bar.querySelectorAll('[data-cb-t2-mode]').forEach(button => {
      const active = button.dataset.cbT2Mode === mode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    setText(bar.querySelector('.cb-t2-mode-help'), mode === 'first-pitch'
      ? 'Only first-pitch essentials are in view. Batting order and later innings stay optional.'
      : 'Plan batting order, later defensive innings, pitching, and the rest of the game.');
  }

  function setMode(next) {
    mode = next === 'full-plan' ? 'full-plan' : 'first-pitch';
    window.sessionStorage.setItem(MODE_KEY, mode);
    document.body.classList.toggle('cb-test2-first-pitch', mode === 'first-pitch');
    document.body.classList.toggle('cb-test2-full-plan', mode === 'full-plan');
    updateModeButtons();
    forceInningOne();
    polishPregameDefense();
  }

  function ensureModeBar() {
    const pregame = $('pregame-checklist-container');
    if (!pregame || isLive()) {
      $(MODE_ID)?.remove();
      return;
    }
    let bar = $(MODE_ID);
    if (!bar) {
      bar = document.createElement('section');
      bar.id = MODE_ID;
      bar.innerHTML = `
        <div class="cb-t2-mode-copy"><div class="cb-t2-mode-kicker">Get ready</div><div class="cb-t2-mode-help"></div></div>
        <div class="cb-t2-mode-buttons" role="group" aria-label="Pregame planning mode">
          <button type="button" class="btn" data-cb-t2-mode="first-pitch">First Pitch</button>
          <button type="button" class="btn" data-cb-t2-mode="full-plan">Full Plan</button>
        </div>`;
      const header = pregame.querySelector(':scope > .d-flex:first-child');
      if (header) header.insertAdjacentElement('afterend', bar);
      else pregame.prepend(bar);
      bar.addEventListener('click', event => {
        const button = event.target.closest('[data-cb-t2-mode]');
        if (button) setMode(button.dataset.cbT2Mode);
      });
    }
    setMode(mode);
  }

  function polishQuickField() {
    const quick = $('cbQuickDefense');
    if (!quick) return;
    setText(quick.querySelector('.cb-qd-kicker'), 'Live Defense');
    setText(quick.querySelector('.cb-qd-title'), 'Quick Field');
    setText(quick.querySelector('.cb-qd-help'), 'Drag or tap players right on the field and bench. Pitcher changes stay in Change Pitcher.');
  }

  function applyContract() {
    queued = false;
    installStyles();
    $('cb-quick-start-launch')?.remove();
    const quickModal = $('cb-quick-start-modal');
    if (quickModal) {
      try { window.bootstrap?.Modal?.getInstance(quickModal)?.hide(); } catch (_) {}
      quickModal.remove();
    }

    if (isLive()) {
      document.body.classList.remove('cb-test2-first-pitch', 'cb-test2-full-plan');
      $(MODE_ID)?.remove();
      polishQuickField();
    } else {
      ensureModeBar();
      forceInningOne();
      polishPregameDefense();
    }
  }

  function queueContract() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(applyContract);
  }

  async function getJson(path) {
    const response = await fetch(path, {cache:'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Request failed (${response.status}).`);
    return data;
  }

  async function postJson(path, body) {
    const response = await fetch(path, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Request failed (${response.status}).`);
    return data;
  }

  function sequenceFromState(state) {
    return (state?.rotation_events || []).reduce((max, event) => {
      if (event?.reverted) return max;
      return Math.max(max, Number(event?.sequence) || 0);
    }, 0);
  }

  function locationMap(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([position, name]) => { if (name) map.set(name, position); });
    (roster || []).forEach(player => { if (!map.has(player.name)) map.set(player.name, 'BENCH'); });
    return map;
  }

  function movesBetween(current, next, roster) {
    const before = locationMap(current, roster);
    const after = locationMap(next, roster);
    return [...new Set([...before.keys(), ...after.keys()])]
      .map(name => ({name, from:before.get(name) || 'BENCH', to:after.get(name) || 'BENCH'}))
      .filter(move => move.from !== move.to)
      .sort((a, b) => {
        if (a.to === 'P') return -1;
        if (b.to === 'P') return 1;
        if (a.to === 'BENCH' && b.to !== 'BENCH') return 1;
        if (b.to === 'BENCH' && a.to !== 'BENCH') return -1;
        return a.to.localeCompare(b.to) || a.name.localeCompare(b.name);
      });
  }

  function confirmedAlignment(prep) {
    if (!prep?.confirmed) return null;
    return prep.confirmed.source === 'current'
      ? {...(prep.current_alignment || {})}
      : {...(prep.confirmed.alignment || {})};
  }

  function plannedCandidate(prep) {
    const planned = {...(prep?.planned_alignment || {})};
    const pitcher = prep?.current_alignment?.P || '';
    if (!pitcher || !Object.values(planned).some(Boolean)) return null;
    const conflict = Object.entries(planned).find(([position, name]) => position !== 'P' && name === pitcher);
    if (conflict) return null;
    planned.P = pitcher;
    return planned;
  }

  async function waitForQuickFieldSave() {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const badge = document.querySelector('#cbQuickDefense .cb-save-state');
      if (!badge || !badge.classList.contains('saving')) return;
      await sleep(100);
    }
    throw new Error('Quick Field is still saving. Try End Inning again after Saved ✓ appears.');
  }

  async function waitForLiveWritesToSettle() {
    await waitForQuickFieldSave();
    let previous = null;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      const state = await getJson(`/api/live-game/${gameId}/state`);
      const signature = `${state.current_inning || ''}:${sequenceFromState(state)}`;
      if (signature === previous) return state;
      previous = signature;
      await sleep(120);
    }
    return getJson(`/api/live-game/${gameId}/state`);
  }

  function ensureHuddle() {
    let modal = $(HUDDLE_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = HUDDLE_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header"><div><div class="cb-t2-huddle-kicker">Between innings</div><h5 class="modal-title mb-0">End Inning</h5><div class="cb-t2-huddle-sub"></div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Back to game"></button></div>
          <div class="modal-body"><div data-cb-t2-huddle-body></div><div class="cb-t2-error" data-cb-t2-huddle-error></div></div>
          <div class="cb-t2-start"><button type="button" class="btn btn-dark" data-cb-t2-start-inning disabled>Start Inning</button></div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      const choice = event.target.closest('[data-cb-t2-choice]');
      if (choice) chooseNextDefense(choice.dataset.cbT2Choice);
      const plan = event.target.closest('[data-cb-t2-plan]');
      if (plan) returnToNextPlan();
      const start = event.target.closest('[data-cb-t2-start-inning]');
      if (start) startNextInning();
    });
    return modal;
  }

  function showHuddleError(message) {
    const box = ensureHuddle().querySelector('[data-cb-t2-huddle-error]');
    if (!box) return;
    setText(box, message || '');
    box.classList.toggle('show', Boolean(message));
  }

  function renderHuddle(prep) {
    huddlePrep = prep;
    const modal = ensureHuddle();
    const next = String(prep?.next_inning || '');
    const current = String(prep?.current_inning || '');
    const body = modal.querySelector('[data-cb-t2-huddle-body]');
    const subtitle = modal.querySelector('.cb-t2-huddle-sub');
    const start = modal.querySelector('[data-cb-t2-start-inning]');
    setText(subtitle, `Inning ${current} is over. Check the next defense before sending the team out.`);

    const target = confirmedAlignment(prep);
    const roster = prep?.roster || [];
    const planned = plannedCandidate(prep);
    if (target) {
      const moves = movesBetween(prep.current_alignment || {}, target, roster);
      const moveMarkup = moves.length
        ? `<div class="cb-t2-moves">${moves.map(move => `<div class="cb-t2-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="cb-t2-dest ${move.to === 'BENCH' ? 'bench' : ''}">${esc(move.to)}</div></div>`).join('')}</div>`
        : '<div class="cb-t2-huddle-status ready"><strong>Same defense</strong><span>The same players and positions are going back out.</span></div>';
      body.innerHTML = `<div class="cb-t2-huddle-status ready"><strong>Inning ${esc(next)} defense is ready</strong><span>${moves.length ? 'Make these moves, then start the inning.' : 'No defensive moves are needed.'}</span></div>${moveMarkup}<div class="cb-t2-huddle-actions"><button type="button" class="btn btn-outline-secondary" data-cb-t2-plan>Change next defense</button></div>`;
      start.disabled = false;
      setText(start, `Start Inning ${next}`);
      showHuddleError('');
      return;
    }

    body.innerHTML = `
      <div class="cb-t2-huddle-status"><strong>Choose the Inning ${esc(next)} defense</strong><span>Pick who goes out next, then start the inning.</span></div>
      <div class="cb-t2-huddle-actions ${planned ? 'two' : ''}">
        <button type="button" class="btn btn-outline-dark" data-cb-t2-choice="current">Same Defense</button>
        ${planned ? '<button type="button" class="btn btn-outline-primary" data-cb-t2-choice="planned">Use Planned Defense</button>' : ''}
        <button type="button" class="btn btn-outline-secondary" data-cb-t2-plan>Change next defense</button>
      </div>`;
    start.disabled = true;
    setText(start, `Start Inning ${next}`);
    showHuddleError('');
  }

  async function refreshHuddle() {
    const prep = await getJson(`/api/live-game/${gameId}/next-inning-prep`);
    renderHuddle(prep);
    return prep;
  }

  async function chooseNextDefense(choice) {
    if (huddleBusy) return;
    huddleBusy = true;
    showHuddleError('');
    try {
      let data;
      if (choice === 'planned') {
        const candidate = plannedCandidate(huddlePrep);
        if (!candidate) throw new Error('The planned defense is not ready to use. Review the Next Inning plan first.');
        if (window.CBNextDefense?.usePregame) data = await window.CBNextDefense.usePregame();
        else data = await postJson(`/api/live-game/${gameId}/next-inning-prep`, {mode:'custom', alignment:candidate});
      } else {
        if (window.CBNextDefense?.useSame) data = await window.CBNextDefense.useSame();
        else data = await postJson(`/api/live-game/${gameId}/next-inning-prep`, {mode:'current'});
      }
      if (!data) data = await getJson(`/api/live-game/${gameId}/next-inning-prep`);
      renderHuddle(data);
    } catch (error) {
      showHuddleError(error.message || 'Unable to set the next defense.');
    } finally {
      huddleBusy = false;
    }
  }

  function returnToNextPlan() {
    const modal = ensureHuddle();
    window.bootstrap?.Modal?.getOrCreateInstance(modal)?.hide();
    window.setTimeout(() => {
      const board = $('live-board-prep-v3');
      board?.scrollIntoView({behavior:'smooth', block:'start'});
      board?.classList.add('cb-board-flash');
      window.setTimeout(() => board?.classList.remove('cb-board-flash'), 1500);
    }, 180);
  }

  async function startNextInning() {
    if (huddleBusy) return;
    huddleBusy = true;
    showHuddleError('');
    const modal = ensureHuddle();
    const button = modal.querySelector('[data-cb-t2-start-inning]');
    if (button) button.disabled = true;
    try {
      await waitForLiveWritesToSettle();
      const [prep, liveState] = await Promise.all([
        getJson(`/api/live-game/${gameId}/next-inning-prep`),
        getJson(`/api/live-game/${gameId}/state`),
      ]);
      const alignment = confirmedAlignment(prep);
      if (!alignment) throw new Error('Lock the next defense before starting the inning.');
      if (String(liveState.current_inning || '') !== String(prep.current_inning || '')) {
        throw new Error('Another coach already moved the game forward. The huddle has been refreshed.');
      }
      const result = await postJson(`/api/live-game/${gameId}/advance-inning`, {
        alignment,
        base_sequence: sequenceFromState(liveState),
      });
      window.bootstrap?.Modal?.getOrCreateInstance(modal)?.hide();
      document.dispatchEvent(new CustomEvent('coachboard:test2-inning-started', {detail:{result}}));
      window.CBNextDefense?.refresh?.();
      window.setTimeout(() => $('cbQuickDefense')?.scrollIntoView({behavior:'smooth', block:'start'}), 180);
    } catch (error) {
      showHuddleError(error.message || 'Unable to start the next inning.');
      try { await refreshHuddle(); } catch (_) {}
    } finally {
      huddleBusy = false;
      if (button?.isConnected && confirmedAlignment(huddlePrep)) button.disabled = false;
    }
  }

  async function openHuddle() {
    if (huddleBusy) return;
    huddleBusy = true;
    const modal = ensureHuddle();
    showHuddleError('');
    const body = modal.querySelector('[data-cb-t2-huddle-body]');
    if (body) body.innerHTML = '<div class="cb-t2-huddle-status"><strong>Checking next inning…</strong><span>CoachBoard is making sure the current defense is saved.</span></div>';
    modal.querySelector('[data-cb-t2-start-inning]').disabled = true;
    window.bootstrap?.Modal?.getOrCreateInstance(modal)?.show();
    try {
      await waitForLiveWritesToSettle();
      await refreshHuddle();
    } catch (error) {
      showHuddleError(error.message || 'Unable to prepare the next inning.');
    } finally {
      huddleBusy = false;
    }
  }

  window.addEventListener('click', event => {
    const button = event.target.closest?.('#liveEndInningBtn');
    if (!button || button.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    openHuddle();
  }, true);

  window.CBTest2Contract = {
    setMode,
    openHuddle,
    apply: applyContract,
  };

  function start() {
    installStyles();
    ensureClockControls();
    applyContract();
    const observer = new MutationObserver(queueContract);
    observer.observe(document.body, {childList:true, subtree:true});
    window.addEventListener('orientationchange', queueContract, {passive:true});
    window.addEventListener('resize', queueContract, {passive:true});
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();