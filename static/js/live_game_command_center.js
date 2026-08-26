(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let liveState = null;
  let readiness = null;
  let ruleState = null;
  let refreshBusy = false;
  let observerBusy = false;

  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (byId('cb-command-center-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-command-center-styles';
    style.textContent = `
      #cb-quick-start-note{border-radius:11px;padding:10px 12px;margin:0 0 10px;font-size:.74rem;line-height:1.35}
      #cb-quick-start-note.ready{border:1px solid #b9dcc4;background:#f5fbf7;color:#205b35}
      #cb-quick-start-note.quick{border:1px solid #d5dff4;background:#f7f9ff;color:#294a84}
      #cb-quick-start-note.blocked{border:1px solid #ead7b5;background:#fffaf1;color:#805710}
      #cb-quick-start-note strong{display:block;font-size:.78rem;margin-bottom:2px}
      #startLiveGameBtnAction[data-cb-start-mode="quick"]{background:#123b76;border-color:#123b76}
      .coach-live-head.cb-command-head{align-items:center!important}
      .cb-command-head-tools{display:flex;align-items:center;gap:7px;flex-shrink:0}
      #liveUndoBtn.cb-command-undo{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:46px!important;height:46px!important;min-height:46px!important;padding:0!important;border-radius:10px!important;background:#fff!important;border:1px solid #d6dae1!important;color:#475467!important;box-shadow:none!important;flex:none!important}
      #liveUndoBtn.cb-command-undo i{display:inline-block!important;font-size:1.15rem!important;margin:0!important}
      #liveUndoBtn.cb-command-undo .cb-undo-text{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
      .coach-actions.cb-command-actions{grid-template-columns:1fr 1fr!important;gap:8px!important}
      .coach-actions.cb-command-actions #liveDefensiveChangeBtn{order:1;background:var(--primary-color,#102a66)!important;border-color:var(--primary-color,#102a66)!important;color:#fff!important}
      .coach-actions.cb-command-actions #liveChangePitcherBtn{order:2;background:#fff!important;border:1px solid #aab4c3!important;color:#26364c!important}
      .coach-actions.cb-command-actions #liveEndInningBtn{order:3;grid-column:1/-1;background:#202733!important;border-color:#202733!important;color:#fff!important}
      .coach-actions.cb-command-actions .btn{min-height:58px!important}
      .cb-command-pitcher-status{font-size:.74rem!important;color:#667085!important;line-height:1.3!important}
      .cb-command-pitcher-status .ok{color:#176b38;font-weight:800}
      .cb-command-pitcher-status .stop{color:#a32929;font-weight:800}
      .cb-command-pitcher-status .next{color:#7b6241;font-weight:700}
      #liveEndGameBtn{min-height:44px;border-radius:10px;font-weight:750}
      @media(max-width:575.98px){
        #cb-quick-start-note{font-size:.7rem;padding:9px 10px}
        .coach-live-head.cb-command-head{gap:8px!important}
        .cb-command-head-tools{gap:5px}
        #liveUndoBtn.cb-command-undo{width:44px!important;height:44px!important;min-height:44px!important}
        .coach-actions.cb-command-actions .btn{min-height:60px!important}
      }
    `;
    document.head.appendChild(style);
  }

  async function getJson(path) {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) return null;
    return response.json().catch(() => null);
  }

  function rulesSelected() {
    return Boolean(ruleState?.effective);
  }

  function inningOneAlignment() {
    return liveState?.actual_rotation?.['1'] || liveState?.current_alignment || {};
  }

  function startingPitcherDecision() {
    const name = inningOneAlignment()?.P || null;
    if (!name) return {name: null, available: false, status: 'Starting pitcher needed', next: null};
    const summary = liveState?.pitch_count_summary?.[name] || {};
    const status = String(summary.status || '').trim() || 'Eligibility unknown';
    return {
      name,
      available: status === 'Available',
      status,
      next: summary.next_available || null,
    };
  }

  function inningOneComplete() {
    if (!readiness) return false;
    const incomplete = Array.isArray(readiness.incomplete_innings) ? readiness.incomplete_innings : [];
    return !incomplete.some(item => String(item?.inning) === '1');
  }

  function quickStartStatus() {
    const pitcher = startingPitcherDecision();
    const reasons = [];

    if (!readiness || !liveState || !ruleState) reasons.push('Checking game setup…');
    else {
      if (!(Number(readiness.present_count || 0) > 0)) reasons.push("Set Who's Out");
      if (!readiness.lineup_ready) reasons.push('Set the batting order');
      if (!inningOneComplete()) reasons.push('Finish the 1st-inning defense');
      if (!pitcher.name) reasons.push('Choose the starting pitcher');
      if (!rulesSelected()) reasons.push('Select the game pitching rules');
      if (pitcher.name && !pitcher.available) reasons.push(`${pitcher.name}: ${pitcher.status}`);
    }

    const coreReady = reasons.length === 0;
    const fullReady = coreReady && Boolean(readiness?.ready);
    return {coreReady, fullReady, reasons, pitcher};
  }

  function ensureQuickStartNote(button) {
    let note = byId('cb-quick-start-note');
    if (!note) {
      note = document.createElement('div');
      note.id = 'cb-quick-start-note';
      note.setAttribute('role', 'status');
      button.parentElement?.insertAdjacentElement('beforebegin', note);
    }
    return note;
  }

  function setStartButtonText(button, label, icon = 'bi-play-circle-fill') {
    const wanted = `<i class="bi ${icon} me-2"></i>${label}`;
    if (button.innerHTML !== wanted) button.innerHTML = wanted;
  }

  function polishSavedDefenseLanguage() {
    const panel = byId('pregame-defense-editor-v3');
    if (!panel) return;

    const label = panel.querySelector('.gm-preset-label');
    if (label && label.textContent !== 'Saved Defense · This Inning Only') {
      label.textContent = 'Saved Defense · This Inning Only';
    }

    const help = panel.querySelector('.gm-preset-help');
    if (help && !help.textContent.includes('Full-game plans are under Defense Options.')) {
      help.textContent = 'Applies only to this inning. Full-game plans are under Defense Options.';
    }

    const select = byId('pde-preset');
    if (select?.options?.length && select.options[0].textContent !== 'Choose a saved defense…') {
      select.options[0].textContent = 'Choose a saved defense…';
    }
  }

  function applyStartMode() {
    const button = byId('startLiveGameBtnAction');
    if (!button || liveState?.game?.is_live) return;

    const oldFeedback = byId('start-live-blockers');
    if (oldFeedback) oldFeedback.classList.add('d-none');

    const note = ensureQuickStartNote(button);
    const status = quickStartStatus();
    button.dataset.cbStartAllowed = status.coreReady ? '1' : '0';

    if (status.fullReady) {
      button.dataset.cbStartMode = 'full';
      button.disabled = false;
      button.classList.remove('disabled');
      setStartButtonText(button, 'START LIVE GAME');
      note.className = 'ready';
      note.innerHTML = '<strong>Ready for first pitch.</strong>Your full defensive plan is set. You can still make changes live.';
      return;
    }

    if (status.coreReady) {
      button.dataset.cbStartMode = 'quick';
      button.disabled = false;
      button.classList.remove('disabled');
      setStartButtonText(button, 'START WITH INNING 1', 'bi-lightning-charge-fill');
      note.className = 'quick';
      note.innerHTML = '<strong>Inning 1 is ready.</strong>Start now and set later innings between innings. CoachBoard will keep the current defense unless you choose a new one.';
      return;
    }

    button.dataset.cbStartMode = 'blocked';
    button.disabled = true;
    button.classList.add('disabled');
    setStartButtonText(button, 'START LIVE GAME');
    note.className = 'blocked';
    const detail = status.reasons.length ? status.reasons.map(esc).join(' · ') : 'Finish the 1st-inning setup.';
    note.innerHTML = `<strong>Before first pitch</strong>${detail}`;
  }

  function concisePitcherStatus() {
    const name = liveState?.current_pitcher || byId('live-current-pitcher')?.textContent?.trim();
    const stats = byId('live-pitcher-stats');
    if (!stats || !name || name === 'None') return;

    const summary = liveState?.pitch_count_summary?.[name] || {};
    const status = String(summary.status || 'Eligibility unknown');
    let html;
    if (status === 'Available') {
      html = '<span class="ok"><i class="bi bi-check-circle-fill me-1"></i>Eligible to pitch</span>';
    } else {
      const next = summary.next_available && summary.next_available !== 'Today'
        ? `<span class="next"> · Next: ${esc(summary.next_available)}</span>`
        : '';
      html = `<span class="stop"><i class="bi bi-exclamation-triangle-fill me-1"></i>${esc(status)}</span>${next}`;
    }

    stats.classList.add('cb-command-pitcher-status');
    if (stats.innerHTML !== html) stats.innerHTML = html;
  }

  function actionMarkup(button, title, note) {
    if (!button) return;
    const wanted = `<span class="coach-action-title">${esc(title)}</span><span class="coach-action-note">${esc(note)}</span>`;
    if (button.innerHTML !== wanted) button.innerHTML = wanted;
  }

  function configureLiveCommandCenter() {
    if (!liveState?.game?.is_live) return;

    const shell = document.querySelector('.coach-live-shell');
    const head = shell?.querySelector('.coach-live-head');
    const slot = shell?.querySelector('#coach-action-slot');
    let defense = byId('liveDefensiveChangeBtn');
    const pitcher = byId('liveChangePitcherBtn');
    const endInning = byId('liveEndInningBtn');
    const undo = byId('liveUndoBtn');

    if (slot && !defense) {
      defense = document.createElement('button');
      defense.type = 'button';
      defense.id = 'liveDefensiveChangeBtn';
      defense.className = 'btn';
    }

    if (head) {
      head.classList.add('cb-command-head');
      let tools = head.querySelector('.cb-command-head-tools');
      const pill = head.querySelector('.coach-inning-pill');
      if (!tools) {
        tools = document.createElement('div');
        tools.className = 'cb-command-head-tools';
        if (pill) {
          pill.insertAdjacentElement('beforebegin', tools);
          tools.appendChild(pill);
        } else {
          head.appendChild(tools);
        }
      }
      if (undo) {
        undo.className = 'btn cb-command-undo';
        undo.title = 'Undo the last live-game change';
        undo.setAttribute('aria-label', 'Undo last change');
        undo.innerHTML = '<i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i><span class="cb-undo-text">Undo last change</span>';
        tools.appendChild(undo);
      }
    }

    if (slot) {
      slot.classList.add('cb-command-actions');
      actionMarkup(defense, 'Defense Change', 'Move field / bench');
      actionMarkup(pitcher, 'Change Pitcher', 'Make a mound change');
      actionMarkup(endInning, 'End Inning', 'Keep or change defense');
      [defense, pitcher, endInning].filter(Boolean).forEach(button => slot.appendChild(button));
    }

    const endGame = byId('liveEndGameBtn');
    if (endGame) {
      endGame.innerHTML = '<i class="bi bi-stop-circle-fill me-1"></i> End Game';
      endGame.title = 'Save the defensive history and go to the Game Report. Enter GameChanger pitching stats when ready.';
    }

    concisePitcherStatus();
  }

  async function refresh() {
    if (refreshBusy) return;
    refreshBusy = true;
    try {
      const [stateData, readinessData, rulesData] = await Promise.all([
        getJson(`/api/live-game/${gameId}/state`),
        getJson(`/api/game-day/${gameId}/readiness`),
        getJson(`/api/game-day/${gameId}/pitching-rules`),
      ]);
      if (stateData) liveState = stateData;
      if (readinessData?.readiness) readiness = readinessData.readiness;
      if (rulesData) ruleState = rulesData;

      polishSavedDefenseLanguage();
      if (liveState?.game?.is_live) configureLiveCommandCenter();
      else applyStartMode();
    } finally {
      refreshBusy = false;
    }
  }

  function refreshImmediatelyAfterStart() {
    [80, 220, 500].forEach(delay => window.setTimeout(refresh, delay));
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('#startLiveGameBtnAction');
    if (!button || liveState?.game?.is_live) return;
    if (button.dataset.cbStartAllowed === '1') {
      // The authoritative Live Game controller starts the game on this same
      // click. Refresh promptly so the command center replaces the pregame
      // layout immediately instead of waiting for the 4-second poll.
      refreshImmediatelyAfterStart();
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    applyStartMode();
  }, true);

  const observer = new MutationObserver(() => {
    if (observerBusy) return;
    observerBusy = true;
    window.requestAnimationFrame(() => {
      try {
        polishSavedDefenseLanguage();
        const oldFeedback = byId('start-live-blockers');
        if (oldFeedback && !liveState?.game?.is_live) oldFeedback.classList.add('d-none');
        if (liveState?.game?.is_live) configureLiveCommandCenter();
      } finally {
        observerBusy = false;
      }
    });
  });

  function start() {
    installStyles();
    const startButton = byId('startLiveGameBtnAction');
    if (startButton && !byId('cb-quick-start-note')) {
      startButton.disabled = true;
      startButton.dataset.cbStartAllowed = '0';
    }
    polishSavedDefenseLanguage();
    observer.observe(document.body, {childList: true, subtree: true, characterData: true});
    refresh();
    window.setInterval(refresh, 4000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once: true});
  } else {
    start();
  }
})();