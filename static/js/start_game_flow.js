// Start Game, shared by the Updated and Classic Prepare Game screens.
//
// Moved out of live_game_contract.js unchanged, so both views run exactly the
// same Start: the same save settling, the same reviewed 1st inning, the same
// open-position, starting-pitcher and hard-stop questions, all decided by
// the server (/api/live-game/<id>/start). Only "take me to fix it" knows
// which defense editor is on the page.
//
// It also owns the open-position acknowledgements both views share
// (window.CBRecordAcks), which live_game_contract.js reads in live play.
(() => {
  'use strict';

  const route = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!route) return;

  const gameId = Number(route[1]);
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[char]));
  const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));

  // An open position the coach chose to start or continue with, remembered
  // for this tab (sessionStorage), so a deliberate "Start with CF Open" at
  // first pitch survives the page reload into live play.
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

  window.CBRecordAcks = {
    key: recordKey,
    has: key => acknowledgedRecords.has(key),
    add: acknowledgeRecord,
  };

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

  // The defense editor on this page: Updated's tap field, or Classic's
  // bench-and-diamond (#rotation-board, static/js/game_logic.js).
  const defenseEditor = () => $('pregame-defense-editor-v3') || $('rotation-board');

  function showFirstInningDefense() {
    const quickStart = $('cb-quick-start-modal');
    if (quickStart) window.bootstrap?.Modal?.getInstance(quickStart)?.hide();
    const first = document.querySelector('#inning-btn-group input[name="inning-radio"][value="1"]');
    if (first && !first.checked) first.click();
    window.setTimeout(() => {
      defenseEditor()?.scrollIntoView({behavior: 'smooth', block: 'start'});
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
  // Classic's diamond removes a player when their position is tapped, so it
  // is only pointed out there, never tapped for the coach.
  function chooseAnotherPitcher() {
    showFirstInningDefense();
    window.setTimeout(() => {
      const updated = document.querySelector('#pregame-defense-editor-v3 [data-pde-pos="P"]');
      if (updated) {
        updated.click();
        return;
      }
      const spot = [...document.querySelectorAll('#pos-desktop-P, #pos-mobile-P')]
        .find(el => el.getClientRects().length);
      if (!spot) return;
      spot.scrollIntoView({behavior: 'smooth', block: 'center'});
      spot.classList.add('cb-start-attention');
      window.setTimeout(() => spot.classList.remove('cb-start-attention'), 2400);
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
      // An arm-care concern (in the message) also offers another pitcher.
      return startQuestion({
        title: info.eligibility_heading,
        message,
        actions: [
          {label: 'Choose Rules', value: 'rules', primary: true},
          ...(info.arm_care_concern ? [another] : []),
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
})();
