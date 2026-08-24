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
  let rootObserver = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));
  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setHtml = (el, value) => {
    if (el && el.innerHTML !== value) el.innerHTML = value;
  };

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.cb-dugout #liveDefensiveChangeBtn,
      body.cb-dugout #liveSetDefenseBtnCoach,
      body.cb-dugout [data-cb-full-defense] {
        display:none!important;
      }
      body.cb-dugout #cbQuickDefense .cb-qd-actions {
        display:none!important;
      }
      body.cb-dugout #coach-action-slot.coach-actions {
        grid-template-columns:repeat(2,minmax(0,1fr))!important;
        gap:9px!important;
      }
      body.cb-dugout #liveChangePitcherBtn,
      body.cb-dugout #liveEndInningBtn {
        min-height:62px!important;
      }
      body.cb-dugout #liveUndoBtn {
        grid-column:1/-1!important;
        width:auto!important;
        min-height:28px!important;
        justify-self:center!important;
        border:0!important;
        background:transparent!important;
        color:#667085!important;
        padding:3px 10px!important;
        box-shadow:none!important;
      }
      body.cb-dugout #liveUndoBtn .coach-action-title {
        font-size:.74rem!important;
        text-decoration:underline;
        text-underline-offset:2px;
      }
      body.cb-dugout #liveUndoBtn .coach-action-note {
        display:none!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-note,
      body.cb-dugout #liveEndInningBtn .coach-action-note {
        font-size:0!important;
        opacity:.78!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-note::after {
        content:'This inning';
        font-size:.67rem;
      }
      body.cb-dugout #liveEndInningBtn .coach-action-note::after {
        content:'Send next defense out';
        font-size:.67rem;
      }
      body.cb-dugout #cbQuickDefense .cb-qd-bench {
        display:flex!important;
        visibility:visible!important;
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
        html body.cb-dugout #cbQuickDefense .cb-qd-head{
          padding:8px 9px 7px!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-title{
          font-size:.9rem!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-help{
          font-size:.64rem!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-body{
          padding:6px 7px 8px!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-field{
          min-height:0!important;
          max-height:228px!important;
          aspect-ratio:1.58/1!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-spot{
          width:61px!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-name{
          font-size:.55rem!important;
          padding:3px 4px!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap{
          margin-top:6px!important;
          padding:7px!important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-player{
          padding:6px 7px!important;
          font-size:.66rem!important;
        }
        body.cb-dugout #coach-action-slot.coach-actions{
          position:sticky;
          bottom:0;
          z-index:1030;
          background:#eef1f4;
          padding:7px 0 calc(7px + env(safe-area-inset-bottom));
          margin-bottom:8px!important;
        }
        body.cb-dugout #liveChangePitcherBtn,
        body.cb-dugout #liveEndInningBtn{
          min-height:56px!important;
        }
        #${END_MODAL_ID} .modal-dialog{margin:.5rem}
      }
      @media(orientation:landscape) and (max-height:599.98px){
        html body.cb-dugout #cbQuickDefense .cb-qd-field{
          max-height:205px!important;
          width:min(62vw,480px)!important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function removeBulkDefense() {
    document.getElementById('liveSetDefenseBtnCoach')?.remove();
    document.getElementById('live-bulk-defense-coach')?.remove();
    document.querySelectorAll('[data-cb-full-defense]').forEach(button => button.remove());
  }

  function patchQuickDefense() {
    removeBulkDefense();
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;

    setText(card.querySelector('.cb-qd-kicker'),'ON THE FIELD');
    setText(card.querySelector('.cb-qd-title'),'Defense Now');
    setText(card.querySelector('.cb-qd-help'),'Tap a fielder or bench player to make one sub.');

    const benchTitle = card.querySelector('.cb-qd-bench-head strong');
    if (benchTitle && /^Bench now/i.test(benchTitle.textContent || '')) {
      setText(benchTitle,benchTitle.textContent.replace(/^Bench now/i,'On the Bench'));
    }

    card.querySelectorAll('.cb-bench-note').forEach(note => {
      const text = (note.textContent || '').trim();
      if (text === 'Bench now' || text === 'On the bench') {
        note.textContent = '';
        note.style.display = 'none';
      }
    });

    const tools = card.querySelector('.cb-qd-actions');
    if (tools) tools.remove();
    setText(document.querySelector('.cb-end-zone small'),'After the last out');
  }

  function patchMenu() {
    const modal = document.getElementById('cbCoachBoardNavModal');
    if (!modal) return;
    setText(modal.querySelector('.modal-header .small.text-muted'),'Game stays live.');
    setHtml(modal.querySelector('.cb-nav-safe'),'<strong>Game stays live.</strong> Clock stays as-is.');
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
      const synced = await window.CBNextDefense?.syncSamePointer?.();
      if (synced === null) throw new Error('Could not refresh the next defense.');

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
      },50);
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

  function attachQuickDefenseObserver() {
    const card = document.getElementById('cbQuickDefense');
    if (!card) return false;
    patchQuickDefense();
    if (!quickDefenseObserver) {
      quickDefenseObserver = new MutationObserver(() => requestAnimationFrame(patchQuickDefense));
      quickDefenseObserver.observe(card,{childList:true,subtree:true});
    }
    return true;
  }

  function start() {
    installStyles();
    document.getElementById('cbCurrentInningStrip')?.remove();
    removeBulkDefense();
    document.addEventListener('click',guardEndInning,true);
    document.addEventListener('click',event => {
      if (event.target.closest?.('[data-cb-menu], #cbCoachBoardNavBtn')) window.setTimeout(patchMenu,0);
    },true);

    document.addEventListener('coachboard:next-defense-set', () => {
      if (!endAfterNextDefense) return;
      endAfterNextDefense = false;
      window.setTimeout(endInningNow,80);
    });

    if (!attachQuickDefenseObserver()) {
      rootObserver = new MutationObserver(() => {
        removeBulkDefense();
        if (!attachQuickDefenseObserver()) return;
        rootObserver?.disconnect();
        rootObserver = null;
      });
      rootObserver.observe(document.body,{childList:true,subtree:true});
    }
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();
