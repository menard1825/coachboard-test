(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const MODAL_ID = 'cb-quick-start-modal';
  const LAUNCH_ID = 'cb-quick-start-launch';
  const STYLE_ID = 'cb-pregame-quick-start-styles';
  let latest = {state:null, readiness:null, rules:null, startReady:null, startMissing:[]};
  let refreshBusy = false;
  let startAnchor = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #cb-quick-start-note{display:none!important}
      #${LAUNCH_ID}{
        display:flex;align-items:center;justify-content:space-between;gap:12px;
        border:1px solid #cfdae9;border-left:4px solid #d0a526;border-radius:13px;
        background:#fff;padding:11px 12px;margin:0 0 10px;box-shadow:0 2px 8px rgba(16,24,40,.04)
      }
      #${LAUNCH_ID} .cb-qsl-copy{min-width:0}
      #${LAUNCH_ID} .cb-qsl-title{font-size:.84rem;font-weight:900;color:#172033}
      #${LAUNCH_ID} .cb-qsl-help{font-size:.68rem;line-height:1.35;color:#667085;margin-top:2px}
      #${LAUNCH_ID} .cb-qsl-button{flex:0 0 auto;min-height:40px;border-radius:9px;font-size:.72rem;font-weight:850;white-space:nowrap}
      #${MODAL_ID} .modal-content{border:0;border-radius:16px;overflow:hidden}
      #${MODAL_ID} .modal-header{border-bottom:1px solid #e8ecf1;padding:13px 14px}
      #${MODAL_ID} .cb-qs-kicker{font-size:.59rem;text-transform:uppercase;letter-spacing:.09em;color:#667085;font-weight:900}
      #${MODAL_ID} .modal-title{font-size:1.08rem;font-weight:900;color:#172033;margin-top:1px}
      #${MODAL_ID} .cb-qs-subtitle{font-size:.69rem;color:#667085;line-height:1.35;margin-top:2px}
      #${MODAL_ID} .modal-body{padding:11px 12px;background:#f7f9fb}
      #${MODAL_ID} .cb-qs-list{display:grid;gap:7px}
      #${MODAL_ID} .cb-qs-step{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:9px;border:1px solid #dfe4ea;border-radius:12px;background:#fff;padding:9px 10px}
      #${MODAL_ID} .cb-qs-step.ready{border-color:#b9dcc4;background:#f8fcf9}
      #${MODAL_ID} .cb-qs-step.warn{border-color:#ead7b5;background:#fffaf1}
      #${MODAL_ID} .cb-qs-icon{width:32px;height:32px;border-radius:9px;display:flex;align-items:center;justify-content:center;background:#edf2f8;color:#344054;font-size:.9rem}
      #${MODAL_ID} .ready .cb-qs-icon{background:#e5f5ea;color:#176b38}
      #${MODAL_ID} .warn .cb-qs-icon{background:#fff0d0;color:#8a5a13}
      #${MODAL_ID} .cb-qs-name{font-size:.76rem;font-weight:880;color:#172033}
      #${MODAL_ID} .cb-qs-status{font-size:.65rem;color:#667085;line-height:1.3;margin-top:1px}
      #${MODAL_ID} .cb-qs-action{min-width:62px;min-height:36px;border-radius:8px;font-size:.65rem;font-weight:850}
      #${MODAL_ID} .cb-qs-footer{position:sticky;bottom:0;background:#fff;border-top:1px solid #e5e9ef;padding:10px 12px calc(10px + env(safe-area-inset-bottom));display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:center}
      #${MODAL_ID} .cb-qs-footer .btn{min-height:46px;border-radius:10px;font-weight:850}
      #${MODAL_ID} .cb-qs-start-slot #startLiveGameBtnAction{position:static!important;left:auto!important;right:auto!important;bottom:auto!important;width:100%!important;margin:0!important;min-height:46px!important;box-shadow:none!important}
      #${MODAL_ID} .cb-qs-blockers{grid-column:1/-1;font-size:.65rem;color:#805710;line-height:1.3}
      #${MODAL_ID} .cb-qs-blockers.ready{color:#176b38}
      #game-pitching-rules-v2 .cb-pitch-source{font-size:.62rem;color:#667085;font-weight:700;margin-left:4px}
      #game-pitching-rules-v2 .cb-pitch-smart-help{border-top:1px solid #eef1f4;padding:7px 10px;background:#fbfcfd}
      #game-pitching-rules-v2 .cb-pitch-smart-help button{border:0;background:transparent;padding:0;color:#294a84;font-size:.64rem;font-weight:800}
      #game-pitching-rules-v2 .cb-pitch-smart-copy{display:none;margin-top:5px;color:#667085;font-size:.64rem;line-height:1.35}
      #game-pitching-rules-v2 .cb-pitch-smart-help.open .cb-pitch-smart-copy{display:block}
      #coach-game-readiness-v2 .cb-hidden-redundant{display:none!important}
      @media(max-width:767.98px){
        #${LAUNCH_ID}{padding:10px;align-items:stretch}
        #${LAUNCH_ID} .cb-qsl-button{min-width:112px}
        body.coach-game-page:not(.cb-dugout) #startLiveGameBtnAction{
          position:fixed!important;left:10px!important;right:10px!important;bottom:calc(10px + env(safe-area-inset-bottom))!important;
          width:auto!important;z-index:1035!important;box-shadow:0 8px 24px rgba(16,24,40,.24)!important
        }
        body.coach-game-page:not(.cb-dugout){padding-bottom:78px!important}
        #${MODAL_ID} .modal-dialog{height:calc(100dvh - 12px);margin:6px}
        #${MODAL_ID} .modal-content{height:100%;max-height:100%}
        #${MODAL_ID} .modal-body{overflow:auto}
      }
      @media(max-width:374.98px){
        #${LAUNCH_ID}{display:grid;grid-template-columns:1fr}
        #${LAUNCH_ID} .cb-qsl-button{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  async function getJson(path) {
    const response = await fetch(path, {cache:'no-store'});
    if (!response.ok) return null;
    return response.json().catch(() => null);
  }

  function trackingMode(ruleName) {
    const name = String(ruleName || '').trim();
    if (!name) return {label:'Choose tracking', detail:'Select the tournament or league pitching rules.'};
    if (name === 'MLB Pitch Smart' || name === 'Little League Baseball') {
      return {label:'Track Pitches', detail:name === 'MLB Pitch Smart' ? 'Pitch Smart' : 'Little League'};
    }
    if (name === 'USSSA' || name === 'Bullpen Tournaments') {
      return {label:'Track Innings / Outs', detail:name};
    }
    return {label:'Track Pitching', detail:name};
  }

  function inningOneComplete(readiness = latest.readiness) {
    if (!readiness) return false;
    const incomplete = Array.isArray(readiness.incomplete_innings) ? readiness.incomplete_innings : [];
    return !incomplete.some(item => String(item?.inning) === '1');
  }

  function starterName() {
    const state = latest.state || {};
    const alignment = state.actual_rotation?.['1'] || state.current_alignment || {};
    return alignment.P || null;
  }

  function clockSummary() {
    const clock = document.getElementById('cbPregameClock');
    if (!clock) return 'Optional — set a time limit if this game uses one';
    const text = String(clock.textContent || '').replace(/\s+/g,' ').trim();
    const found = text.match(/(\d{1,3})\s*(?:min|minute)/i);
    if (found) return `${found[1]} minute time limit`;
    return 'No time limit · optional';
  }

  function setupSteps() {
    const readiness = latest.readiness || {};
    const rules = latest.rules || {};
    const starter = starterName();
    const tracking = trackingMode(rules.effective);
    return [
      {
        key:'availability', name:'Player Availability', icon:'bi-people-fill',
        ready:Number(readiness.present_count || 0) > 0,
        status:Number(readiness.present_count || 0) > 0 ? `${readiness.present_count} available` : 'Confirm who is available today',
      },
      {
        key:'defense', name:'Starting Defense', icon:'bi-diagram-3-fill',
        ready:inningOneComplete(readiness),
        status:inningOneComplete(readiness) ? 'Inning 1 defense is ready' : 'Fill the Inning 1 defense',
      },
      {
        key:'starter', name:'Starting Pitcher', icon:'bi-person-check-fill',
        ready:Boolean(starter),
        status:starter ? `${starter} is the Inning 1 pitcher` : 'Choose P on the Inning 1 defense',
      },
      {
        key:'rules', name:'Pitching Tracking', icon:'bi-clipboard2-pulse-fill',
        ready:Boolean(rules.effective),
        status:rules.effective ? `${tracking.label} · ${tracking.detail}` : 'Choose the game pitching rules',
      },
      {
        key:'batting', name:'Batting Order', icon:'bi-list-ol',
        ready:Boolean(readiness.lineup_ready), optional:true,
        status:readiness.lineup_ready ? 'Batting order is set' : 'Optional — add it later if you need it',
      },
      {
        key:'clock', name:'Game Clock', icon:'bi-clock-fill',
        ready:true, optional:true, status:clockSummary(),
      },
    ];
  }

  function findLeafByText(root, patterns) {
    if (!root) return null;
    const nodes = [...root.querySelectorAll('button,a,h3,h4,h5,h6,strong,span,div')];
    return nodes.find(node => {
      if (node.children.length) return false;
      const text = String(node.textContent || '').replace(/\s+/g,' ').trim();
      return patterns.some(pattern => pattern.test(text));
    }) || null;
  }

  function targetFor(key) {
    if (key === 'defense' || key === 'starter') return document.getElementById('rotation-card-container') || document.getElementById('pregame-defense-editor-v3');
    if (key === 'rules') return document.getElementById('game-pitching-rules-v2');
    if (key === 'clock') return document.getElementById('cbPregameClock') || findLeafByText(document, [/Set Time Limit/i])?.closest('.card,section,div');
    if (key === 'batting') return findLeafByText(document, [/^Batting Order$/i])?.closest('.card,section,[id]');
    if (key === 'availability') return findLeafByText(document, [/^Player Availability$/i, /^Who['’]s Out$/i])?.closest('.card,section,[id]');
    return null;
  }

  function restoreStartButton() {
    const button = document.getElementById('startLiveGameBtnAction');
    if (!button || !startAnchor?.parentNode) return;
    startAnchor.parentNode.insertBefore(button, startAnchor.nextSibling);
  }

  function moveStartButtonIntoModal(modal) {
    const button = document.getElementById('startLiveGameBtnAction');
    const slot = modal.querySelector('[data-cb-qs-start-slot]');
    if (!button || !slot) return;
    if (!startAnchor) {
      startAnchor = document.createComment('CoachBoard canonical Start Game button');
      button.parentNode?.insertBefore(startAnchor, button);
    }
    slot.appendChild(button);
    button.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i>START GAME';
  }

  function scrollToStep(key) {
    const target = targetFor(key);
    if (!target) return;
    const modal = document.getElementById(MODAL_ID);
    bootstrap.Modal.getInstance(modal)?.hide();
    window.setTimeout(() => {
      target.scrollIntoView({behavior:'smooth', block:'start'});
      if (key === 'clock') {
        const button = [...target.querySelectorAll('button')].find(item => /Set Time Limit/i.test(item.textContent || ''));
        button?.focus({preventScroll:true});
      }
      if (key === 'starter') {
        document.querySelector('#pregame-defense-editor-v3 [data-pde-pos="P"]')?.focus({preventScroll:true});
      }
    }, 220);
  }

  function enterFullPlan() {
    const modal = document.getElementById(MODAL_ID);
    bootstrap.Modal.getInstance(modal)?.hide();
    window.setTimeout(() => {
      const planner = document.getElementById('game-management-planner-row') || document.getElementById('rotation-card-container');
      planner?.scrollIntoView({behavior:'smooth', block:'start'});
    }, 220);
  }

  function ensureLaunch() {
    if (document.getElementById(LAUNCH_ID)) return;
    const pregame = document.getElementById('pregame-checklist-container');
    if (!pregame) return;
    const launch = document.createElement('div');
    launch.id = LAUNCH_ID;
    launch.innerHTML = `
      <div class="cb-qsl-copy">
        <div class="cb-qsl-title"><i class="bi bi-lightning-charge-fill me-1" aria-hidden="true"></i>Quick Start</div>
        <div class="cb-qsl-help">Get ready for first pitch without planning the whole game. Set availability, Inning 1 defense, pitcher, and pitching tracking. Batting order can be added later.</div>
      </div>
      <button type="button" class="btn btn-primary cb-qsl-button">Open Quick Start</button>`;
    const rules = document.getElementById('game-pitching-rules-v2');
    const readiness = document.getElementById('coach-game-readiness-v2');
    if (rules?.parentNode) rules.insertAdjacentElement('afterend', launch);
    else if (readiness?.parentNode) readiness.insertAdjacentElement('beforebegin', launch);
    else pregame.prepend(launch);
    launch.querySelector('button')?.addEventListener('click', openQuickStart);
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <div class="cb-qs-kicker">Quick Start</div>
              <h5 class="modal-title mb-0">Get ready for first pitch</h5>
              <div class="cb-qs-subtitle">Only the essentials. You can add a batting order and plan later defensive innings during the game.</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body"><div class="cb-qs-list" data-cb-qs-list></div></div>
          <div class="cb-qs-footer">
            <button type="button" class="btn btn-outline-secondary" data-cb-full-plan>Full Game Plan</button>
            <div class="cb-qs-start-slot" data-cb-qs-start-slot></div>
            <div class="cb-qs-blockers" data-cb-qs-blockers></div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('show.bs.modal', () => refresh(true));
    modal.addEventListener('shown.bs.modal', () => moveStartButtonIntoModal(modal));
    modal.addEventListener('hidden.bs.modal', restoreStartButton);
    modal.querySelector('[data-cb-full-plan]')?.addEventListener('click', enterFullPlan);
    return modal;
  }

  function renderModal() {
    const modal = ensureModal();
    const list = modal.querySelector('[data-cb-qs-list]');
    const blockers = modal.querySelector('[data-cb-qs-blockers]');
    if (!list || !blockers) return;

    const steps = setupSteps();
    const markup = steps.map(step => `
      <div class="cb-qs-step ${step.ready ? 'ready' : 'warn'}" data-cb-qs-step="${esc(step.key)}">
        <div class="cb-qs-icon"><i class="bi ${esc(step.icon)}" aria-hidden="true"></i></div>
        <div><div class="cb-qs-name">${esc(step.name)}${step.optional ? ' <span class="text-muted fw-normal">· optional</span>' : ''}</div><div class="cb-qs-status">${esc(step.status)}</div></div>
        <button type="button" class="btn ${step.ready ? 'btn-outline-secondary' : 'btn-outline-primary'} cb-qs-action" data-cb-qs-go="${esc(step.key)}">${step.ready ? 'Review' : 'Set'}</button>
      </div>`).join('');

    if (list.innerHTML !== markup) {
      list.innerHTML = markup;
      list.querySelectorAll('[data-cb-qs-go]').forEach(button => button.addEventListener('click', () => scrollToStep(button.dataset.cbQsGo)));
    }

    if (latest.startReady === true) {
      blockers.className = 'cb-qs-blockers ready';
      blockers.textContent = 'Ready for first pitch. Batting order and later innings remain optional.';
    } else if (latest.startReady === false) {
      blockers.className = 'cb-qs-blockers';
      blockers.textContent = latest.startMissing.length ? `Still needed: ${latest.startMissing.join(' · ')}` : 'Finish the first-pitch setup.';
    } else {
      blockers.className = 'cb-qs-blockers';
      blockers.textContent = 'Checking first-pitch setup…';
    }
  }

  function openQuickStart() {
    const modal = ensureModal();
    renderModal();
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function rewriteLeafText(root, fromPatterns, replacement) {
    if (!root) return;
    [...root.querySelectorAll('*')].forEach(node => {
      if (node.children.length) return;
      const text = String(node.textContent || '').replace(/\s+/g,' ').trim();
      if (fromPatterns.some(pattern => pattern.test(text)) && text !== replacement) node.textContent = replacement;
    });
  }

  function simplifyReadiness() {
    const readiness = document.getElementById('coach-game-readiness-v2');
    if (!readiness) return;
    rewriteLeafText(readiness, [/^WHO['’]S OUT$/i, /^Who['’]s Out$/i], 'Player Availability');
  }

  function decorateRules() {
    const card = document.getElementById('game-pitching-rules-v2');
    if (!card || !latest.rules) return;
    const mode = trackingMode(latest.rules.effective);
    const labels = card.querySelectorAll('.gpr-label');
    const rule = card.querySelector('.gpr-rule');
    if (labels[0] && labels[0].textContent.trim() !== 'Game Tracking') labels[0].textContent = 'Game Tracking';
    if (rule && rule.textContent.trim() !== mode.label) rule.textContent = mode.label;
  }

  function normalizeStartButton() {
    const button = document.getElementById('startLiveGameBtnAction');
    if (!button) return;
    button.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i>START GAME';
    button.title = 'Start Live Game when the server confirms the first-pitch essentials are ready.';
    delete button.dataset.cbStartAllowed;
    delete button.dataset.cbStartMode;
  }

  function runPass() {
    ensureLaunch();
    simplifyReadiness();
    decorateRules();
    normalizeStartButton();
    if (document.getElementById(MODAL_ID)?.classList.contains('show')) renderModal();
  }

  async function refresh(forceModal = false) {
    if (refreshBusy) return;
    refreshBusy = true;
    try {
      const [stateData, readinessData, rulesData] = await Promise.all([
        getJson(`/api/live-game/${gameId}/state`),
        getJson(`/api/game-day/${gameId}/readiness`),
        getJson(`/api/game-day/${gameId}/pitching-rules`),
      ]);
      if (stateData) latest.state = stateData;
      if (readinessData?.readiness) latest.readiness = readinessData.readiness;
      if (typeof readinessData?.ready === 'boolean') latest.startReady = readinessData.ready;
      if (Array.isArray(readinessData?.missing)) latest.startMissing = readinessData.missing;
      if (rulesData) latest.rules = rulesData;

      if (latest.state?.game?.is_live) {
        document.getElementById(LAUNCH_ID)?.remove();
        bootstrap.Modal.getInstance(document.getElementById(MODAL_ID))?.hide();
        return;
      }

      runPass();
      if (forceModal) renderModal();
    } finally {
      refreshBusy = false;
    }
  }

  function init() {
    installStyles();
    ensureModal();
    ensureLaunch();
    normalizeStartButton();
    refresh();
    window.setTimeout(refresh, 900);
    window.setInterval(() => {
      if (!document.hidden && !latest.state?.game?.is_live) refresh();
    }, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
