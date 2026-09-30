(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const STYLE_ID = 'cb-live-dugout-workflow-style';
  const nativeFetch = window.fetch.bind(window);
  let started = false;

  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setHtml = (el, value) => {
    if (el && el.innerHTML !== value) el.innerHTML = value;
  };

  if (typeof window.io === 'function' && !window.io.__cbSocketExposed) {
    const originalIo = window.io;
    const exposedIo = function(...args) {
      const socket = originalIo.apply(this, args);
      window.__cbLiveGameSocket = socket;
      return socket;
    };
    Object.keys(originalIo).forEach(key => { try { exposedIo[key] = originalIo[key]; } catch (_) {} });
    exposedIo.__cbSocketExposed = true;
    exposedIo.__cbOriginal = originalIo;
    window.io = exposedIo;
  }

  // Every On the Field defensive change. While the current inning has no
  // start marker the server asks "Has the 4th inning started?"
  // (inning_start_question, see game_availability.py) instead of saving;
  // askInningStarted() puts that to the coach and the same request is sent
  // again with the answer. CoachBoard counts no outs, so only the coach
  // knows whether play has begun. "Cancel change" sends nothing: the caller
  // gets inning_start_cancelled (cancelledChange) and the field stays as it
  // was.
  const ON_THE_FIELD = new Set([
    'defensive-change',
    'defense-edit',
    'set-defense',
    'complete-pitcher-change',
    'change-pitcher',
  ]);
  const INNING_START_MODAL_ID = 'cbInningStartModal';
  let pendingInningQuestion = null;

  function onTheFieldPath(pathname) {
    const prefix = `/api/live-game/${gameId}/`;
    return pathname.startsWith(prefix) && ON_THE_FIELD.has(pathname.slice(prefix.length));
  }

  function inningStartModal() {
    let modal = document.getElementById(INNING_START_MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = INNING_START_MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.setAttribute('data-bs-keyboard', 'false');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header"><h5 class="modal-title" data-cb-inning-start-title></h5></div>
          <div class="modal-body"><div data-cb-inning-start-message></div></div>
          <div class="modal-footer">
            <button type="button" class="btn btn-link text-secondary me-auto" data-cb-inning-start="cancel">Cancel change</button>
            <button type="button" class="btn btn-outline-secondary" data-cb-inning-start="not_yet"></button>
            <button type="button" class="btn btn-primary" data-cb-inning-start="yes"></button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  // Resolves 'yes', 'not_yet' or 'cancel'. Changes waiting on the same inning
  // share one question, so one Cancel abandons all of them. The answer counts on the tap, even while the sheet is still
  // opening (Bootstrap ignores hide() mid-transition).
  function askInningStarted(question) {
    const inning = String(question.inning || '');
    if (pendingInningQuestion && pendingInningQuestion.inning === inning) {
      return pendingInningQuestion.answer;
    }
    const answer = (async () => {
      const modal = inningStartModal();
      if (modal.style.display === 'block' && !modal.classList.contains('show')) {
        await new Promise(resolve => modal.addEventListener('hidden.bs.modal', resolve, {once: true}));
      }
      setText(modal.querySelector('[data-cb-inning-start-title]'), question.title || 'Has this inning started?');
      setText(modal.querySelector('[data-cb-inning-start-message]'), question.message || '');
      const notYet = modal.querySelector('[data-cb-inning-start="not_yet"]');
      const yes = modal.querySelector('[data-cb-inning-start="yes"]');
      setText(notYet, question.not_yet_label || 'Not yet');
      setText(yes, question.yes_label || 'Yes, inning started');

      if (!window.bootstrap?.Modal) return 'cancel';
      return new Promise(resolve => {
        const instance = window.bootstrap.Modal.getOrCreateInstance(modal, {backdrop: 'static', keyboard: false});
        let answered = false;
        const decide = value => {
          if (!answered) {
            answered = true;
            resolve(value);
          }
          instance.hide();
        };
        const cancel = modal.querySelector('[data-cb-inning-start="cancel"]');
        notYet.onclick = () => decide('not_yet');
        yes.onclick = () => decide('yes');
        cancel.onclick = () => decide('cancel');
        modal.addEventListener('shown.bs.modal', () => { if (answered) instance.hide(); }, {once: true});
        instance.show();
      });
    })();
    const entry = {inning, answer};
    pendingInningQuestion = entry;
    answer.finally(() => {
      if (pendingInningQuestion === entry) pendingInningQuestion = null;
    });
    return answer;
  }

  function cancelledChange() {
    return new Response(JSON.stringify({
      status: 'error',
      code: 'inning_start_cancelled',
      message: 'Change cancelled. Nothing was saved.',
    }), {status: 409, headers: {'Content-Type': 'application/json'}});
  }

  async function answerInningStart(input, init) {
    const response = await bridgeDefensiveChange(input, init);
    if (response.status !== 409 || typeof input !== 'string') return response;
    const method = String(init?.method || 'GET').toUpperCase();
    let pathname = '';
    try { pathname = new URL(input, window.location.href).pathname; } catch (_) {}
    if (method !== 'POST' || !onTheFieldPath(pathname)) return response;

    const question = await response.clone().json().catch(() => null);
    if (question?.code !== 'inning_start_question') return response;

    let body = {};
    try { body = JSON.parse(init.body || '{}'); } catch (_) { return response; }
    const answer = await askInningStarted(question);
    if (answer !== 'yes' && answer !== 'not_yet') return cancelledChange();
    body.inning_started = answer === 'yes';
    return bridgeDefensiveChange(input, {...init, body: JSON.stringify(body)});
  }

  async function bridgeDefensiveChange(input, init = {}) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    let pathname = '';
    try { pathname = new URL(url, window.location.href).pathname; } catch (_) {}

    if (method === 'POST' && pathname === `/api/live-game/${gameId}/start`) {
      const response = await nativeFetch(input, init);
      if (response.ok) {
        const data = await response.clone().json().catch(() => ({}));
        if (data?.state?.game?.is_live) {
          // The unified controller may still hold pre-start state. Seed it from
          // the authoritative Start response before the normal socket delta arrives.
          pushStateIntoUnifiedController(data.state);
        }
      }
      return response;
    }

    // Quick Field still uses the legacy defensive-change endpoint name for a
    // single-player move. Translate that request into the authoritative full
    // alignment edit so Quick Field remains the only live defense surface.
    if (method !== 'POST' || pathname !== `/api/live-game/${gameId}/defensive-change`) return nativeFetch(input, init);

    let requested = {};
    try { requested = JSON.parse(init.body || '{}'); } catch (_) { return nativeFetch(input, init); }
    const playerId = Number(requested.player_id);
    const destination = String(requested.destination_position || 'BENCH').toUpperCase();
    if (!Number.isFinite(playerId) || destination === 'P') return nativeFetch(input, init);

    const stateResponse = await nativeFetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
    if (!stateResponse.ok) return nativeFetch(input, init);
    const current = await stateResponse.json();
    const player = (current.roster || []).find(item => Number(item.id) === playerId);
    if (!player) return nativeFetch(input, init);

    const after = {...(current.current_alignment || {})};
    const source = Object.entries(after).find(([, name]) => name === player.name)?.[0] || '';
    if (destination === 'BENCH') {
      if (source) delete after[source];
      return nativeFetch(input, init);
    }

    const occupant = after[destination] || '';
    if (source) delete after[source];
    after[destination] = player.name;
    if (occupant && occupant !== player.name && source) after[source] = occupant;

    const editResponse = await nativeFetch(`/api/live-game/${gameId}/defense-edit`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        alignment:after,
        base_sequence:requested.base_sequence,
        ...(requested.inning_started === undefined ? {} : {inning_started:requested.inning_started}),
      }),
    });
    if (!editResponse.ok) return editResponse;
    const editData = await editResponse.clone().json().catch(() => ({}));
    const delta = editData.delta || {};
    const syntheticState = {
      ...current,
      current_inning: String(delta.current_inning || current.current_inning || '1'),
      current_alignment: {...(delta.current_alignment || after)},
      current_pitcher: delta.current_pitcher || (delta.current_alignment || after).P || current.current_pitcher,
      bench: Array.isArray(delta.bench) ? delta.bench : current.bench,
      rotation_events: delta.event ? [...(current.rotation_events || []), delta.event] : (current.rotation_events || []),
    };
    return new Response(JSON.stringify({status:'success', state:syntheticState, delta}), {
      status:200,
      headers:{'Content-Type':'application/json'},
    });
  }

  window.fetch = answerInningStart;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.cb-dugout #cbQuickDefense .cb-qd-actions{display:none!important}
      body.cb-dugout #cbQuickDefense .cb-bench-note{display:none!important}
      body.cb-dugout #coach-action-slot.coach-actions{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}
      body.cb-dugout #liveChangePitcherBtn,body.cb-dugout #liveEndInningBtn{min-height:62px!important}
      /* Undo is presented in the dark #cbDugoutHeader, not as a row inside
         #coach-action-slot, so the grid-column/underlined-link treatment that
         used to live here no longer has a subject. */
      body.cb-dugout #liveChangePitcherBtn .coach-action-note,body.cb-dugout #liveEndInningBtn .coach-action-note{font-size:0!important;opacity:.78!important}
      body.cb-dugout #liveChangePitcherBtn .coach-action-note::after{content:'This inning';font-size:.67rem}
      body.cb-dugout #liveEndInningBtn .coach-action-note::after{content:'Send next defense out';font-size:.67rem}
      body.cb-dugout #cbQuickDefense .cb-qd-bench{display:flex!important;visibility:visible!important}
      @media(max-width:575.98px){html body.cb-dugout #cbQuickDefense .cb-qd-head{padding:8px 9px 7px!important}html body.cb-dugout #cbQuickDefense .cb-qd-title{font-size:.9rem!important}html body.cb-dugout #cbQuickDefense .cb-qd-help{font-size:var(--cb-text-xs)!important}html body.cb-dugout #cbQuickDefense .cb-qd-body{padding:6px 7px 8px!important}html body.cb-dugout #cbQuickDefense .cb-qd-field{min-height:0!important;max-height:228px!important;aspect-ratio:1.58/1!important}html body.cb-dugout #cbQuickDefense .cb-qd-spot{width:66px!important;min-height:30px!important}html body.cb-dugout #cbQuickDefense .cb-qd-name{font-size:var(--cb-marker-name)!important;padding:2px!important}/* The phone field is short: shortstop and second base names reach down beside the pitcher. The current pitcher's jersey is already in the live header just above, so the pitcher marker shows only P here. */html body.cb-dugout #cbQuickDefense .cb-qd-spot.pitcher .cb-qd-num{display:none!important}html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap{margin-top:6px!important;padding:7px!important}html body.cb-dugout #cbQuickDefense .cb-qd-bench-player{padding:6px 7px!important;font-size:.66rem!important}html body.cb-dugout .coach-live-shell{padding-bottom:calc(96px + env(safe-area-inset-bottom))!important}body.cb-dugout #coach-action-slot.coach-actions{position:fixed;left:0;right:0;bottom:0;z-index:1030;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important;background:#eef1f4;border-top:1px solid #d7dde5;box-shadow:0 -6px 18px rgba(16,24,40,.12);padding:8px 10px calc(8px + env(safe-area-inset-bottom));margin:0!important}body.cb-dugout #coach-action-slot.coach-actions.cb-single-live-action{grid-template-columns:minmax(0,1fr)!important}body.cb-dugout #coach-action-slot.coach-actions.cb-single-live-action #liveEndInningBtn{width:100%!important}body.cb-dugout #liveChangePitcherBtn,body.cb-dugout #liveEndInningBtn{min-height:56px!important}}@media(max-width:374.98px){html body.cb-dugout #cbQuickDefense .cb-qd-spot{width:61px!important}}
      @media(orientation:landscape) and (max-height:599.98px){html body.cb-dugout #cbQuickDefense .cb-qd-field{max-height:205px!important;width:min(62vw,480px)!important}}
    `;
    document.head.appendChild(style);
  }

  function patchMenu() {
    const modal = document.getElementById('cbCoachBoardNavModal');
    if (!modal) return;
    setText(modal.querySelector('.modal-header .small.text-muted'), 'Game stays live.');
    setHtml(modal.querySelector('.cb-nav-safe'), '<strong>Game stays live.</strong> Clock stays as-is.');
  }

  function pushStateIntoUnifiedController(current) {
    const events = Array.isArray(current?.rotation_events) ? current.rotation_events : [];
    const sequence = events.reduce((max, item) => item?.reverted ? max : Math.max(max, Number(item?.sequence) || 0), 0);
    const delta = {
      game_id: gameId,
      current_inning: String(current?.current_inning || current?.game?.live_current_inning || '1'),
      current_alignment: {...(current?.current_alignment || {})},
      current_pitcher: current?.current_pitcher || current?.current_alignment?.P || null,
      bench: Array.isArray(current?.bench) ? current.bench : [],
      sequence,
    };
    const socket = window.__cbLiveGameSocket;
    const listeners = typeof socket?.listeners === 'function' ? socket.listeners('live_game_delta') : [];
    if (listeners?.length) {
      listeners.forEach(listener => listener(delta));
      return true;
    }
    if (typeof socket?.emitEvent === 'function') {
      socket.emitEvent(['live_game_delta', delta]);
      return true;
    }
    return false;
  }

  function loadUnifiedFeedbackPass() {
    if ([...document.scripts].some(node => /\/static\/js\/live_game_feedback_pass\.js(?:\?|$)/.test(node.src || ''))) return;
    if (document.readyState === 'loading') {
      document.write(
        '<script src="' +
        window.CoachBoardAssets.url('/static/js/live_game_feedback_pass.js') +
        '" data-cb-live-feedback-pass="true"></' + 'script>'
      );
      return;
    }
    const script = document.createElement('script');
    script.src = window.CoachBoardAssets.url('/static/js/live_game_feedback_pass.js');
    script.dataset.cbLiveFeedbackPass = 'true';
    document.body.appendChild(script);
  }

  function start() {
    if (started) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', start, {once:true});
      return;
    }
    started = true;
    installStyles();
    document.getElementById('cbCurrentInningStrip')?.remove();
    document.addEventListener('click', event => {
      if (event.target.closest?.('[data-cb-menu], #cbCoachBoardNavBtn')) window.setTimeout(patchMenu, 0);
    }, true);
    loadUnifiedFeedbackPass();
  }

  start();
})();