(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const QUICK_MODAL_ID = 'cb-quick-start-modal';
  const STEP_MODAL_ID = 'cb-quick-step-modal';
  const RESUME_KEY = `coachboard:quick-start:${gameId}`;
  const STYLE_ID = 'cb-quick-start-modal-flow-styles';

  let activeStep = null;
  let moved = null;
  let suspendedForDefensePicker = false;
  let bypassDefenseCapture = false;
  let stepBusy = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${STEP_MODAL_ID} .modal-content{border:0;border-radius:16px;overflow:hidden}
      #${STEP_MODAL_ID} .modal-header{padding:12px 14px;border-bottom:1px solid #e7ebef}
      #${STEP_MODAL_ID} .cb-qsm-kicker{font-size:.58rem;font-weight:900;letter-spacing:.09em;text-transform:uppercase;color:#667085}
      #${STEP_MODAL_ID} .modal-title{font-size:1.06rem;font-weight:900;color:#172033;margin:1px 0 0}
      #${STEP_MODAL_ID} .cb-qsm-subtitle{font-size:.68rem;line-height:1.35;color:#667085;margin-top:2px}
      #${STEP_MODAL_ID} .modal-body{padding:11px 12px;background:#f7f9fb}
      #${STEP_MODAL_ID} .cb-qsm-guide{padding:9px 10px;margin-bottom:9px;border:1px solid #dce3eb;border-radius:10px;background:#fff;font-size:.69rem;line-height:1.35;color:#475467}
      #${STEP_MODAL_ID} .cb-qsm-host>#availabilityCollapse{display:block!important;margin:0!important}
      #${STEP_MODAL_ID} .cb-qsm-host>#availabilityCollapse>.card{margin:0!important;box-shadow:none!important}
      #${STEP_MODAL_ID} .cb-qsm-host>#pregame-defense-editor-v3{margin:0!important;box-shadow:none!important}
      #${STEP_MODAL_ID} .cb-qsm-footer{display:flex;justify-content:flex-end;gap:8px;padding:9px 12px calc(9px + env(safe-area-inset-bottom));border-top:1px solid #e7ebef;background:#fff}
      #${STEP_MODAL_ID} .cb-qsm-footer .btn{min-height:42px;border-radius:9px;font-weight:800}
      #${STEP_MODAL_ID}.cb-qsm-defense #pregame-defense-editor-v3 .pde-head{display:none!important}
      #${STEP_MODAL_ID}.cb-qsm-defense #pregame-defense-editor-v3 .pde-body{padding-top:8px!important}
      #${STEP_MODAL_ID}.cb-qsm-defense #pregame-defense-editor-v3 .pde-status{margin-bottom:0!important}
      #${STEP_MODAL_ID} .cb-qsp-list{display:grid;gap:7px}
      #${STEP_MODAL_ID} .cb-qsp-player{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;text-align:left;border:1px solid #dfe4ea;border-radius:11px;background:#fff;padding:10px 11px;color:#172033}
      #${STEP_MODAL_ID} .cb-qsp-player:not(:disabled):hover,#${STEP_MODAL_ID} .cb-qsp-player:not(:disabled):focus{border-color:#8aa0bc;background:#f8fafc}
      #${STEP_MODAL_ID} .cb-qsp-player:disabled{opacity:.62;background:#f8f9fb}
      #${STEP_MODAL_ID} .cb-qsp-name{display:block;font-size:.8rem;font-weight:850}
      #${STEP_MODAL_ID} .cb-qsp-detail{display:block;font-size:.65rem;color:#667085;margin-top:2px;line-height:1.3}
      #${STEP_MODAL_ID} .cb-qsp-state{font-size:.6rem;font-weight:850;border-radius:999px;padding:4px 7px;white-space:nowrap;background:#e8f5ec;color:#176b38}
      #${STEP_MODAL_ID} .cb-qsp-player:disabled .cb-qsp-state{background:#fff0dd;color:#8a5800}
      #${STEP_MODAL_ID} .cb-qsr-groups{display:grid;gap:10px}
      #${STEP_MODAL_ID} .cb-qsr-group{border:1px solid #dfe4ea;border-radius:12px;background:#fff;padding:10px}
      #${STEP_MODAL_ID} .cb-qsr-group-title{font-size:.78rem;font-weight:900;color:#172033}
      #${STEP_MODAL_ID} .cb-qsr-group-help{font-size:.65rem;color:#667085;line-height:1.3;margin:2px 0 8px}
      #${STEP_MODAL_ID} .cb-qsr-options{display:grid;grid-template-columns:1fr 1fr;gap:7px}
      #${STEP_MODAL_ID} .cb-qsr-choice{min-height:46px;border-radius:9px;font-size:.7rem;font-weight:800;text-align:left}
      #${STEP_MODAL_ID} .cb-qsr-current{font-size:.63rem;color:#176b38;font-weight:800;margin-top:3px}
      #${QUICK_MODAL_ID} .cb-qs-progress{font-size:.64rem;font-weight:800;color:#475467;margin-top:4px}
      #${QUICK_MODAL_ID} .cb-qs-progress strong{color:#172033}
      @media(max-width:575.98px){
        #${STEP_MODAL_ID} .modal-dialog{height:calc(100dvh - 12px);margin:6px}
        #${STEP_MODAL_ID} .modal-content{height:100%;max-height:100%}
        #${STEP_MODAL_ID} .modal-body{overflow:auto;padding:9px}
        #${STEP_MODAL_ID} .cb-qsr-options{grid-template-columns:1fr}
      }
    `;
    document.head.appendChild(style);
  }

  async function getJson(path) {
    const response = await fetch(path, {cache:'no-store'});
    if (!response.ok) throw new Error(`Unable to load setup (${response.status}).`);
    return response.json();
  }

  function parseInnings(value) {
    if (value && typeof value === 'object') return {...value};
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === 'object' ? parsed : {};
      } catch (_) {
        return {};
      }
    }
    return {};
  }

  function markResume(step) {
    try {
      sessionStorage.setItem(RESUME_KEY, JSON.stringify({gameId, step, at:Date.now()}));
    } catch (_) {}
  }

  function clearResume() {
    try { sessionStorage.removeItem(RESUME_KEY); } catch (_) {}
  }

  function hasRecentResume() {
    try {
      const raw = sessionStorage.getItem(RESUME_KEY);
      if (!raw) return false;
      const data = JSON.parse(raw);
      return Number(data?.gameId) === gameId && Date.now() - Number(data?.at || 0) < 45000;
    } catch (_) {
      return false;
    }
  }

  async function waitFor(selector, timeout = 8000) {
    const existing = document.querySelector(selector);
    if (existing) return existing;
    const started = Date.now();
    while (Date.now() - started < timeout) {
      await sleep(60);
      const node = document.querySelector(selector);
      if (node) return node;
    }
    return null;
  }

  function quickModalElement() {
    return document.getElementById(QUICK_MODAL_ID);
  }

  async function showQuickStart() {
    const modal = await waitFor(`#${QUICK_MODAL_ID}`, 10000);
    if (!modal || !window.bootstrap?.Modal) return;
    window.bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function hideQuickThen(callback) {
    const modal = quickModalElement();
    if (!modal || !window.bootstrap?.Modal || !modal.classList.contains('show')) {
      callback();
      return;
    }
    modal.addEventListener('hidden.bs.modal', () => window.setTimeout(callback, 30), {once:true});
    window.bootstrap.Modal.getOrCreateInstance(modal).hide();
  }

  function ensureStepModal() {
    let modal = document.getElementById(STEP_MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = STEP_MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <div class="cb-qsm-kicker">Quick Start</div>
              <h5 class="modal-title" data-cb-qsm-title></h5>
              <div class="cb-qsm-subtitle" data-cb-qsm-subtitle></div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Back to Quick Start"></button>
          </div>
          <div class="modal-body">
            <div class="cb-qsm-guide d-none" data-cb-qsm-guide></div>
            <div class="cb-qsm-host" data-cb-qsm-host></div>
          </div>
          <div class="cb-qsm-footer">
            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal"><i class="bi bi-arrow-left me-1"></i>Back to Quick Start</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('hidden.bs.modal', () => {
      if (suspendedForDefensePicker) return;
      restoreMovedNode();
      activeStep = null;
      modal.className = 'modal fade';
      if (!hasRecentResume()) window.setTimeout(showQuickStart, 100);
    });
    return modal;
  }

  function setStepHeader(title, subtitle, guide = '') {
    const modal = ensureStepModal();
    const titleNode = modal.querySelector('[data-cb-qsm-title]');
    const subtitleNode = modal.querySelector('[data-cb-qsm-subtitle]');
    const guideNode = modal.querySelector('[data-cb-qsm-guide]');
    if (titleNode) titleNode.textContent = title;
    if (subtitleNode) subtitleNode.textContent = subtitle;
    if (guideNode) {
      guideNode.textContent = guide;
      guideNode.classList.toggle('d-none', !guide);
    }
  }

  function clearStepHost() {
    const host = ensureStepModal().querySelector('[data-cb-qsm-host]');
    if (host) host.replaceChildren();
    return host;
  }

  function restoreMovedNode() {
    if (!moved) return;
    const {node, marker, className, style} = moved;
    if (marker?.isConnected) marker.replaceWith(node);
    if (className === null) node.removeAttribute('class');
    else node.setAttribute('class', className);
    if (style === null) node.removeAttribute('style');
    else node.setAttribute('style', style);
    moved = null;
  }

  function moveIntoStep(node) {
    restoreMovedNode();
    if (!node?.parentNode) return false;
    const marker = document.createElement('span');
    marker.hidden = true;
    marker.dataset.cbQuickStartPlaceholder = node.id || 'editor';
    node.parentNode.insertBefore(marker, node);
    moved = {
      node,
      marker,
      className:node.getAttribute('class'),
      style:node.getAttribute('style'),
    };
    clearStepHost()?.appendChild(node);
    return true;
  }

  function showStepModal(step, extraClass = '') {
    activeStep = step;
    const modal = ensureStepModal();
    modal.className = `modal fade ${extraClass}`.trim();
    window.bootstrap?.Modal?.getOrCreateInstance(modal).show();
  }

  function showStepError(title, message) {
    restoreMovedNode();
    setStepHeader(title, 'Quick Start');
    const host = clearStepHost();
    if (host) host.innerHTML = `<div class="alert alert-warning mb-0">${esc(message)}</div>`;
    showStepModal('error');
  }

  function openAvailability() {
    const collapse = document.getElementById('availabilityCollapse');
    if (!collapse || !moveIntoStep(collapse)) {
      showStepError('Player Availability', 'The availability editor is not ready yet. Close this window and try again.');
      return;
    }
    collapse.classList.remove('collapsing');
    collapse.classList.add('show');
    collapse.style.display = 'block';
    setStepHeader(
      'Player Availability',
      'Confirm who is available for this game.',
      'Everyone is available by default. Mark OUT only for players who will miss this game.'
    );
    showStepModal('availability', 'cb-qsm-availability');
  }

  async function openDefense() {
    const inningOne = document.querySelector('#inning-btn-group input[name="inning-radio"][value="1"]');
    if (inningOne && !inningOne.checked) {
      inningOne.click();
      await sleep(160);
    }
    const panel = document.getElementById('pregame-defense-editor-v3');
    if (!panel || !moveIntoStep(panel)) {
      showStepError('Starting Defense', 'The defense editor is not ready yet. Close this window and try again.');
      return;
    }
    setStepHeader(
      'Starting Defense',
      'Set the defense for the first inning.',
      'Tap a field position to change it, or use a saved Starting Defense. Pitcher assignments stay separate.'
    );
    showStepModal('defense', 'cb-qsm-defense');
  }

  function pitcherStatus(summary) {
    const status = String(summary?.status || '').trim() || 'Eligibility unknown';
    return {
      status,
      available:status === 'Available',
      detail:String(summary?.status_detail || summary?.next_available || '').trim(),
    };
  }

  async function openStartingPitcher() {
    setStepHeader(
      'Starting Pitcher',
      'Choose the pitcher who will start this game.',
      'Only pitchers CoachBoard currently shows as Available can be selected.'
    );
    const host = clearStepHost();
    if (host) host.innerHTML = '<div class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2"></span>Checking pitcher eligibility…</div>';
    showStepModal('starter', 'cb-qsm-starter');

    try {
      const [state, gameData] = await Promise.all([
        getJson(`/api/live-game/${gameId}/state`),
        getJson(`/api/game_data/${gameId}`),
      ]);
      if (activeStep !== 'starter' || !host?.isConnected) return;
      const absent = new Set((gameData.absent_player_ids || []).map(Number));
      const roster = (state.roster || gameData.roster || []).filter(player => !absent.has(Number(player.id)));
      const innings = parseInnings(gameData.rotation?.innings);
      const currentPitcher = String(innings?.['1']?.P || '').trim();
      const rows = roster.map(player => {
        const decision = pitcherStatus(state.pitch_count_summary?.[player.name] || {});
        return {player, decision};
      }).sort((a, b) => Number(b.decision.available) - Number(a.decision.available) || a.player.name.localeCompare(b.player.name));

      host.innerHTML = rows.length ? `<div class="cb-qsp-list">${rows.map(({player, decision}) => {
        const selected = player.name === currentPitcher;
        const detail = selected
          ? `Current starter${decision.detail ? ` · ${decision.detail}` : ''}`
          : (decision.detail || (decision.available ? 'Eligible for this game' : 'Not available to start')); 
        return `<button type="button" class="cb-qsp-player" data-cb-qsp-player="${esc(player.name)}" ${decision.available ? '' : 'disabled'}>
          <span><span class="cb-qsp-name">${esc(player.name)}${selected ? ' · Current' : ''}</span><span class="cb-qsp-detail">${esc(detail)}</span></span>
          <span class="cb-qsp-state">${esc(decision.available ? 'Available' : decision.status)}</span>
        </button>`;
      }).join('')}</div>` : '<div class="alert alert-warning mb-0">No available roster players were found.</div>';
    } catch (error) {
      if (host?.isConnected) host.innerHTML = `<div class="alert alert-warning mb-0">${esc(error.message || 'Unable to load pitcher eligibility.')}</div>`;
    }
  }

  async function saveStartingPitcher(playerName, button) {
    if (stepBusy || !playerName) return;
    stepBusy = true;
    if (button) button.disabled = true;
    try {
      const data = await getJson(`/api/game_data/${gameId}?_=${Date.now()}`);
      const rotation = data.rotation || {};
      const innings = parseInnings(rotation.innings);
      if (!innings['1'] || typeof innings['1'] !== 'object') innings['1'] = {};
      Object.keys(innings['1']).forEach(position => {
        if (position !== 'P' && innings['1'][position] === playerName) delete innings['1'][position];
      });
      innings['1'].P = playerName;
      const response = await fetch('/save_rotation', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          id:rotation.id || null,
          title:rotation.title || `Rotation for vs ${data.game?.opponent || 'Opponent'}`,
          innings,
          associated_game_id:gameId,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status === 'error') throw new Error(result.message || 'Unable to save the starting pitcher.');
      window.bootstrap?.Modal?.getOrCreateInstance(ensureStepModal()).hide();
    } catch (error) {
      window.alert(error.message || 'Unable to save the starting pitcher.');
      if (button?.isConnected) button.disabled = false;
    } finally {
      stepBusy = false;
    }
  }

  function trackingMode(ruleName) {
    if (ruleName === 'MLB Pitch Smart' || ruleName === 'Little League Baseball') return 'pitches';
    if (ruleName === 'USSSA' || ruleName === 'Bullpen Tournaments') return 'innings';
    return 'other';
  }

  async function openPitchingRules() {
    setStepHeader(
      'Pitching Tracking',
      'Choose how pitching is officially tracked for this game.',
      'CoachBoard still keeps arm-care guidance separate from the tournament or league eligibility rule.'
    );
    const host = clearStepHost();
    if (host) host.innerHTML = '<div class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2"></span>Loading pitching rules…</div>';
    showStepModal('rules', 'cb-qsm-rules');

    try {
      const data = await getJson(`/api/game-day/${gameId}/pitching-rules`);
      if (activeStep !== 'rules' || !host?.isConnected) return;
      const options = Array.isArray(data.options) && data.options.length
        ? data.options
        : ['MLB Pitch Smart', 'Little League Baseball', 'USSSA', 'Bullpen Tournaments'];
      const groups = [
        {
          mode:'pitches',
          title:'Track Pitches',
          help:'Use a pitch count during the game. Rest rules are based on the number of pitches thrown.',
        },
        {
          mode:'innings',
          title:'Track Innings / Outs',
          help:'Track innings or outs pitched across games and consecutive days.',
        },
        {
          mode:'other',
          title:'Other Pitching Rule',
          help:'Use the configured event or league rule.',
        },
      ];
      const markup = groups.map(group => {
        const matches = options.filter(name => trackingMode(name) === group.mode);
        if (!matches.length) return '';
        return `<section class="cb-qsr-group"><div class="cb-qsr-group-title">${esc(group.title)}</div><div class="cb-qsr-group-help">${esc(group.help)}</div><div class="cb-qsr-options">${matches.map(name => {
          const label = name === 'MLB Pitch Smart' ? 'MLB Pitch Smart' : name;
          const current = data.effective === name;
          return `<button type="button" class="btn ${current ? 'btn-primary' : 'btn-outline-primary'} cb-qsr-choice" data-cb-qsr-rule="${esc(name)}">${esc(label)}${current ? '<span class="d-block cb-qsr-current">Current rule</span>' : ''}</button>`;
        }).join('')}</div></section>`;
      }).join('');
      host.innerHTML = `<div class="cb-qsr-groups">${markup}</div>`;
    } catch (error) {
      if (host?.isConnected) host.innerHTML = `<div class="alert alert-warning mb-0">${esc(error.message || 'Unable to load pitching rules.')}</div>`;
    }
  }

  async function savePitchingRule(ruleName, button) {
    if (stepBusy || !ruleName) return;
    stepBusy = true;
    if (button) button.disabled = true;
    try {
      const response = await fetch(`/api/game-day/${gameId}/pitching-rules`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({rule_set:ruleName}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to save pitching tracking.');

      const inlineSelect = document.getElementById('game-pitch-rule-select-v2');
      if (inlineSelect) inlineSelect.value = ruleName;
      window.bootstrap?.Modal?.getOrCreateInstance(ensureStepModal()).hide();
    } catch (error) {
      window.alert(error.message || 'Unable to save pitching tracking.');
      if (button?.isConnected) button.disabled = false;
    } finally {
      stepBusy = false;
    }
  }

  function bindReturnFromExternalModal(modal, step) {
    const handler = () => {
      if (activeStep !== step) return;
      activeStep = null;
      window.setTimeout(() => {
        if (hasRecentResume()) return;
        showQuickStart();
      }, 120);
    };
    modal.addEventListener('hidden.bs.modal', handler, {once:true});
  }

  async function openBattingOrder() {
    const modal = await waitFor('#lineupEditorModal');
    if (!modal || !window.bootstrap?.Modal) {
      showStepError('Batting Order', 'The batting-order editor is not ready yet. Close this window and try again.');
      return;
    }
    activeStep = 'batting';
    bindReturnFromExternalModal(modal, 'batting');
    window.bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  async function openClock() {
    const button = await waitFor('#cbPregameClock .cb-clock-config', 4000);
    if (!button) {
      showStepError('Game Clock', 'The game-clock controls are not ready yet. Close this window and try again.');
      return;
    }
    activeStep = 'clock';
    button.click();
    const modal = await waitFor('#cbGameClockConfigModal', 2000);
    if (!modal) {
      activeStep = null;
      showStepError('Game Clock', 'The game-clock controls could not be opened.');
      return;
    }
    bindReturnFromExternalModal(modal, 'clock');
  }

  function openStep(key) {
    if (!key) return;
    hideQuickThen(() => {
      if (key === 'availability') openAvailability();
      else if (key === 'batting') openBattingOrder();
      else if (key === 'defense') openDefense();
      else if (key === 'starter') openStartingPitcher();
      else if (key === 'rules') openPitchingRules();
      else if (key === 'clock') openClock();
    });
  }

  function suspendForDefensePicker(spot) {
    if (!spot || bypassDefenseCapture || activeStep !== 'defense' || suspendedForDefensePicker) return;
    suspendedForDefensePicker = true;
    const stepModal = ensureStepModal();
    const reopen = async () => {
      bypassDefenseCapture = true;
      try { spot.click(); } finally { bypassDefenseCapture = false; }
      const picker = await waitFor('#pde-player-modal', 1500);
      if (!picker) {
        suspendedForDefensePicker = false;
        window.bootstrap?.Modal?.getOrCreateInstance(stepModal).show();
        return;
      }
      picker.addEventListener('hidden.bs.modal', () => {
        suspendedForDefensePicker = false;
        window.setTimeout(() => window.bootstrap?.Modal?.getOrCreateInstance(stepModal).show(), 70);
      }, {once:true});
    };
    stepModal.addEventListener('hidden.bs.modal', reopen, {once:true});
    window.bootstrap?.Modal?.getOrCreateInstance(stepModal).hide();
  }

  function decorateQuickProgress() {
    const modal = quickModalElement();
    const subtitle = modal?.querySelector('.cb-qs-subtitle');
    const list = modal?.querySelector('[data-cb-qs-list]');
    if (!subtitle || !list) return;
    const required = [...list.querySelectorAll('.cb-qs-step')].filter(step => !/optional/i.test(step.textContent || ''));
    const ready = required.filter(step => step.classList.contains('ready')).length;
    let progress = modal.querySelector('.cb-qs-progress');
    if (!progress) {
      progress = document.createElement('div');
      progress.className = 'cb-qs-progress';
      subtitle.insertAdjacentElement('afterend', progress);
    }
    progress.innerHTML = `<strong>${ready} of ${required.length || 5}</strong> essentials ready`;
  }

  function scheduleProgress() {
    window.setTimeout(decorateQuickProgress, 80);
    window.setTimeout(decorateQuickProgress, 350);
  }

  function bindEvents() {
    document.addEventListener('click', event => {
      const quickButton = event.target.closest(`#${QUICK_MODAL_ID} [data-cb-qs-go]`);
      if (quickButton) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        openStep(quickButton.dataset.cbQsGo);
        return;
      }

      const pitcher = event.target.closest(`#${STEP_MODAL_ID} [data-cb-qsp-player]`);
      if (pitcher && activeStep === 'starter') {
        event.preventDefault();
        saveStartingPitcher(pitcher.dataset.cbQspPlayer, pitcher);
        return;
      }

      const rule = event.target.closest(`#${STEP_MODAL_ID} [data-cb-qsr-rule]`);
      if (rule && activeStep === 'rules') {
        event.preventDefault();
        savePitchingRule(rule.dataset.cbQsrRule, rule);
        return;
      }

      const spot = event.target.closest(`#${STEP_MODAL_ID} #pregame-defense-editor-v3 .pde-spot`);
      if (spot && activeStep === 'defense' && !bypassDefenseCapture) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        suspendForDefensePicker(spot);
        return;
      }

      if (activeStep === 'batting' && event.target.closest('#lineupEditorModal #saveLineupBtn')) {
        const title = document.getElementById('lineupTitle')?.value.trim();
        const count = document.querySelectorAll('#lineup-order .list-group-item[data-player-name]').length;
        if (title && count) {
          markResume('batting');
          window.setTimeout(() => {
            if (document.visibilityState === 'visible') clearResume();
          }, 8000);
        }
        return;
      }

      if (activeStep === 'defense' && event.target.closest(`#${STEP_MODAL_ID} #pde-apply-game`)) {
        markResume('defense');
        window.setTimeout(() => {
          if (document.visibilityState === 'visible') clearResume();
        }, 8000);
      }
    }, true);

    document.addEventListener('submit', event => {
      if (activeStep !== 'availability' || event.target?.id !== 'gameAvailabilityForm') return;
      markResume('availability');
    }, true);

    document.addEventListener('shown.bs.modal', event => {
      if (event.target?.id === QUICK_MODAL_ID) scheduleProgress();
    });

    document.addEventListener('hidden.bs.modal', event => {
      if (event.target?.id === QUICK_MODAL_ID) return;
      if (event.target?.id === STEP_MODAL_ID) return;
      scheduleProgress();
    });

    const quickObserver = new MutationObserver(() => {
      if (quickModalElement()?.classList.contains('show')) scheduleProgress();
    });
    quickObserver.observe(document.body, {childList:true, subtree:true});
  }

  async function resumeAfterReload() {
    if (!hasRecentResume()) return;
    clearResume();
    const modal = await waitFor(`#${QUICK_MODAL_ID}`, 12000);
    if (!modal) return;
    await sleep(250);
    showQuickStart();
  }

  function start() {
    installStyles();
    ensureStepModal();
    bindEvents();
    resumeAfterReload();
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
