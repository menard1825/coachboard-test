(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const MODAL_ID = 'cbClockControlsModal';
  let clock = null;
  let busy = false;
  let headerObserver = null;
  let rootObserver = null;

  const $ = id => document.getElementById(id);

  function installStyles() {
    if ($('cb-live-time-limit-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-live-time-limit-style';
    style.textContent = `
      #cbDugoutHeader [data-cb-clock] i{display:none!important}
      #${MODAL_ID} .modal-content{border:0;border-radius:15px;overflow:hidden}
      #${MODAL_ID} .tl-state{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:10px 11px;margin-bottom:11px}
      #${MODAL_ID} .tl-state.paused{background:#fff8e8;border-color:#e5c66f}
      #${MODAL_ID} .tl-state strong{display:block;font-size:.88rem;color:#172033}
      #${MODAL_ID} .tl-state span{display:block;font-size:.72rem;color:#667085;margin-top:2px}
      #${MODAL_ID} .tl-action{min-height:54px;border-radius:11px;font-weight:820;text-align:left;padding:9px 11px}
      #${MODAL_ID} .tl-action small{display:block;font-size:.66rem;font-weight:550;opacity:.78;margin-top:2px}
      body.cb-clock-paused #cbDugoutHeader{border-bottom-color:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-dot{background:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-time{color:#ffd166!important}
      @media(max-width:575.98px){#cbDugoutHeader [data-cb-clock]{font-size:.68rem!important;padding:.35rem .5rem!important}}
    `;
    document.head.appendChild(style);
  }

  function patchHeaderButton() {
    const button = document.querySelector('#cbDugoutHeader [data-cb-clock]');
    if (!button) return false;
    if (button.textContent.trim() !== 'Time Limit') button.textContent = 'Time Limit';
    button.setAttribute('aria-label','Time Limit');
    return true;
  }

  function ensureModal() {
    let modal = $(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">Time Limit</h5>
              <div class="small text-muted">Game clock</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="tl-state" data-tl-state></div>
            <div class="d-grid gap-2">
              <button type="button" class="btn btn-outline-warning tl-action" data-tl-pause></button>
              <button type="button" class="btn btn-outline-secondary tl-action" data-tl-adjust>
                Adjust Time Limit
                <small>Change or correct the game time.</small>
              </button>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Back to Game</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('[data-tl-pause]')?.addEventListener('click', async () => {
      await postClock(clock?.is_paused ? 'resume' : 'pause');
    });
    modal.querySelector('[data-tl-adjust]')?.addEventListener('click', () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      window.setTimeout(() => {
        const config = document.querySelector('#cbLiveGameClock .cb-clock-config');
        if (config) config.click();
        else {
          const configModal = $('cbGameClockConfigModal');
          if (configModal) bootstrap.Modal.getOrCreateInstance(configModal).show();
        }
      },160);
    });
    return modal;
  }

  function updateModal() {
    const modal = $(MODAL_ID);
    if (!modal) return;
    const paused = Boolean(clock?.is_paused);
    const state = modal.querySelector('[data-tl-state]');
    const button = modal.querySelector('[data-tl-pause]');
    if (state) {
      state.classList.toggle('paused',paused);
      state.innerHTML = paused
        ? '<strong>Paused</strong><span>Time limit is stopped.</span>'
        : '<strong>Running</strong><span>Time limit is running.</span>';
    }
    if (button) {
      button.className = `btn ${paused ? 'btn-success' : 'btn-outline-warning'} tl-action`;
      button.innerHTML = paused
        ? 'Resume Time<small>Continue the game clock.</small>'
        : 'Pause for Delay<small>Rain, injury, or another official stoppage.</small>';
      button.disabled = busy;
    }
    document.body.classList.toggle('cb-clock-paused',paused);
  }

  async function fetchClock() {
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`,{cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      clock = data.clock || null;
      updateModal();
    } catch (_) {}
  }

  async function postClock(action) {
    if (busy) return;
    busy = true;
    updateModal();
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action})
      });
      const data = await response.json().catch(()=>({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to change the time limit.');
      clock = data.clock || clock;
      updateModal();
      document.dispatchEvent(new Event('visibilitychange'));
    } catch (err) {
      window.alert(err.message || 'Unable to change the time limit.');
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

  function attachHeaderObserver() {
    const header = $('cbDugoutHeader');
    if (!header) return false;
    patchHeaderButton();
    if (!headerObserver) {
      headerObserver = new MutationObserver(() => requestAnimationFrame(patchHeaderButton));
      headerObserver.observe(header,{childList:true,subtree:true});
    }
    return true;
  }

  function start() {
    installStyles();
    fetchClock();
    window.setInterval(fetchClock,5000);

    document.addEventListener('click',event => {
      const button = event.target.closest('#cbDugoutHeader [data-cb-clock]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      openControls();
    },true);

    if (!attachHeaderObserver()) {
      rootObserver = new MutationObserver(() => {
        if (!attachHeaderObserver()) return;
        rootObserver?.disconnect();
        rootObserver = null;
      });
      rootObserver.observe(document.body,{childList:true,subtree:true});
    }

    document.addEventListener('visibilitychange',()=>{ if (!document.hidden) fetchClock(); });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();