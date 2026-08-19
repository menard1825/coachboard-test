(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let clock = null;
  let busy = false;
  let patchQueued = false;

  const $ = id => document.getElementById(id);

  function installStyles() {
    if ($('cb-live-clock-controls-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-live-clock-controls-style';
    style.textContent = `
      #cbDugoutHeader [data-cb-clock]{font-size:0!important}
      #cbDugoutHeader [data-cb-clock] i{display:none!important}
      #cbDugoutHeader [data-cb-clock]::after{content:'Clock Controls';font-size:.72rem;font-weight:750}
      body.cb-clock-paused #cbDugoutHeader{border-bottom-color:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-dot{background:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-clock small{font-size:0!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-clock small::after{content:'Time left · Paused';font-size:.55rem;color:#ffd166;font-weight:900}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-time{color:#ffd166!important}
      body.cb-dugout #liveChangePitcherBtn .coach-action-title,
      body.cb-dugout #liveChangePitcherBtn .coach-action-note{font-size:0!important}
      body.cb-dugout #liveChangePitcherBtn .coach-action-title::after{content:'Change Pitcher Now';font-size:1.02rem;font-weight:850}
      body.cb-dugout #liveChangePitcherBtn .coach-action-note::after{content:'Mid-inning pitching change';font-size:.7rem;font-weight:550}
      .cb-mid-inning-help{border:1px solid #b9cbe8;background:#f4f8ff;color:#253858;border-radius:10px;padding:9px 10px;margin-bottom:12px;font-size:.78rem;line-height:1.35}
      .cb-mid-inning-help strong{font-weight:850}
      #cbClockControlsModal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #cbClockControlsModal .cb-clock-state{border-radius:11px;padding:11px 12px;margin-bottom:12px;background:#f8fafc;border:1px solid #dfe4ea}
      #cbClockControlsModal .cb-clock-state.paused{background:#fff8e8;border-color:#e5c66f}
      #cbClockControlsModal .cb-clock-state strong{display:block;font-size:.9rem;color:#172033}
      #cbClockControlsModal .cb-clock-state span{display:block;font-size:.74rem;color:#667085;margin-top:3px;line-height:1.35}
      #cbClockControlsModal .cb-clock-action{min-height:56px;border-radius:11px;font-weight:800;text-align:left;padding:9px 12px}
      #cbClockControlsModal .cb-clock-action small{display:block;font-weight:550;opacity:.78;margin-top:2px}
      #cbClockControlsModal .cb-delay-help{font-size:.72rem;color:#667085;line-height:1.4;margin-top:10px}
      @media(max-width:575.98px){#cbDugoutHeader [data-cb-clock]::after{content:'Clock';font-size:.7rem}}
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = $('cbClockControlsModal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'cbClockControlsModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">Clock Controls</h5>
              <div class="small text-muted">Manage delays or correct the tournament clock.</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="cb-clock-state" id="cbClockControlState"></div>
            <div class="d-grid gap-2">
              <button type="button" class="btn btn-outline-warning cb-clock-action" id="cbPauseResumeClockBtn"></button>
              <button type="button" class="btn btn-outline-secondary cb-clock-action" id="cbAdjustClockBtn">
                <i class="bi bi-sliders me-1"></i> Adjust Clock Settings
                <small>Change the time limit or restart the clock if it was started at the wrong time.</small>
              </button>
            </div>
            <div class="cb-delay-help">
              <strong>For delays:</strong> pause CoachBoard only when the official game/tournament clock is also stopped — for example for rain, lightning, an injury, or a field delay. Pausing CoachBoard does not change the inning, pitcher, defense, or live-game state.
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('#cbPauseResumeClockBtn')?.addEventListener('click', async () => {
      await postClock(clock?.is_paused ? 'resume' : 'pause');
    });

    modal.querySelector('#cbAdjustClockBtn')?.addEventListener('click', () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      setTimeout(() => {
        const config = document.querySelector('#cbLiveGameClock .cb-clock-config');
        if (config) config.click();
        else {
          const configModal = $('cbGameClockConfigModal');
          if (configModal) bootstrap.Modal.getOrCreateInstance(configModal).show();
        }
      }, 180);
    });

    return modal;
  }

  function updateModal() {
    const modal = $('cbClockControlsModal');
    if (!modal) return;
    const paused = Boolean(clock?.is_paused);
    const state = modal.querySelector('#cbClockControlState');
    const button = modal.querySelector('#cbPauseResumeClockBtn');
    if (state) {
      state.classList.toggle('paused', paused);
      state.innerHTML = paused
        ? '<strong><i class="bi bi-pause-circle me-1"></i> Clock is paused</strong><span>Game time is frozen until you resume it. The current inning and defensive state stay exactly where they are.</span>'
        : '<strong><i class="bi bi-clock me-1"></i> Clock is running</strong><span>Use Pause only when the official game clock has also stopped for a delay.</span>';
    }
    if (button) {
      button.className = `btn ${paused ? 'btn-success' : 'btn-outline-warning'} cb-clock-action`;
      button.innerHTML = paused
        ? '<i class="bi bi-play-fill me-1"></i> Resume Clock<small>Continue from the exact time where the delay started.</small>'
        : '<i class="bi bi-pause-fill me-1"></i> Pause for Delay<small>Freeze CoachBoard time for rain, lightning, injury, or another official stoppage.</small>';
      button.disabled = busy;
    }
  }

  function patchPitcherUI() {
    const button = $('liveChangePitcherBtn');
    if (button) {
      button.title = 'Changes the pitcher immediately during the current inning. Use the Next Inning Board for the following inning.';
      button.setAttribute('aria-label', 'Change Pitcher Now — mid-inning pitching change');
    }

    const modal = $('live-pitcher-picker-v2');
    if (!modal) return;
    const title = modal.querySelector('.modal-title');
    if (title && title.textContent !== 'Mid-Inning Pitching Change') {
      title.textContent = 'Mid-Inning Pitching Change';
    }
    const body = modal.querySelector('.modal-body');
    if (body && !body.querySelector('.cb-mid-inning-help')) {
      body.insertAdjacentHTML('afterbegin', `
        <div class="cb-mid-inning-help">
          <strong>This changes the pitcher immediately in the current inning.</strong><br>
          For the pitcher who will start the following inning, use the <strong>Next Inning Board</strong> instead.
        </div>`);
    }
  }

  function patch() {
    patchQueued = false;
    installStyles();
    document.body.classList.toggle('cb-clock-paused', Boolean(clock?.is_paused));
    patchPitcherUI();
    updateModal();
  }

  function queuePatch() {
    if (patchQueued) return;
    patchQueued = true;
    requestAnimationFrame(patch);
  }

  async function fetchClock() {
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`, {cache: 'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      clock = data.clock || null;
      queuePatch();
    } catch (_) {}
  }

  async function postClock(action) {
    if (busy) return;
    busy = true;
    updateModal();
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') {
        throw new Error(data.message || 'Unable to update the game clock.');
      }
      clock = data.clock || clock;
      queuePatch();
      // The dugout header has its own clock poller. Trigger its existing refresh
      // path immediately so Pause/Resume is reflected without waiting for polling.
      document.dispatchEvent(new Event('visibilitychange'));
    } catch (err) {
      window.alert(err.message || 'Unable to update the game clock.');
    } finally {
      busy = false;
      updateModal();
    }
  }

  function openControls() {
    const modal = ensureModal();
    updateModal();
    bootstrap.Modal.getOrCreateInstance(modal).show();
    fetchClock();
  }

  function start() {
    installStyles();
    fetchClock();
    setInterval(fetchClock, 5000);

    document.addEventListener('click', event => {
      const clockButton = event.target.closest('#cbDugoutHeader [data-cb-clock]');
      if (!clockButton) return;
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
      openControls();
    }, true);

    new MutationObserver(queuePatch).observe(document.body, {
      childList: true,
      subtree: true,
    });

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) fetchClock();
    });

    queuePatch();
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once: true})
    : start();
})();
