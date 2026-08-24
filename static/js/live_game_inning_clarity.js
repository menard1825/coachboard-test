(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const STYLE_ID = 'cb-live-dugout-workflow-style';
  const END_MODAL_ID = 'cbEndInningSheet';
  let ending = false;
  let endAfterNextDefense = false;
  let quickDefenseObserver = null;
  let actionObserver = null;
  let rootObserver = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.cb-dugout #liveDefensiveChangeBtn,
      body.cb-dugout #liveSetDefenseBtnCoach {
        display:none!important;
      }
      body.cb-dugout #coach-action-slot.coach-actions {
        grid-template-columns:repeat(2,minmax(0,1fr))!important;
        gap:9px!important;
      }
      body.cb-dugout #liveChangePitcherBtn,
      body.cb-dugout #liveEndInningBtn {
        min-height:64px!important;
      }
      body.cb-dugout #liveUndoBtn {
        grid-column:1/-1!important;
        min-height:40px!important;
        border-width:1px!important;
        padding:6px 10px!important;
      }
      body.cb-dugout #liveUndoBtn .coach-action-title {
        font-size:.78rem!important;
      }
      body.cb-dugout #liveUndoBtn .coach-action-note {
        display:none!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-title,
      body.cb-dugout #liveEndInningBtn .coach-action-title {
        font-size:1rem!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-note,
      body.cb-dugout #liveEndInningBtn .coach-action-note {
        font-size:.67rem!important;
        opacity:.78!important;
      }
      #${END_MODAL_ID} .modal-content {
        border:0;
        border-radius:15px;
        overflow:hidden;
      }
      #${END_MODAL_ID} .cb-end-actions {
        display:grid;
        gap:9px;
      }
      #${END_MODAL_ID} .cb-end-actions .btn {
        min-height:58px;
        border-radius:11px;
        font-weight:850;
        text-align:left;
        padding:10px 12px;
      }
      #${END_MODAL_ID} .cb-end-actions small {
        display:block;
        margin-top:2px;
        font-size:.68rem;
        font-weight:550;
        opacity:.78;
      }
      @media(max-width:575.98px){
        #${END_MODAL_ID} .modal-dialog{margin:.5rem}
      }
    `;
    document.head.appendChild(style);
  }

  function setAction(button, title, note='') {
    if (!button) return;
    const titleEl = button.querySelector('.coach-action-title');
    const noteEl = button.querySelector('.coach-action-note');
    if (titleEl) titleEl.textContent = title;
    if (noteEl) noteEl.textContent = note;
    button.title = note ? `${title} — ${note}` : title;
    button.setAttribute('aria-label', note ? `${title}. ${note}.` : title);
  }

  function patchActions() {
    document.getElementById('cbCurrentInningStrip')?.remove();
    setAction(document.getElementById('liveChangePitcherBtn'), 'Change Pitcher', 'This inning');
    setAction(document.getElementById('liveEndInningBtn'), 'End Inning', 'Send next defense out');
    setAction(document.getElementById('liveUndoBtn'), 'Undo');
  }

  function patchQuickDefense() {
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;
    const kicker = card.querySelector('.cb-qd-kicker');
    const title = card.querySelector('.cb-qd-title');
    const help = card.querySelector('.cb-qd-help');
    const benchTitle = card.querySelector('.cb-qd-bench-head strong');
    const tip = card.querySelector('.cb-qd-tip');
    const full = card.querySelector('[data-cb-full-defense]');
    if (kicker) kicker.textContent = 'ON THE FIELD';
    if (title) title.textContent = 'Defense Now';
    if (help) help.textContent = 'Tap a fielder or bench player to move him.';
    if (benchTitle) benchTitle.textContent = benchTitle.textContent.replace(/^Bench now/i, 'On the Bench');
    if (tip) tip.textContent = 'Tap a bench player, then the position. The player coming out goes to the bench.';
    if (full) full.innerHTML = '<i class="bi bi-sliders me-1"></i>Change Several Positions';
    card.querySelectorAll('.cb-bench-note').forEach(note => {
      if ((note.textContent || '').trim() === 'Bench now') note.textContent = 'On the bench';
    });
  }

  function toast(message, kind='success') {
    let host = document.getElementById('cb-live-workflow-toast');
    if (!host) {
      host = document.createElement('div');
      host.id = 'cb-live-workflow-toast';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '5000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:2200});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  async function endInningNow() {
    if (ending) return;
    ending = true;
    const button = document.getElementById('liveEndInningBtn');
    if (button) button.disabled = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/end-inning`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:'{}'
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to end inning (${response.status}).`);
      const inning = data.state?.current_inning;
      toast(inning ? `Inning ${inning}` : 'Inning advanced');
      window.CBNextDefense?.refresh?.();
    } catch (err) {
      toast(err.message,'danger');
    } finally {
      ending = false;
      if (button) button.disabled = false;
    }
  }

  function nextDefenseReady() {
    return Boolean(document.querySelector('#live-board-prep-v3 .nxd-status.ready, #live-board-prep-v3 .bp-status.ready'));
  }

  function ensureEndModal() {
    let modal = document.getElementById(END_MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = END_MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">End Inning</h5>
              <div class="small text-muted">Who goes back out?</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="cb-end-actions">
              <button type="button" class="btn btn-primary" data-cb-end-same>
                Same Defense
                <small>Send them back out as-is.</small>
              </button>
              <button type="button" class="btn btn-outline-primary" data-cb-end-new>
                New Defense
                <small>Set who takes the field next inning.</small>
              </button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('[data-cb-end-same]')?.addEventListener('click', async () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      const data = await window.CBNextDefense?.useSame?.();
      if (data) await endInningNow();
    });

    modal.querySelector('[data-cb-end-new]')?.addEventListener('click', () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      endAfterNextDefense = true;
      window.CBNextDefense?.openNew?.();
      window.setTimeout(() => {
        const adjust = document.getElementById('next-inning-adjust-modal');
        if (!adjust) return;
        adjust.addEventListener('hidden.bs.modal', () => {
          if (endAfterNextDefense) endAfterNextDefense = false;
        }, {once:true});
      }, 50);
    });
    return modal;
  }

  function guardEndInning(event) {
    const button = event.target.closest?.('#liveEndInningBtn');
    if (!button || button.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    if (nextDefenseReady()) {
      endInningNow();
      return;
    }
    bootstrap.Modal.getOrCreateInstance(ensureEndModal()).show();
  }

  function attachObservers() {
    const actions = document.getElementById('coach-action-slot');
    if (actions && !actionObserver) {
      patchActions();
      actionObserver = new MutationObserver(() => requestAnimationFrame(patchActions));
      actionObserver.observe(actions,{childList:true,subtree:true});
    }

    const quick = document.getElementById('cbQuickDefense');
    if (quick && !quickDefenseObserver) {
      patchQuickDefense();
      quickDefenseObserver = new MutationObserver(() => requestAnimationFrame(patchQuickDefense));
      quickDefenseObserver.observe(quick,{childList:true,subtree:true});
    }

    if (actions && quick && rootObserver) {
      rootObserver.disconnect();
      rootObserver = null;
    }
  }

  function start() {
    installStyles();
    document.addEventListener('click',guardEndInning,true);
    document.addEventListener('coachboard:next-defense-set', () => {
      if (!endAfterNextDefense) return;
      endAfterNextDefense = false;
      window.setTimeout(endInningNow,80);
    });
    attachObservers();
    if (!document.getElementById('coach-action-slot') || !document.getElementById('cbQuickDefense')) {
      rootObserver = new MutationObserver(attachObservers);
      rootObserver.observe(document.body,{childList:true,subtree:true});
    }
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();