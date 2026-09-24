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

  async function getJson(path) {
    const response = await fetch(path, {cache:'no-store'});
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
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Request failed (${response.status}).`);
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

  async function waitForLiveWritesToSettle() {
    await waitForQuickFieldSave();

    let previous = null;

    for (
      let attempt = 0;
      attempt < 12;
      attempt += 1
    ) {
      const state = await getJson(
        `/api/live-game/${gameId}/state`
      );

      const signature =
        `${state.current_inning || ''}:` +
        `${sequenceFromState(state)}`;

      if (signature === previous) {
        return state;
      }

      previous = signature;
      await sleep(120);
    }

    return getJson(
      `/api/live-game/${gameId}/state`
    );
  }

  function showInningRecoveryNotice(inning) {
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

  function openCurrentDefensePositions(
    liveState
  ) {
    const alignment =
      liveState?.current_alignment || {};

    return requiredDefensePositions(
      liveState
    ).filter(
      position =>
        !String(
          alignment[position] || ''
        ).trim()
    );
  }

  function openDefenseMessage(open) {
    if (open.length === 1) {
      return `${open[0]} is still Open.`;
    }

    if (open.length === 2) {
      return (
        `${open[0]} and ${open[1]} ` +
        'are still Open.'
      );
    }

    return (
      `${open.slice(0, -1).join(', ')}, ` +
      `and ${open[open.length - 1]} ` +
      'are still Open.'
    );
  }

  function ensureOpenDefenseEndModal() {
    let modal =
      $('cbOpenDefenseEndModal');

    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'cbOpenDefenseEndModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute(
      'aria-hidden',
      'true'
    );

    modal.innerHTML = `
      <div
        class="
          modal-dialog
          modal-dialog-centered
        "
      >
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              Defense still open
            </h5>

            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>

          <div class="modal-body">
            <div
              class="fw-semibold"
              data-cb-open-defense-message
            ></div>

            <div
              class="
                small
                text-muted
                mt-2
              "
            >
              Fix the position on On the Field,
              or end the inning anyway. You can
              also correct this inning from the
              Game Report after the game.
            </div>
          </div>

          <div class="modal-footer">
            <button
              type="button"
              class="
                btn
                btn-outline-secondary
              "
              data-bs-dismiss="modal"
            >
              Go Back
            </button>

            <button
              type="button"
              class="btn btn-primary"
              data-cb-end-inning-anyway
            >
              End Inning Anyway
            </button>
          </div>
        </div>
      </div>`;

    document.body.appendChild(modal);

    return modal;
  }

  function warnOpenCurrentDefense(
    open
  ) {
    const modal =
      ensureOpenDefenseEndModal();

    const message =
      modal.querySelector(
        '[data-cb-open-defense-message]'
      );

    if (message) {
      message.textContent =
        openDefenseMessage(open);
    }

    const confirm =
      modal.querySelector(
        '[data-cb-end-inning-anyway]'
      );

    confirm.onclick = () => {
      const instance =
        bootstrap.Modal
          .getOrCreateInstance(modal);

      modal.addEventListener(
        'hidden.bs.modal',
        () => {
          endInningFromNext(true);
        },
        {
          once: true,
        }
      );

      instance.hide();
    };

    bootstrap.Modal
      .getOrCreateInstance(modal)
      .show();
  }

  async function endInningFromNext(
    allowOpenCurrent = false
  ) {
    if (inningAdvanceBusy) return;

    const button =
      $('liveEndInningBtn');

    if (!button || button.disabled) {
      return;
    }

    inningAdvanceBusy = true;

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

      const [prep, liveState] =
        await Promise.all([
          getJson(
            `/api/live-game/${gameId}/next-inning-prep`
          ),
          getJson(
            `/api/live-game/${gameId}/state`
          ),
        ]);

      const currentInning = String(
        liveState?.current_inning ||
        ''
      );

      const openCurrent =
        openCurrentDefensePositions(
          liveState
        );

      if (
        openCurrent.length &&
        !allowOpenCurrent
      ) {
        warnOpenCurrentDefense(
          openCurrent
        );
        return;
      }

      if (
        currentInning !==
        String(prep?.current_inning || '')
      ) {
        recoverAdvancedInning(
          liveState
        );
        return;
      }

      const alignment = {
        ...(prep?.confirmed?.alignment || {}),
      };

      if (!alignment.P) {
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
        }
      );

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
      try {
        const fresh = await getJson(
          `/api/live-game/${gameId}/state`
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
