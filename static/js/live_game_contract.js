(() => {
  'use strict';

  // Authoritative client contract for the live-game workflow, including
  // End Inning. Historical cb-test2 DOM/storage names remain temporarily
  // for compatibility, but this file is not Test App 2-only.

  const route = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!route) return;

  const gameId = Number(route[1]);
  const MODE_KEY = `coachboard:test2-pregame-mode:v2:${gameId}`;
  const MODE_ID = 'cb-test2-pregame-modes';
  const HUDDLE_ID = 'cb-test2-huddle-modal';
  const storedMode = window.sessionStorage.getItem(MODE_KEY);
  let mode = storedMode === 'first-pitch' ? 'first-pitch' : 'full-plan';
  let queued = false;
  let inningAdvanceBusy = false;
  let recoveryNoticeTimer = null;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[char]));
  const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));

  // Live-game writes this page has sent and not yet had an answer to.
  // End Inning reads the game only once they have all landed. Next Inning
  // saves are settled by CBNextDefense.flush(), and End Inning's own
  // advance is not counted.
  let liveWritesInFlight = 0;
  const untrackedFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    let pathname = '';
    try { pathname = new URL(url, window.location.href).pathname; } catch (_) {}
    if (
      method === 'GET' ||
      !pathname.startsWith(`/api/live-game/${gameId}/`) ||
      /\/(next-inning-prep|advance-inning)$/.test(pathname)
    ) {
      return untrackedFetch.apply(this, arguments);
    }
    liveWritesInFlight += 1;
    const landed = () => { liveWritesInFlight -= 1; };
    const result = untrackedFetch.apply(this, arguments);
    result.then(landed, landed);
    return result;
  };
  const setText = (element, value) => {
    if (element && element.textContent !== value) element.textContent = value;
  };

  function installStyles() {
    if ($('cb-test2-contract-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-test2-contract-styles';
    style.textContent = `
      #${MODE_ID}{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 12px;padding:9px 10px;border:1px solid #dfe4ea;border-radius:12px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.04)}
      #${MODE_ID} .cb-t2-mode-copy{min-width:0}.cb-t2-mode-kicker{font-size:var(--cb-text-2xs);text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#667085}.cb-t2-mode-help{font-size:var(--cb-text-xs);color:#667085;line-height:1.3;margin-top:2px}
      #${MODE_ID} .cb-t2-mode-buttons{display:flex;gap:5px;flex:0 0 auto;padding:3px;border:1px solid #d9dee5;border-radius:10px;background:#f4f6f8}
      #${MODE_ID} .cb-t2-mode-buttons .btn{border:0!important;border-radius:7px!important;min-height:36px;padding:6px 10px;font-size:var(--cb-text-xs);font-weight:850;box-shadow:none!important}
      #${MODE_ID} .cb-t2-mode-buttons .active{background:#172033!important;color:#fff!important}
      #cb-quick-start-launch,#cb-quick-start-modal{display:none!important}
      body.cb-test2-first-pitch #lineup-card-container,
      body.cb-test2-first-pitch #pitching-log-container,
      body.cb-test2-first-pitch #pitching-board-v2{display:none!important}
      body.cb-test2-first-pitch #pde-playing-time-summary{display:none!important}
      body.cb-test2-first-pitch #coach-game-readiness-v2 [data-cgr-action="lineup"]{display:none!important}
      body.cb-test2-first-pitch #rotation-card-container>.card>.card-header{display:none!important}
      body.cb-test2-first-pitch #rotation-board>*:not(#pregame-defense-editor-v3){display:none!important}
      #${HUDDLE_ID} .modal-content{border:0;border-radius:16px;overflow:hidden}
      #${HUDDLE_ID} .modal-header{padding:12px 14px;border-bottom:1px solid #e7ebef}
      #${HUDDLE_ID} .cb-t2-huddle-kicker{font-size:.59rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#667085}
      #${HUDDLE_ID} .modal-title{font-size:1.08rem;font-weight:900;color:#172033;margin-top:1px}
      #${HUDDLE_ID} .cb-t2-huddle-sub{font-size:.68rem;color:#667085;margin-top:2px}
      #${HUDDLE_ID} .modal-body{background:#f7f9fb;padding:11px 12px}
      #${HUDDLE_ID} .cb-t2-huddle-status{border:1px solid #dfe4ea;border-radius:11px;background:#fff;padding:9px 10px;margin-bottom:9px}
      #${HUDDLE_ID} .cb-t2-huddle-status.ready{border-color:#b8dcc4;background:#f5fbf7}
      #${HUDDLE_ID} .cb-t2-huddle-status strong{display:block;color:#172033;font-size:.82rem}
      #${HUDDLE_ID} .cb-t2-huddle-status span{display:block;color:#667085;font-size:.69rem;line-height:1.35;margin-top:2px}
      #${HUDDLE_ID} .cb-t2-moves{display:grid;gap:6px;margin:8px 0}
      #${HUDDLE_ID} .cb-t2-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e2e6eb;border-radius:9px;background:#fff;padding:7px 9px}
      #${HUDDLE_ID} .cb-t2-move strong{font-size:.75rem;color:#172033}#${HUDDLE_ID} .cb-t2-move small{display:block;color:#667085;font-size:.63rem;margin-top:1px}
      #${HUDDLE_ID} .cb-t2-dest{min-width:48px;text-align:center;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;font-size:.65rem;font-weight:850}#${HUDDLE_ID} .cb-t2-dest.bench{background:#eef1f5;color:#475467}
      #${HUDDLE_ID} .cb-t2-huddle-actions{display:grid;gap:7px;margin-top:9px}#${HUDDLE_ID} .cb-t2-huddle-actions.two{grid-template-columns:1fr 1fr}
      #${HUDDLE_ID} .cb-t2-huddle-actions .btn{min-height:46px;border-radius:10px;font-weight:820}
      #${HUDDLE_ID} .cb-t2-error{display:none;border:1px solid #efbbb6;border-radius:9px;background:#fff2f0;color:#912d28;padding:8px 9px;font-size:.7rem;margin-top:8px}#${HUDDLE_ID} .cb-t2-error.show{display:block}
      #${HUDDLE_ID} .cb-t2-start{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7ebef;padding:10px 12px calc(10px + env(safe-area-inset-bottom))}
      #${HUDDLE_ID} .cb-t2-start .btn{width:100%;min-height:50px;border-radius:10px;font-weight:900}
      #cb-test2-inning-recovery{display:none;position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2200;width:min(92vw,520px);border:1px solid #9fc5b0;border-radius:11px;background:#edf8f1;color:#176b38;padding:10px 12px;box-shadow:0 8px 24px rgba(16,24,40,.18);font-size:.76rem;font-weight:780;line-height:1.35;text-align:center}
      #cb-test2-inning-recovery.show{display:block}
      @media(max-width:767.98px){
        #${MODE_ID}{
          justify-content:flex-end;
          padding:5px 6px;
          margin-bottom:7px;
        }
        #${MODE_ID} .cb-t2-mode-copy{
          display:none;
        }
        #${MODE_ID} .cb-t2-mode-buttons{
          width:auto;
          padding:2px;
          gap:3px;
          margin-left:auto;
        }
        #${MODE_ID} .cb-t2-mode-buttons .btn{
          flex:0 0 auto;
          min-height:30px;
          padding:4px 8px;
          font-size:var(--cb-text-xs);
        }
        #${HUDDLE_ID} .modal-dialog{
          margin:.35rem;
        }
        #${HUDDLE_ID} .cb-t2-huddle-actions.two{
          grid-template-columns:1fr;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureClockControls() {
    if ([...document.scripts].some(script => /\/live_game_clock_controls\.js(?:\?|$)/.test(script.src || ''))) return;
    const script = document.createElement('script');
    script.src = window.CoachBoardAssets.url('/static/js/live_game_clock_controls.js');
    script.dataset.cbTest2ClockControls = 'true';
    document.head.appendChild(script);
  }

  function isLive() {
    const overlay = $('live-game-overlay');
    return document.body.classList.contains('cb-dugout') || Boolean(overlay && !overlay.classList.contains('d-none'));
  }

  function forceInningOne() {
    if (mode !== 'first-pitch' || isLive()) return;
    const inningOne = document.querySelector('#inning-btn-group input[name="inning-radio"][value="1"]');
    if (inningOne && !inningOne.checked) inningOne.click();
  }

  function polishPregameDefense() {
    if (isLive()) return;
    const panel = $('pregame-defense-editor-v3');
    if (!panel) return;
    if (mode === 'first-pitch') {
      setText(panel.querySelector('.pde-kicker'), 'First Pitch');
      setText(panel.querySelector('.pde-title'), 'First-pitch defense');
      setText(panel.querySelector('.pde-help'), 'Set only the defense needed to start the game. Full Plan is available when you want later innings.');
      return;
    }
    const selectedInning = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked')?.value || '1';
    setText(panel.querySelector('.pde-kicker'), 'Defense Setup');
    setText(panel.querySelector('.pde-title'), `Set Defense — Inning ${selectedInning}`);
    setText(panel.querySelector('.pde-help'), 'Set the defense for this inning, or use the full-game planning tools for later innings.');
  }

  function updateModeButtons() {
    const bar = $(MODE_ID);
    if (!bar) return;
    bar.querySelectorAll('[data-cb-t2-mode]').forEach(button => {
      const active = button.dataset.cbT2Mode === mode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    setText(bar.querySelector('.cb-t2-mode-help'), mode === 'first-pitch'
      ? 'Only first-pitch essentials are in view. Batting order and later innings stay optional.'
      : 'Plan batting order, later defensive innings, pitching, and the rest of the game.');
  }

  function setMode(next) {
    mode = next === 'full-plan' ? 'full-plan' : 'first-pitch';
    window.sessionStorage.setItem(MODE_KEY, mode);
    document.body.classList.toggle('cb-test2-first-pitch', mode === 'first-pitch');
    document.body.classList.toggle('cb-test2-full-plan', mode === 'full-plan');
    updateModeButtons();
    forceInningOne();
    polishPregameDefense();
  }

  function ensureModeBar() {
    const pregame = $('pregame-checklist-container');
    if (!pregame || isLive()) {
      $(MODE_ID)?.remove();
      return;
    }
    let bar = $(MODE_ID);
    if (!bar) {
      bar = document.createElement('section');
      bar.id = MODE_ID;
      bar.innerHTML = `
        <div class="cb-t2-mode-copy"><div class="cb-t2-mode-kicker">Get ready</div><div class="cb-t2-mode-help"></div></div>
        <div class="cb-t2-mode-buttons" role="group" aria-label="Pregame planning mode">
          <button type="button" class="btn" data-cb-t2-mode="first-pitch">First Pitch</button>
          <button type="button" class="btn" data-cb-t2-mode="full-plan">Full Plan</button>
        </div>`;
      const header = pregame.querySelector(':scope > .d-flex:first-child');
      if (header) header.insertAdjacentElement('afterend', bar);
      else pregame.prepend(bar);
      bar.addEventListener('click', event => {
        const button = event.target.closest('[data-cb-t2-mode]');
        if (button) setMode(button.dataset.cbT2Mode);
      });
    }
    setMode(mode);
  }

  function applyContract() {
    queued = false;
    installStyles();
    $('cb-quick-start-launch')?.remove();
    const quickModal = $('cb-quick-start-modal');
    if (quickModal) {
      try { window.bootstrap?.Modal?.getInstance(quickModal)?.hide(); } catch (_) {}
      quickModal.remove();
    }

    if (isLive()) {
      // Only touch the classes when one is there: classList.remove() rewrites
      // the attribute even when nothing changes, which woke the other
      // body-class observers and kept both scripts re-running every frame.
      // Quick Field's words belong to live_game_dugout_mode.js.
      const modeClasses = ['cb-test2-first-pitch', 'cb-test2-full-plan'];
      if (modeClasses.some(name => document.body.classList.contains(name))) {
        document.body.classList.remove(...modeClasses);
      }
      $(MODE_ID)?.remove();
    } else {
      ensureModeBar();
      forceInningOne();
      polishPregameDefense();
    }
  }

  function queueContract() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(applyContract);
  }

  // fresh: a new request, never one already in the air (the shared /state
  // read in live_game_feedback_pass.js may predate a write that just landed).
  async function getJson(path, {fresh = false} = {}) {
    const response = await fetch(path, {cache:'no-store', ...(fresh ? {cbFresh: true} : {})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Request failed (${response.status}).`);
    return data;
  }

  async function postJson(path, body) {
    const response = await fetch(path, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') {
      const error = new Error(data.message || `Request failed (${response.status}).`);
      error.code = data.code || '';
      error.pitcher = data.pitcher || '';
      error.payload = data;
      throw error;
    }
    return data;
  }

  function sequenceFromState(state) {
    return (state?.rotation_events || []).reduce((max, event) => {
      if (event?.reverted) return max;
      return Math.max(max, Number(event?.sequence) || 0);
    }, 0);
  }

  async function waitForQuickFieldSave() {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const badge = document.querySelector(
        '#cbQuickDefense .cb-save-state'
      );

      if (
        !badge ||
        !badge.classList.contains('saving')
      ) {
        return;
      }

      await sleep(100);
    }

    throw new Error(
      'Current defense is still saving. ' +
      'Try End Inning again after Saved ✓ appears.'
    );
  }

  // This page's live writes (a Quick Field save, an Undo, a fill...) have
  // all been answered, so one read now includes them. Another device's
  // later change is caught by the server (base_sequence, the Next Inning
  // revision), as before.
  async function waitForLiveWritesToSettle() {
    await waitForQuickFieldSave();

    for (let attempt = 0; liveWritesInFlight > 0; attempt += 1) {
      if (attempt >= 100) {
        throw new Error(
          'A change is still saving. ' +
          'Try End Inning again in a moment.'
        );
      }

      await sleep(100);
    }
  }


  function showInningRecoveryNotice(inning, message = '') {
    let notice = $('cb-test2-inning-recovery');

    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'cb-test2-inning-recovery';
      notice.setAttribute('role', 'status');
      notice.setAttribute(
        'aria-live',
        'polite'
      );
      document.body.appendChild(notice);
    }

    setText(
      notice,
      message ||
      `Another coach already started Inning ${inning}. ` +
      'Live Game is updated.'
    );

    notice.classList.add('show');

    if (recoveryNoticeTimer) {
      window.clearTimeout(
        recoveryNoticeTimer
      );
    }

    recoveryNoticeTimer =
      window.setTimeout(
        () => {
          notice.classList.remove('show');
        },
        4500
      );
  }

  function stateAsLiveDelta(value) {
    const events = Array.isArray(
      value?.rotation_events
    )
      ? value.rotation_events.filter(
          event => !event?.reverted
        )
      : [];

    const latestEvent = events.reduce(
      (latest, event) => {
        if (!latest) return event;

        return Number(
          event?.sequence || 0
        ) >
        Number(
          latest?.sequence || 0
        )
          ? event
          : latest;
      },
      null
    );

    const alignment = {
      ...(value?.current_alignment || {}),
    };

    return {
      game_id: gameId,
      current_inning: String(
        value?.current_inning ||
        value?.game?.live_current_inning ||
        '1'
      ),
      current_alignment: alignment,
      current_pitcher:
        value?.current_pitcher ||
        alignment.P ||
        null,
      bench: Array.isArray(value?.bench)
        ? value.bench
        : [],
      sequence:
        Number(value?.sequence) ||
        Number(latestEvent?.sequence) ||
        sequenceFromState(value),
      event:
        value?.event ||
        latestEvent ||
        undefined,
    };
  }

  function recoverAdvancedInning(
    liveState,
    {publish = true} = {}
  ) {
    const inning = String(
      liveState?.current_inning ||
      liveState?.game?.live_current_inning ||
      ''
    );

    if (!inning) return;

    $(HUDDLE_ID)?.remove();

    if (publish) {
      document.dispatchEvent(
        new CustomEvent(
          'coachboard:live-delta',
          {
            detail:
              stateAsLiveDelta(
                liveState
              ),
          }
        )
      );
    }

    window.CBNextDefense
      ?.afterAdvance?.();

    showInningRecoveryNotice(
      inning
    );
  }

  function requiredDefensePositions(
    liveState
  ) {
    return Number(
      liveState?.outfielder_count
    ) === 4
      ? [
          'P', 'C', '1B', '2B', '3B',
          'SS', 'LF', 'LCF', 'RCF', 'RF',
        ]
      : [
          'P', 'C', '1B', '2B', '3B',
          'SS', 'LF', 'CF', 'RF',
        ];
  }

  function positionList(open) {
    if (open.length === 1) return open[0];
    if (open.length === 2) return `${open[0]} and ${open[1]}`;
    return (
      `${open.slice(0, -1).join(', ')}, ` +
      `and ${open[open.length - 1]}`
    );
  }

  // End Inning starts the next inning with the Next Inning defense. An open
  // spot there is allowed (a short-handed team), but never by accident.
  function ordinal(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value || '');
    const teen = n % 100 >= 11 && n % 100 <= 13;
    const suffix = teen ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[n % 10] || 'th');
    return `${n}${suffix}`;
  }

  function openPositionsIn(alignment, source) {
    return requiredDefensePositions(source).filter(
      position => !String((alignment || {})[position] || '').trim()
    );
  }

  // A modal with a title, a message, an optional note and two actions.
  // Each action is [label, onChoose, buttonClass?].
  function endInningQuestion(id, {title, message, note, primary, secondary}) {
    let modal = $(id);

    if (!modal) {
      modal = document.createElement('div');
      modal.id = id;
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.setAttribute('aria-hidden', 'true');
      modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" data-cb-question-title></h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="fw-semibold" data-cb-question-message></div>
              <div class="small text-muted mt-2" data-cb-question-note></div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-primary" data-cb-question-primary></button>
              <button type="button" class="btn btn-outline-secondary" data-cb-question-secondary></button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);
    }

    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    modal.querySelector('[data-cb-question-title]').textContent = title;
    modal.querySelector('[data-cb-question-message]').textContent = message;
    const noteLine = modal.querySelector('[data-cb-question-note]');
    noteLine.textContent = note || '';
    noteLine.hidden = !note;

    const wire = (selector, [label, onChoose, buttonClass], fallbackClass) => {
      const button = modal.querySelector(selector);
      button.className = `btn ${buttonClass || fallbackClass}`;
      button.textContent = label;
      button.onclick = () => {
        modal.addEventListener('hidden.bs.modal', onChoose, {once: true});
        instance.hide();
      };
    };
    wire('[data-cb-question-primary]', primary, 'btn-primary');
    wire('[data-cb-question-secondary]', secondary, 'btn-outline-secondary');

    instance.show();
  }

  /*
   * The inning being completed. An open position in its recorded defense
   * may be a recording mistake that would make the Game Report and
   * playing time wrong, so it is worth one clear question -- about THAT
   * inning, never worded as if the next inning's plan were open.
   * "Continue to 6th" is remembered for this exact recorded defense.
   */
  // Remembered for this tab (sessionStorage), so a deliberate "Start with CF
  // Open" at first pitch survives the page reload into live play.
  const RECORD_ACKS_KEY = `coachboard:record-acks:v1:${gameId}`;
  const acknowledgedRecords = new Set((() => {
    try {
      const saved = JSON.parse(window.sessionStorage.getItem(RECORD_ACKS_KEY) || '[]');
      return Array.isArray(saved) ? saved : [];
    } catch (_) {
      return [];
    }
  })());

  function acknowledgeRecord(key) {
    acknowledgedRecords.add(key);
    try {
      window.sessionStorage.setItem(RECORD_ACKS_KEY, JSON.stringify([...acknowledgedRecords]));
    } catch (_) {}
  }

  function recordKey(liveState) {
    const alignment = Object.entries(liveState?.current_alignment || {})
      .filter(([, name]) => String(name || '').trim())
      .sort(([a], [b]) => (a < b ? -1 : 1));
    return JSON.stringify([
      gameId,
      String(liveState?.current_inning || ''),
      alignment,
    ]);
  }

  const POSITION_NAMES = {
    P: 'pitcher',
    C: 'catcher',
    '1B': 'first base',
    '2B': 'second base',
    '3B': 'third base',
    SS: 'shortstop',
    LF: 'left field',
    CF: 'center field',
    RF: 'right field',
    LCF: 'left-center field',
    RCF: 'right-center field',
  };

  // ['LF', 'CF', 'RF'] -> "LF, CF, or RF" (conjunction 'or' / 'and').
  function joinWords(items, conjunction) {
    if (items.length <= 1) return items[0] || '';
    if (items.length === 2) return `${items[0]} ${conjunction} ${items[1]}`;
    return `${items.slice(0, -1).join(', ')}, ${conjunction} ${items[items.length - 1]}`;
  }

  // Coach words, not record keeping: "Right field is empty at the end of
  // the 5th". "Continue to 6th", not "Start": the next inning's own check
  // may still come before it begins.
  function warnRecordedInningGap(open, liveState, retry) {
    const inning = ordinal(liveState?.current_inning);
    const next = ordinal(Number(liveState?.current_inning) + 1);
    const key = recordKey(liveState);
    const named = joinWords(open.map(pos => POSITION_NAMES[pos] || pos), 'and');

    endInningQuestion('cbRecordedInningGapModal', {
      title:
        `${named.charAt(0).toUpperCase()}${named.slice(1)} ` +
        `${open.length === 1 ? 'is' : 'are'} empty at the end of the ${inning}`,
      message:
        `Nobody was in ${joinWords(open, 'or')} when the ${inning} ended. ` +
        `Go back and fix the ${inning} if that's wrong, or continue to the ` +
        `${next} and leave the ${inning} as saved.`,
      note: '',
      // Fix opens the picker for the (first) empty spot on the field; any
      // other empty spot stays marked Open, and the picker names it too.
      primary: [`Fix ${inning} Defense`, () => {
        document.querySelector('#cb-now-next-switch [data-now-next="now"]')?.click();
        window.CBQuickField?.fillOpen?.(open[0]);
      }],
      secondary: [`Continue to ${next}`, () => {
        acknowledgeRecord(key);
        retry();
      }, 'btn-outline-primary'],
    });
  }

  // The next inning's plan: exactly the alignment advance-inning receives.
  // Asked only when a player on the bench could fill the spot (a
  // short-handed team starts without asking). Both answers are real
  // choices, so both buttons read as actions.
  function warnIncompleteNextDefense(open, nextInning, benchAvailable, retry) {
    const inning = ordinal(nextInning);
    const listed = positionList(open);
    const verb = open.length === 1 ? 'is' : 'are';

    endInningQuestion('cbIncompleteNextModal', {
      title: open.length === 1
        ? `${inning} inning defense has ${open[0]} open`
        : `${inning} inning defense has open positions`,
      message: benchAvailable
        ? `${listed} ${verb} open, and players are available on the bench.`
        : `${listed} ${verb} open.`,
      note: '',
      // Fixing is the prominent choice and opens the picker for the (first)
      // open spot; starting with the gap stays a deliberate second choice.
      primary: [`Finish ${inning} Inning Defense`, () => {
        if (window.CBNextDefense?.fixOpen) window.CBNextDefense.fixOpen(open[0]);
        else window.CBNextDefense?.showNext?.();
      }, 'btn-primary'],
      secondary: [`Start ${inning} with ${listed} Open`, retry, 'btn-outline-primary'],
    });
  }

  const PITCHING_DECISION_CODES = new Set([
    'pitcher_advisory',
    'pitcher_rule_conflict',
    'pitcher_eligibility_unconfirmed',
  ]);

  // End Inning putting a flagged pitcher on the mound: the server has just
  // re-evaluated eligibility and says what it believes (rule set, reason).
  // The coach decides -- Continue (advisory), I verified (can't confirm),
  // or Use Anyway plus a deliberate override confirmation (rule conflict).
  // Cancel changes nothing.
  function askPitchingDecision(info, retry) {
    let modal = $('cbPitchingDecisionModal');

    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'cbPitchingDecisionModal';
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.setAttribute('aria-hidden', 'true');
      modal.setAttribute('aria-labelledby', 'cbPitchingDecisionTitle');
      modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="cbPitchingDecisionTitle"></h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="fw-semibold" data-cb-decision-message></div>
              <div class="small text-muted mt-2" data-cb-decision-confirm-text></div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-secondary" data-cb-decision-cancel></button>
              <button type="button" class="btn" data-cb-decision-go></button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);
    }

    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const pitcher = info.pitcher || '';
    const firstName = String(pitcher).trim().split(/\s+/)[0] || pitcher;
    const kind = info.eligibility;
    const decision = info.required_decision;
    const title = modal.querySelector('.modal-title');
    const message = modal.querySelector('[data-cb-decision-message]');
    const confirmText = modal.querySelector('[data-cb-decision-confirm-text]');
    const cancel = modal.querySelector('[data-cb-decision-cancel]');
    const go = modal.querySelector('[data-cb-decision-go]');

    modal.dataset.eligibilityKind = kind || '';

    const decide = () => {
      modal.addEventListener(
        'hidden.bs.modal',
        () => retry({type: decision, status: info.pitching_status || ''}),
        {once: true}
      );
      instance.hide();
    };

    const showOverrideConfirm = () => {
      title.textContent = 'Override pitching rule?';
      confirmText.textContent = info.override_confirm || '';
      cancel.textContent = 'Cancel';
      go.className = 'btn btn-danger';
      go.textContent = `Use ${firstName} Anyway`;
      go.onclick = decide;
    };

    title.textContent = info.eligibility_heading || pitcher;
    message.textContent = info.eligibility_message || info.message || '';
    confirmText.textContent = '';
    cancel.textContent = kind === 'unknown' ? 'Cancel' : 'Go Back';
    cancel.onclick = () => instance.hide();

    if (kind === 'rule_conflict') {
      go.className = 'btn btn-outline-danger';
      go.textContent = `Use ${firstName} Anyway`;
      go.onclick = showOverrideConfirm;
    } else {
      go.className = 'btn btn-primary';
      go.textContent = kind === 'advisory'
        ? `Continue with ${firstName}`
        : `I verified ${firstName} is eligible`;
      go.onclick = decide;
    }

    instance.show();
  }

  function sameDefense(a, b) {
    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    return [...keys].every(pos => (a?.[pos] || '') === (b?.[pos] || ''));
  }

  function planSkippedByDefault(prep) {
    const seed = prep?.planned_seed;
    return Boolean(
      seed &&
      Object.values(seed).some(Boolean) &&
      prep?.confirmed?.updated_by === 'Auto' &&
      !sameDefense(seed, prep.confirmed.alignment)
    );
  }

  function askAboutSkippedPlan(prep, retry) {
    const next = ordinal(prep.next_inning);
    const current = ordinal(prep.current_inning);
    const choose = action => async () => {
      try {
        await action();
        retry();
      } catch (error) {
        window.CBNextDefense?.showError?.(error?.message || 'Unable to save that choice.');
        window.CBNextDefense?.showNext?.();
      }
    };

    endInningQuestion('cbSkippedPlanModal', {
      title: `Use the ${next}-inning plan?`,
      message:
        `A change this inning carried the ${current}-inning defense forward, ` +
        `so your ${next}-inning pregame plan won't be used unless you choose it.`,
      note: '',
      primary: [`Use the ${next}-inning plan`, choose(() => window.CBNextDefense.usePlan()), 'btn-primary'],
      secondary: ['Keep this defense', choose(() => window.CBNextDefense.useSame()), 'btn-outline-primary'],
    });
  }

  async function endInningFromNext(
    allowOpenNext = false,
    pitchingDecision = null
  ) {
    if (inningAdvanceBusy) return;

    const button =
      $('liveEndInningBtn');

    if (!button || button.disabled) {
      return;
    }

    inningAdvanceBusy = true;

    // The inning the coach is ending, as the button showed it.
    const shownInning =
      button.dataset.cbInning || '';

    const wasDisabled =
      button.disabled;

    button.disabled = true;

    try {
      // NEXT prep is a separate persistence channel from live rotation
      // events. Flush it explicitly before asking the server which defense
      // should become the next inning.
      await window.CBNextDefense
        ?.flush?.();

      await waitForLiveWritesToSettle();

      // Everything this page sent has landed: read the game and the next
      // inning once, together.
      const [prep, liveState] =
        await Promise.all([
          getJson(
            `/api/live-game/${gameId}/next-inning-prep`,
            {fresh: true}
          ),
          getJson(
            `/api/live-game/${gameId}/state`,
            {fresh: true}
          ),
        ]);

      const currentInning = String(
        liveState?.current_inning ||
        ''
      );

      // The page shows what was just read (if it is newer).
      window.CBLiveState?.adopt?.(liveState, 'end-inning');

      if (
        currentInning !==
        String(prep?.current_inning || '')
      ) {
        recoverAdvancedInning(
          liveState
        );
        return;
      }

      // The game is in another inning than the one the coach tapped to end
      // (changed on another device, not yet shown here): show it instead of
      // ending an inning the coach did not see.
      if (shownInning && currentInning !== shownInning) {
        showInningRecoveryNotice(
          currentInning,
          `The game is in Inning ${currentInning} now — it changed on another device. ` +
          'Check the field, then end the inning.'
        );
        return;
      }

      // The inning being completed: an unacknowledged open position in
      // its recorded defense gets one clear question about that inning.
      const openRecorded = openPositionsIn(
        liveState?.current_alignment,
        liveState
      );

      if (
        openRecorded.length &&
        !acknowledgedRecords.has(recordKey(liveState))
      ) {
        warnRecordedInningGap(
          openRecorded,
          liveState,
          () => endInningFromNext(allowOpenNext, pitchingDecision)
        );
        return;
      }

      // The next inning has its own pregame plan, but a live change this
      // inning carried the field forward instead -- and no coach chose
      // either. Ask once; the answer is saved as the coach's choice, so it
      // is not asked again and later live changes keep it.
      if (planSkippedByDefault(prep)) {
        askAboutSkippedPlan(
          prep,
          () => endInningFromNext(allowOpenNext, pitchingDecision)
        );
        return;
      }

      const alignment = {
        ...(prep?.confirmed?.alignment || {}),
      };

      if (!alignment.P) {
        // One message -- the Next Inning board's "Set a pitcher" line --
        // with focus on its P spot.
        if (window.CBNextDefense?.requirePitcher?.()) return;
        throw new Error(
          'Set a pitcher for the next inning.'
        );
      }

      const assigned = new Map();

      for (
        const [position, rawName]
        of Object.entries(alignment)
      ) {
        const name = String(
          rawName || ''
        ).trim();

        if (!name) continue;

        if (assigned.has(name)) {
          const firstPosition =
            assigned.get(name);

          throw new Error(
            `${name} is assigned to both ` +
            `${firstPosition} and ${position}. ` +
            'Fix NEXT before ending the inning.'
          );
        }

        assigned.set(name, position);
      }

      // The next inning's plan -- the alignment sent below.
      const openNext = openPositionsIn(
        alignment,
        prep
      );

      // Short-handed: every player here is already on the field, so the
      // open spots cannot be filled. Nothing to ask (the board still warns).
      // A player on the bench means the coach could fill a spot, so ask.
      const presentNames = (prep?.roster || [])
        .map(player => String(player?.name || '').trim())
        .filter(Boolean);
      const shortHanded =
        openNext.length > 0 &&
        presentNames.length > 0 &&
        presentNames.every(name => assigned.has(name));

      // Validated and sent are the same alignment: the warning names the
      // spots open in the plan, and "Start inning anyway" sends that plan.
      if (
        openNext.length &&
        !allowOpenNext &&
        !shortHanded
      ) {
        warnIncompleteNextDefense(
          openNext,
          Number(currentInning) + 1,
          presentNames.some(name => !assigned.has(name)),
          () => endInningFromNext(true, pitchingDecision)
        );
        return;
      }

      const result = await postJson(
        `/api/live-game/${gameId}/advance-inning`,
        {
          alignment,
          next_prep_id:
            prep?.confirmed?.id ??
            null,
          base_sequence:
            sequenceFromState(
              liveState
            ),
          // The coach's decision from this End Inning, for the status
          // shown; honored here instead of asking again.
          ...(pitchingDecision?.type
            ? {
                pitching_decision: pitchingDecision.type,
                pitching_decision_status: pitchingDecision.status || '',
              }
            : {}),
        }
      );

      // A deliberate open start ("Start Inning Anyway", or short-handed) is
      // remembered for exactly this inning and defense, like "Keep as
      // Recorded": its End Inning does not ask about the same open spots
      // again. Any change to that defense asks again.
      if (openNext.length) {
        acknowledgeRecord(recordKey({
          current_inning: String(Number(currentInning) + 1),
          current_alignment: alignment,
        }));
      }

      if (result?.delta) {
        document.dispatchEvent(
          new CustomEvent(
            'coachboard:live-delta',
            {
              detail: result.delta,
            }
          )
        );
      }

      document.dispatchEvent(
        new CustomEvent(
          'coachboard:test2-inning-started',
          {
            detail: {
              result,
            },
          }
        )
      );

      window.CBNextDefense
        ?.afterAdvance?.();

    } catch (error) {
      // Asked again only when the status changed since the coach decided
      // (the server says the decision is outdated).
      if (
        PITCHING_DECISION_CODES.has(error?.code) &&
        (!pitchingDecision || error.payload?.decision_outdated)
      ) {
        askPitchingDecision(
          error.payload || {pitcher: error.pitcher, message: error.message},
          decision => endInningFromNext(
            allowOpenNext,
            decision
          )
        );
        return;
      }

      try {
        const fresh = await getJson(
          `/api/live-game/${gameId}/state`,
          {fresh: true}
        );

        const nextInning = Number(
          fresh?.current_inning
        );

        const oldInning = Number(
          $('live-inning-display')
            ?.textContent
        );

        if (
          Number.isFinite(nextInning) &&
          Number.isFinite(oldInning) &&
          nextInning > oldInning
        ) {
          recoverAdvancedInning(
            fresh
          );
          return;
        }
      } catch (_) {}

      const message =
        error?.message ||
        'Unable to end inning.';

      window.CBNextDefense
        ?.showError?.(
          message
        );

      window.CBNextDefense
        ?.showNext?.();

    } finally {
      inningAdvanceBusy = false;

      if (button?.isConnected) {
        button.disabled =
          wasDisabled;
      }
    }
  }

  window.addEventListener(
    'click',
    event => {
      const button =
        event.target.closest?.(
          '#liveEndInningBtn'
        );

      if (
        !button ||
        button.disabled
      ) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();

      endInningFromNext();
    },
    true
  );

  /*
   * Start Game. The server decides (game_start_readiness.can_start_game,
   * under the game's write lock); this asks the coach what only the coach
   * can decide and sends exactly what the coach reviewed:
   *
   * - the Pregame save queue settles first, and an unsaved change stops Start;
   * - the 1st-inning defense on screen goes with the request, and the server
   *   refuses it if the stored one differs;
   * - a data problem (no pitcher, a player twice, not on the roster, marked
   *   Out) is listed to fix;
   * - open fielding positions are asked about, and "Start with CF Open"
   *   acknowledges exactly those positions -- if they change first, the
   *   server asks again.
   */
  async function settlePregameSaves(timeoutMs = 15000) {
    const store = window.CBPregameRotation;
    if (!store) return true;
    const began = Date.now();
    while (store.isSaveInFlightOrQueued()) {
      if (Date.now() - began > timeoutMs) return false;
      await sleep(100);
    }
    return !store.hasUnsyncedLocalState();
  }

  function reviewedInningOne() {
    const inning = window.CBPregameRotation?.getRotation?.()?.innings?.['1'];
    return inning && typeof inning === 'object' ? {...inning} : null;
  }

  function showFirstInningDefense() {
    const quickStart = $('cb-quick-start-modal');
    if (quickStart) window.bootstrap?.Modal?.getInstance(quickStart)?.hide();
    const first = document.querySelector('#inning-btn-group input[name="inning-radio"][value="1"]');
    if (first && !first.checked) first.click();
    window.setTimeout(() => {
      $('pregame-defense-editor-v3')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 250);
  }

  // One Start question. Resolves with the chosen action's value, or null
  // when closed. The answer counts on the tap, even while the sheet is still
  // opening (Bootstrap ignores hide() mid-transition).
  async function startQuestion({title, message, list = [], actions}) {
    let modal = $('cbStartGameModal');
    // Still closing from the previous answer: let it finish, or Bootstrap
    // would ignore this show().
    if (modal && modal.style.display === 'block' && !modal.classList.contains('show')) {
      await new Promise(resolve => modal.addEventListener('hidden.bs.modal', resolve, {once: true}));
    }
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'cbStartGameModal';
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.setAttribute('aria-hidden', 'true');
      modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" data-cb-start-title></h5>
              <button type="button" class="btn-close" data-cb-start-close aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="fw-semibold" data-cb-start-message></div>
              <ul class="small mb-0 mt-2 ps-3" data-cb-start-list></ul>
            </div>
            <div class="modal-footer" data-cb-start-actions></div>
          </div>
        </div>`;
      document.body.appendChild(modal);
    }
    modal.querySelector('[data-cb-start-title]').textContent = title;
    modal.querySelector('[data-cb-start-message]').textContent = message || '';
    const listed = modal.querySelector('[data-cb-start-list]');
    listed.innerHTML = list.map(item => `<li>${esc(item)}</li>`).join('');
    listed.hidden = !list.length;
    const footer = modal.querySelector('[data-cb-start-actions]');
    footer.innerHTML = actions.map((action, index) => `
      <button type="button" class="btn ${action.danger ? 'btn-danger' : action.primary ? 'btn-primary' : 'btn-outline-secondary'}" data-cb-start-action="${index}">${esc(action.label)}</button>`).join('');

    return new Promise(resolve => {
      let answered = false;
      const instance = bootstrap.Modal.getOrCreateInstance(modal);
      const decide = value => {
        if (!answered) {
          answered = true;
          resolve(value);
        }
        instance.hide();
      };
      const closeIfAnswered = () => {
        if (answered) instance.hide();
      };
      footer.querySelectorAll('[data-cb-start-action]').forEach(button => {
        button.onclick = () => decide(actions[Number(button.dataset.cbStartAction)].value);
      });
      modal.querySelector('[data-cb-start-close]').onclick = () => decide(null);
      modal.addEventListener('shown.bs.modal', closeIfAnswered);
      modal.addEventListener('hidden.bs.modal', () => {
        modal.removeEventListener('shown.bs.modal', closeIfAnswered);
        if (!answered) {
          answered = true;
          resolve(null);
        }
      }, {once: true});
      instance.show();
    });
  }

  // Back to the 1st inning's P to choose another starter.
  function chooseAnotherPitcher() {
    showFirstInningDefense();
    window.setTimeout(() => {
      document.querySelector('#pregame-defense-editor-v3 [data-pde-pos="P"]')?.click();
    }, 450);
  }

  function chooseRules() {
    const quickStart = $('cb-quick-start-modal');
    if (quickStart) window.bootstrap?.Modal?.getInstance(quickStart)?.hide();
    window.setTimeout(() => {
      const card = $('game-pitching-rules-v2');
      card?.scrollIntoView({behavior: 'smooth', block: 'start'});
      const edit = $('game-pitch-rule-edit-v2');
      if (edit && edit.getAttribute('aria-expanded') !== 'true') edit.click();
    }, 250);
  }

  // The starting pitcher's question, from the server's own classification
  // and wording (pitching_eligibility.py) -- the same four kinds and the
  // same decisions as a live pitching change. Resolves 'decide', 'another',
  // 'rules' or null.
  async function askStartingPitcher(info) {
    const pitcher = info.pitcher || '';
    const first = String(pitcher).trim().split(/\s+/)[0] || pitcher;
    const changed = info.decision_outdated ? `${pitcher}'s pitching status changed. ` : '';
    const message = `${changed}${info.eligibility_message || info.message || ''}`;
    const another = {label: 'Choose Another Pitcher', value: 'another'};

    if (info.code === 'start_no_pitching_rules') {
      return startQuestion({
        title: info.eligibility_heading,
        message,
        actions: [
          {label: 'Choose Rules', value: 'rules', primary: true},
          {label: 'Start Without Rules', value: 'decide'},
        ],
      });
    }
    if (info.eligibility === 'advisory') {
      return startQuestion({
        title: info.eligibility_heading,
        message,
        actions: [{label: `Continue with ${first}`, value: 'decide', primary: true}, another],
      });
    }
    if (info.eligibility === 'rule_conflict') {
      const choice = await startQuestion({
        title: info.eligibility_heading,
        message,
        actions: [another, {label: `Use ${first} Anyway`, value: 'override', danger: true}],
      });
      if (choice !== 'override') return choice;
      // A deliberate second step, as in a live pitching change.
      return startQuestion({
        title: 'Override pitching rule?',
        message: info.override_confirm || '',
        actions: [
          {label: `Use ${first} Anyway`, value: 'decide', danger: true},
          {label: 'Cancel', value: null},
        ],
      });
    }
    return startQuestion({
      title: info.eligibility_heading,
      message,
      actions: [{label: `I verified ${first} is eligible`, value: 'decide', primary: true}, another],
    });
  }

  const STARTER_QUESTIONS = new Set([
    'pitcher_advisory',
    'pitcher_rule_conflict',
    'pitcher_eligibility_unconfirmed',
    'start_no_pitching_rules',
  ]);

  async function postStart(body) {
    const response = await fetch(`/api/live-game/${gameId}/start`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    return {ok: response.ok && data.status !== 'error', data};
  }

  // Resolves with the successful /start response, or null when Start did
  // not happen (a question was declined, or something must be fixed).
  async function startGame() {
    if (!(await settlePregameSaves())) {
      await startQuestion({
        title: "Your last change hasn't saved",
        message: "A change to the defense hasn't saved yet. Tap the save status to retry, then start the game.",
        actions: [{label: 'OK', value: null, primary: true}],
      });
      return null;
    }

    // Without the tab's plan there is nothing reviewed to send; the server
    // then asks for a refresh instead of starting.
    const inningOne = reviewedInningOne();
    let openAcknowledged = null;
    let pitchingDecision = null;
    for (;;) {
      const body = {};
      if (inningOne) body.inning_one = inningOne;
      if (openAcknowledged) body.open_positions = openAcknowledged;
      if (pitchingDecision) Object.assign(body, pitchingDecision);
      const {ok, data} = await postStart(body);

      if (ok) {
        if (openAcknowledged && inningOne) {
          // The coach already decided the 1st inning's open position(s);
          // ending the 1st with this same field doesn't ask again.
          acknowledgeRecord(recordKey({current_inning: '1', current_alignment: inningOne}));
        }
        return data;
      }

      if (data.code === 'start_refresh_required') {
        // This tab can't say which 1st inning the coach reviewed: reload the
        // plan rather than guess.
        const choice = await startQuestion({
          title: data.title || 'Refresh Prepare Game before starting.',
          message: data.message,
          actions: [{label: 'Refresh', value: 'refresh', primary: true}],
        });
        if (choice === 'refresh') window.location.reload();
        return null;
      }

      if (data.code === 'start_defense_changed') {
        window.CBPregameDefense?.refresh?.();
        const choice = await startQuestion({
          title: '1st inning defense changed',
          message: data.message,
          actions: [{label: 'Review 1st Inning Defense', value: 'fix', primary: true}],
        });
        if (choice === 'fix') showFirstInningDefense();
        return null;
      }

      if (data.code === 'start_open_positions' && data.open_question) {
        const question = data.open_question;
        const choice = await startQuestion({
          title: question.title,
          message: data.acknowledgement_outdated
            ? `The open positions changed. ${question.message}`
            : question.message,
          actions: [
            {label: 'Fix 1st Inning Defense', value: 'fix', primary: true},
            {label: question.start_label, value: 'start'},
          ],
        });
        if (choice === 'start') {
          openAcknowledged = question.positions;
          continue;
        }
        if (choice === 'fix') showFirstInningDefense();
        return null;
      }

      // The starter comes last, after the defense checks. A decision counts
      // only for what the coach was shown; if that changed, the server asks
      // again (decision_outdated).
      if (STARTER_QUESTIONS.has(data.code)) {
        const choice = await askStartingPitcher(data);
        if (choice === 'decide') {
          pitchingDecision = {
            pitching_decision: data.required_decision,
            pitching_decision_status: data.pitching_status || '',
            pitching_decision_rule_set: data.decision_rule_set || '',
            pitching_decision_reason: data.decision_reason || '',
          };
          continue;
        }
        if (choice === 'another') chooseAnotherPitcher();
        if (choice === 'rules') chooseRules();
        return null;
      }

      const stops = (Array.isArray(data.hard_stops) && data.hard_stops.length)
        ? data.hard_stops
        : (Array.isArray(data.missing) ? data.missing : []);
      if (stops.length) {
        const aboutDefense = stops.some(stop => /1st inning/.test(stop));
        const choice = await startQuestion({
          title: "Can't start yet",
          message: 'Fix this first:',
          list: stops,
          actions: aboutDefense
            ? [{label: 'Fix 1st Inning Defense', value: 'fix', primary: true}, {label: 'Close', value: null}]
            : [{label: 'Close', value: null, primary: true}],
        });
        if (choice === 'fix') showFirstInningDefense();
        return null;
      }

      throw new Error(data.message || 'Unable to start the game.');
    }
  }

  window.CBStartGame = {start: startGame};

  const liveGameContract = {
    setMode,
    endInning: endInningFromNext,
    apply: applyContract,
  };

  window.CBLiveGameContract =
    liveGameContract;

  // Temporary compatibility alias for any cached/helper code that still
  // references the historical name.
  window.CBTest2Contract =
    liveGameContract;

  function start() {
    installStyles();
    ensureClockControls();
    applyContract();
    const observer = new MutationObserver(queueContract);
    observer.observe(document.body, {childList:true, subtree:true});
    window.addEventListener('orientationchange', queueContract, {passive:true});
    window.addEventListener('resize', queueContract, {passive:true});
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
