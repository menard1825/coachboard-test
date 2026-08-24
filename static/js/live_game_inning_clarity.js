(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const STYLE_ID = 'cb-inning-clarity-style';
  const END_MODAL_ID = 'cbNextInningRequiredModal';
  let queued = false;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .cb-current-inning-strip {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        margin:0 0 8px;
        padding:8px 10px;
        border:1px solid #c9d6e8;
        border-radius:10px;
        background:#f5f8fc;
        color:#344054;
      }
      .cb-current-inning-strip strong {
        display:block;
        font-size:.68rem;
        font-weight:900;
        text-transform:uppercase;
        letter-spacing:.08em;
        color:#172033;
      }
      .cb-current-inning-strip span {
        display:block;
        margin-top:1px;
        font-size:.66rem;
        line-height:1.25;
        color:#667085;
      }
      .cb-current-inning-strip .cb-now-badge {
        flex:0 0 auto;
        border-radius:999px;
        padding:5px 8px;
        background:#172033;
        color:#fff;
        font-size:.6rem;
        font-weight:850;
        letter-spacing:.05em;
      }
      body.cb-dugout #liveDefensiveChangeBtn {
        border-color:#365d96!important;
        background:#f5f8ff!important;
        color:#17355f!important;
      }
      body.cb-dugout #liveDefensiveChangeBtn .coach-action-note,
      body.cb-dugout #liveSetDefenseBtnCoach .coach-action-note {
        opacity:1!important;
        color:#53657d!important;
      }
      body.cb-dugout #live-board-prep-v3 {
        border-color:#91a6c3!important;
      }
      body.cb-dugout #live-board-prep-v3 .bp-head {
        background:#f8faff!important;
      }
      body.cb-dugout #live-board-prep-v3 .bp-kicker {
        color:#365d96!important;
      }
      body.cb-dugout #live-board-prep-v3 .bp-status.waiting {
        background:#f7f9fc!important;
        border-color:#d6dde8!important;
      }
      body.cb-dugout #live-board-prep-v3 .bp-status.waiting .bp-status-badge {
        background:#667085!important;
      }
      body.cb-dugout #live-board-prep-v3 [data-bp-action="adjust"] {
        min-height:46px!important;
      }
      .cb-next-inning-note {
        margin:0 0 10px;
        padding:8px 10px;
        border-radius:9px;
        border:1px solid #c9d6e8;
        background:#f5f8fc;
        color:#475467;
        font-size:.69rem;
        line-height:1.35;
      }
      .cb-next-inning-note strong {
        color:#17355f;
      }
      #next-inning-adjust-modal .cb-next-modal-note {
        margin:0 0 12px;
        padding:9px 10px;
        border:1px solid #c9d6e8;
        border-radius:9px;
        background:#f5f8fc;
        color:#475467;
        font-size:.74rem;
        line-height:1.35;
      }
      #${END_MODAL_ID} .modal-content {
        border:0;
        border-radius:15px;
        overflow:hidden;
      }
      #${END_MODAL_ID} .cb-end-plan-explain {
        border:1px solid #d6dde8;
        border-radius:10px;
        background:#f7f9fc;
        color:#475467;
        padding:10px 11px;
        font-size:.76rem;
        line-height:1.4;
        margin-bottom:12px;
      }
      #${END_MODAL_ID} .cb-end-plan-actions {
        display:grid;
        gap:9px;
      }
      #${END_MODAL_ID} .cb-end-plan-actions .btn {
        min-height:55px;
        border-radius:10px;
        font-weight:800;
        text-align:left;
        padding:9px 11px;
      }
      #${END_MODAL_ID} .cb-end-plan-actions small {
        display:block;
        margin-top:2px;
        font-size:.66rem;
        font-weight:550;
        opacity:.78;
      }
      @media (max-width:599.98px) {
        .cb-current-inning-strip {
          align-items:flex-start;
          padding:8px 9px;
        }
        .cb-current-inning-strip .cb-now-badge {
          padding:4px 7px;
          font-size:.56rem;
        }
        #${END_MODAL_ID} .modal-dialog {
          margin:.5rem;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function setAction(button, title, note) {
    if (!button) return;
    const titleEl = button.querySelector('.coach-action-title');
    const noteEl = button.querySelector('.coach-action-note');
    if (titleEl && titleEl.textContent !== title) titleEl.textContent = title;
    if (noteEl && noteEl.textContent !== note) noteEl.textContent = note;
    button.setAttribute('title', `${title} — ${note}`);
    button.setAttribute('aria-label', `${title}. ${note}`);
  }

  function patchCurrentInningActions() {
    const actionSlot = document.getElementById('coach-action-slot');
    if (!actionSlot) return;

    if (!document.getElementById('cbCurrentInningStrip')) {
      const strip = document.createElement('div');
      strip.id = 'cbCurrentInningStrip';
      strip.className = 'cb-current-inning-strip';
      strip.innerHTML = `
        <div>
          <strong>On-Field Changes</strong>
          <span>Moves made during the current inning.</span>
        </div>
        <div class="cb-now-badge">LIVE NOW</div>`;
      actionSlot.insertAdjacentElement('beforebegin', strip);
    }

    setAction(
      document.getElementById('liveDefensiveChangeBtn'),
      'Make Defensive Change',
      'Current inning · updates the field now'
    );

    setAction(
      document.getElementById('liveSetDefenseBtnCoach'),
      'Set Current Defense',
      'Current inning · updates the field now'
    );

    const pitcher = document.getElementById('liveChangePitcherBtn');
    if (pitcher) {
      const titleEl = pitcher.querySelector('.coach-action-title');
      const noteEl = pitcher.querySelector('.coach-action-note');
      if (titleEl) titleEl.textContent = 'Make Pitching Change';
      if (noteEl) noteEl.textContent = 'Current inning · updates the mound now';
      pitcher.setAttribute('title', 'Make Pitching Change — current inning');
      pitcher.setAttribute('aria-label', 'Make Pitching Change. Current inning.');
    }

    const end = document.getElementById('liveEndInningBtn');
    if (end) {
      const titleEl = end.querySelector('.coach-action-title');
      const noteEl = end.querySelector('.coach-action-note');
      if (titleEl) titleEl.textContent = 'End Inning';
      if (noteEl) noteEl.textContent = 'Sends the next defense onto the field';
    }
  }

  function nextInningNumber(card) {
    return card?.querySelector('.bp-inning strong')?.textContent?.trim() || '';
  }

  function patchNextInningCard() {
    const card = document.getElementById('live-board-prep-v3');
    if (!card) return;

    const next = nextInningNumber(card);
    const kicker = card.querySelector('.bp-kicker');
    const title = card.querySelector('.bp-title');
    const help = card.querySelector('.bp-help');

    if (kicker) kicker.textContent = 'NEXT INNING DEFENSE';
    if (title) title.textContent = next ? `Set Defense for Inning ${next}` : 'Set Next Inning Defense';
    if (help) help.textContent = 'Choose the defense that takes the field when the current inning ends.';

    const body = card.querySelector('.bp-body');
    if (body && !body.querySelector('.cb-next-inning-note')) {
      const note = document.createElement('div');
      note.className = 'cb-next-inning-note';
      note.innerHTML = '<strong>Next inning:</strong> use this section for the defense that takes the field after the third out. Use <strong>Make Defensive Change</strong> above for a move during the current inning.';
      body.prepend(note);
    }

    const waiting = card.querySelector('.bp-status.waiting');
    if (waiting) {
      const strong = waiting.querySelector('strong');
      const small = waiting.querySelector('small');
      const badge = waiting.querySelector('.bp-status-badge');
      if (strong) strong.textContent = next ? `Inning ${next} defense not set` : 'Next inning defense not set';
      if (small) small.textContent = 'Set the next defense before ending the inning.';
      if (badge) badge.textContent = 'NOT SET';
    }

    const decisionLabel = card.querySelector('.bp-decision .bp-label');
    const decisionTitle = card.querySelector('.bp-decision h6');
    const decisionText = card.querySelector('.bp-decision p');
    if (decisionLabel) decisionLabel.textContent = 'Next inning';
    if (decisionTitle) decisionTitle.textContent = next ? `Who takes the field for Inning ${next}?` : 'Who takes the field next inning?';
    if (decisionText) decisionText.textContent = 'Keep the same defense, use the pregame defense, or set a new one.';

    const noPlan = card.querySelector('.bp-none');
    if (noPlan && /No pregame plan/i.test(noPlan.textContent || '')) {
      noPlan.textContent = next ? `No pregame defense saved for Inning ${next}.` : 'No pregame defense saved.';
    }

    const current = card.querySelector('[data-bp-action="current"]');
    const planned = card.querySelector('[data-bp-action="planned"]');
    const adjust = card.querySelector('[data-bp-action="adjust"]');
    if (current) current.textContent = 'Keep Same Defense';
    if (planned) planned.textContent = 'Use Pregame Defense';
    if (adjust) adjust.textContent = 'Set New Defense';

    const ready = card.querySelector('.bp-status.ready');
    if (ready) {
      const strong = ready.querySelector('strong');
      const small = ready.querySelector('small');
      const badge = ready.querySelector('.bp-status-badge');
      if (strong) {
        const text = strong.textContent || '';
        if (/Current defense is staying/i.test(text)) strong.textContent = 'Same defense set';
        else if (/Pregame defense confirmed/i.test(text)) strong.textContent = 'Pregame defense set';
        else if (/Custom defense confirmed/i.test(text)) strong.textContent = 'New defense set';
      }
      if (small) {
        const coach = (small.textContent || '').match(/Confirmed by ([^.]+)/i)?.[1];
        small.textContent = coach ? `Set by ${coach}. Takes the field after the third out.` : 'Takes the field after the third out.';
      }
      if (badge) badge.textContent = 'DEFENSE SET';
    }
  }

  function patchNextInningModal() {
    const modal = document.getElementById('next-inning-adjust-modal');
    if (!modal) return;

    const title = modal.querySelector('.modal-title');
    if (title) title.textContent = 'Set Next Inning Defense';

    const body = modal.querySelector('.modal-body');
    if (body && !body.querySelector('.cb-next-modal-note')) {
      const note = document.createElement('div');
      note.className = 'cb-next-modal-note';
      note.innerHTML = '<strong>Next inning defense.</strong> This lineup takes the field after the current inning ends.';
      body.prepend(note);
    }
  }

  function ensureEndPlanModal() {
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
              <h5 class="modal-title mb-0">Set the Next Defense</h5>
              <div class="small text-muted">Choose who takes the field next inning.</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="cb-end-plan-explain">
              The next-inning defense must be set before the inning can advance.
            </div>
            <div class="cb-end-plan-actions">
              <button type="button" class="btn btn-outline-dark" data-cb-end-use-current>
                Keep Same Defense
                <small>Send the current defense back out next inning.</small>
              </button>
              <button type="button" class="btn btn-primary" data-cb-end-build-next>
                Set New Defense
                <small>Set positions and bench players for the next inning.</small>
              </button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('[data-cb-end-use-current]')?.addEventListener('click', () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      const useCurrent = document.querySelector('#live-board-prep-v3 [data-bp-action="current"]');
      if (useCurrent && !useCurrent.disabled) useCurrent.click();
      setTimeout(() => document.getElementById('live-board-prep-v3')?.scrollIntoView({ behavior:'smooth', block:'center' }), 180);
    });

    modal.querySelector('[data-cb-end-build-next]')?.addEventListener('click', () => {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      const adjust = document.querySelector('#live-board-prep-v3 [data-bp-action="adjust"]');
      if (adjust && !adjust.disabled) setTimeout(() => adjust.click(), 180);
      else document.getElementById('live-board-prep-v3')?.scrollIntoView({ behavior:'smooth', block:'center' });
    });

    return modal;
  }

  function guardEndInning(event) {
    const button = event.target.closest?.('#liveEndInningBtn');
    if (!button || button.disabled) return;
    const card = document.getElementById('live-board-prep-v3');
    if (!card || card.querySelector('.bp-status.ready')) return;

    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
    bootstrap.Modal.getOrCreateInstance(ensureEndPlanModal()).show();
  }

  function patch() {
    queued = false;
    installStyles();
    patchCurrentInningActions();
    patchNextInningCard();
    patchNextInningModal();
  }

  function queuePatch() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(patch);
  }

  function start() {
    installStyles();
    queuePatch();
    document.addEventListener('click', guardEndInning, true);
    new MutationObserver(queuePatch).observe(document.body, { childList:true, subtree:true });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, { once:true })
    : start();
})();
