(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-pitch-step][data-pitch-target]');
    if (!button) return;

    const input = document.getElementById(button.dataset.pitchTarget);
    const delta = Number(button.dataset.pitchStep);
    if (!input || !Number.isFinite(delta)) return;

    const minimum = input.min === '' ? Number.NEGATIVE_INFINITY : Number(input.min);
    const maximum = input.max === '' ? Number.POSITIVE_INFINITY : Number(input.max);
    const current = Number(input.value);
    const startingValue = Number.isFinite(current)
      ? current
      : (Number.isFinite(minimum) ? minimum : 0);
    const next = Math.min(maximum, Math.max(minimum, startingValue + delta));

    input.value = String(next);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  });
})();

(() => {
  'use strict';
  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  function loadOnce(src, datasetKey) {
    if (document.querySelector(`script[data-${datasetKey}]`)) return;
    const script = document.createElement('script');
    script.src = src;
    script.setAttribute(`data-${datasetKey}`, '1');
    document.head.appendChild(script);
  }

  function installCommandCenterCompatibilityStyles() {
    if (document.getElementById('cb-command-center-dugout-compat')) return;
    const style = document.createElement('style');
    style.id = 'cb-command-center-dugout-compat';
    style.textContent = `
      body.cb-dugout .coach-live-head.cb-command-head {
        display:flex!important;
        justify-content:flex-end!important;
        align-items:center!important;
        min-height:46px!important;
        margin:0 0 8px!important;
      }
      body.cb-dugout .coach-live-head.cb-command-head > :first-child,
      body.cb-dugout .coach-live-head.cb-command-head .coach-inning-pill {
        display:none!important;
      }
      body.cb-dugout .coach-live-head.cb-command-head .cb-command-head-tools {
        display:flex!important;
        align-items:center!important;
        justify-content:flex-end!important;
        width:100%!important;
      }
      body.cb-dugout .coach-live-head.cb-command-head #liveUndoBtn.cb-command-undo {
        display:inline-flex!important;
        width:46px!important;
        height:46px!important;
        min-width:46px!important;
        min-height:46px!important;
        padding:0!important;
        border:1px solid #d6dae1!important;
        border-radius:10px!important;
        background:#fff!important;
        color:#475467!important;
        align-items:center!important;
        justify-content:center!important;
      }
      @media(max-width:575.98px) {
        body.cb-dugout .coach-live-head.cb-command-head {
          min-height:44px!important;
        }
        body.cb-dugout .coach-live-head.cb-command-head #liveUndoBtn.cb-command-undo {
          width:44px!important;
          height:44px!important;
          min-width:44px!important;
          min-height:44px!important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function actionMarkup(button, title, note) {
    if (!button) return;
    const wanted = `<span class="coach-action-title">${title}</span><span class="coach-action-note">${note}</span>`;
    if (button.innerHTML !== wanted) button.innerHTML = wanted;
  }

  function ensureCommandCenterActions() {
    const shell = document.querySelector('.coach-live-shell');
    const slot = shell?.querySelector('#coach-action-slot');
    if (!shell || !slot) return;

    let defense = document.getElementById('liveDefensiveChangeBtn');
    if (!defense) {
      defense = document.createElement('button');
      defense.type = 'button';
      defense.id = 'liveDefensiveChangeBtn';
      defense.className = 'btn';
    }

    const pitcher = document.getElementById('liveChangePitcherBtn');
    const endInning = document.getElementById('liveEndInningBtn');
    const undo = document.getElementById('liveUndoBtn');

    actionMarkup(defense, 'Defense Change', 'Move field / bench');
    actionMarkup(pitcher, 'Change Pitcher', 'Make a mound change');
    actionMarkup(endInning, 'End Inning', 'Keep or change defense');

    if (defense.parentElement !== slot) slot.prepend(defense);

    if (undo) {
      const undoMarkup = '<i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i><span class="cb-undo-text">Undo last change</span>';
      undo.classList.add('cb-command-undo');
      if (undo.title !== 'Undo the last live-game change') undo.title = 'Undo the last live-game change';
      if (undo.getAttribute('aria-label') !== 'Undo last change') undo.setAttribute('aria-label', 'Undo last change');
      if (undo.innerHTML !== undoMarkup) undo.innerHTML = undoMarkup;
    }
  }

  function installPitcherStatusStabilizer() {
    let stats = null;
    let statsObserver = null;
    let hostObserver = null;
    let queued = false;

    const normalize = () => {
      if (!stats?.isConnected) return;
      const raw = String(stats.textContent || '').trim();
      if (!raw) return;

      const status = raw.split('•')[0].trim();
      const normalized = status === 'Available' || status === 'Eligible to pitch'
        ? '<span class="ok"><i class="bi bi-check-circle-fill me-1" aria-hidden="true"></i>Eligible to pitch</span>'
        : `<span class="stop"><i class="bi bi-exclamation-triangle-fill me-1" aria-hidden="true"></i>${status}</span>`;

      if (stats.innerHTML === normalized) return;
      statsObserver?.disconnect();
      stats.classList.add('cb-command-pitcher-status');
      stats.innerHTML = normalized;
      statsObserver?.observe(stats, {childList:true, subtree:true, characterData:true});
    };

    const attach = () => {
      const current = document.getElementById('live-pitcher-stats');
      if (!current || current === stats) return Boolean(current);
      statsObserver?.disconnect();
      stats = current;
      statsObserver = new MutationObserver(() => {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(() => {
          queued = false;
          normalize();
        });
      });
      statsObserver.observe(stats, {childList:true, subtree:true, characterData:true});
      normalize();
      return true;
    };

    if (attach()) return;
    hostObserver = new MutationObserver(() => {
      if (!attach()) return;
      hostObserver.disconnect();
      hostObserver = null;
    });
    const overlay = document.getElementById('live-game-overlay') || document.body;
    hostObserver.observe(overlay, {childList:true, subtree:true});
  }

  window.addEventListener('load', () => {
    installCommandCenterCompatibilityStyles();
    loadOnce('/static/js/pregame_starting_defense_scope.js', 'starting-defense-scope');
    loadOnce('/static/js/pregame_quick_start.js', 'pregame-quick-start');
    loadOnce('/static/js/pregame_quick_start_modals.js', 'pregame-quick-start-modals');
    loadOnce('/static/js/live_game_dugout_mode.js', 'live-dugout-mode');
    loadOnce('/static/js/live_game_clock_controls.js', 'live-clock-controls');
    loadOnce('/static/js/live_game_command_center.js', 'live-command-center');
    loadOnce('/static/js/live_game_connection_status.js', 'live-connection-status');
    installPitcherStatusStabilizer();

    // Legacy live helpers can rewrite action labels after the command center first
    // appears. Watch only the live overlay and restore the coach-facing actions
    // there, rather than observing the whole page while the game clock changes.
    const liveOverlay = document.getElementById('live-game-overlay');
    if (liveOverlay) {
      let queued = false;
      const observer = new MutationObserver(() => {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(() => {
          queued = false;
          ensureCommandCenterActions();
        });
      });
      observer.observe(liveOverlay, {childList: true, subtree: true});
    }
    ensureCommandCenterActions();
  }, {once: true});
})();