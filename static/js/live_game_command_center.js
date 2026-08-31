(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let liveState = null;
  let refreshBusy = false;
  let pitcherObserver = null;
  let observedPitcherStats = null;
  let pitcherObserverBusy = false;

  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (byId('cb-command-center-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-command-center-styles';
    style.textContent = `
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

  function observePitcherStatus() {
    const stats = byId('live-pitcher-stats');
    if (!stats || stats === observedPitcherStats) return;

    pitcherObserver?.disconnect();
    observedPitcherStats = stats;
    pitcherObserver = new MutationObserver(() => {
      if (pitcherObserverBusy) return;
      pitcherObserverBusy = true;
      window.requestAnimationFrame(() => {
        try { concisePitcherStatus(); }
        finally { pitcherObserverBusy = false; }
      });
    });
    pitcherObserver.observe(stats, {childList: true, subtree: true, characterData: true});
  }

  function actionMarkup(button, title, note) {
    if (!button) return;
    const wanted = `<span class="coach-action-title">${esc(title)}</span><span class="coach-action-note">${esc(note)}</span>`;
    if (button.innerHTML !== wanted) button.innerHTML = wanted;
  }

  function liveShellVisible() {
    const overlay = byId('live-game-overlay');
    return Boolean(
      overlay &&
      !overlay.classList.contains('d-none') &&
      overlay.querySelector('.coach-live-shell')
    );
  }

  function configureLiveCommandCenter() {
    if (!liveState?.game?.is_live && !liveShellVisible()) return;

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
        const undoMarkup = '<i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i><span class="cb-undo-text">Undo last change</span>';
        if (undo.className !== 'btn cb-command-undo') undo.className = 'btn cb-command-undo';
        if (undo.title !== 'Undo the last live-game change') undo.title = 'Undo the last live-game change';
        if (undo.getAttribute('aria-label') !== 'Undo last change') undo.setAttribute('aria-label', 'Undo last change');
        if (undo.innerHTML !== undoMarkup) undo.innerHTML = undoMarkup;
        if (undo.parentElement !== tools) tools.appendChild(undo);
      }
    }

    if (slot) {
      slot.classList.add('cb-command-actions');
      actionMarkup(defense, 'Defense Change', 'Move field / bench');
      actionMarkup(pitcher, 'Change Pitcher', 'Make a mound change');
      actionMarkup(endInning, 'End Inning', 'Keep or change defense');
      [defense, pitcher, endInning].filter(Boolean).forEach(button => {
        if (button.parentElement !== slot) slot.appendChild(button);
      });
    }

    const endGame = byId('liveEndGameBtn');
    if (endGame) {
      const endMarkup = '<i class="bi bi-stop-circle-fill me-1"></i> End Game';
      if (endGame.innerHTML !== endMarkup) endGame.innerHTML = endMarkup;
      endGame.title = 'Save the defensive history and go to the Game Report. Enter GameChanger pitching stats when ready.';
    }

    concisePitcherStatus();
    observePitcherStatus();
  }

  function configureWhenShellReady(attempt = 0) {
    if (liveShellVisible() && document.querySelector('.coach-live-shell #coach-action-slot')) {
      configureLiveCommandCenter();
      return;
    }
    if (attempt >= 100) return;
    window.setTimeout(() => configureWhenShellReady(attempt + 1), 50);
  }

  async function refreshLiveState() {
    if (refreshBusy) return;
    refreshBusy = true;
    try {
      const stateData = await getJson(`/api/live-game/${gameId}/state`);
      if (stateData) liveState = stateData;
      if (liveState?.game?.is_live || liveShellVisible()) configureWhenShellReady();
    } finally {
      refreshBusy = false;
    }
  }

  function start() {
    installStyles();
    refreshLiveState();

    // This module owns only the live command-center presentation. Pregame start
    // readiness is server-owned and rendered by the dedicated setup UI.
    window.setInterval(() => {
      if (document.hidden) return;
      if (!(liveState?.game?.is_live || liveShellVisible())) return;
      refreshLiveState();
    }, 15000);

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refreshLiveState();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once: true});
  } else {
    start();
  }
})();
