// Classic Prepare Game: the Game Day strip above the original game page.
//
// Presentation only. Every decision comes from the shared behavior:
//
// * readiness: the coachboard:readiness event game_prep_readiness.js
//   publishes from /api/game-day/<id>/readiness (the same 5-second feed
//   Updated's Start Game uses);
// * Start Live Game: window.CBStartGame (start_game_flow.js), the same
//   flow and server checks as Updated;
// * save status: the shared pregame save queue (CBPregameRotation), the
//   only writer of the defense on this page;
// * a live game is always shown in Updated, so once this game is live --
//   started here, or by another coach -- the page reloads and the server
//   shows the live screens.
(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match || document.body?.dataset.cbView !== 'classic') return;
  const gameId = Number(match[1]);

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));

  let starting = false;
  let handingOff = false;
  let lastReadiness = null;

  // --- Live hand-off ----------------------------------------------------------

  function handOffToLive() {
    if (handingOff) return;
    handingOff = true;
    const summary = $('classic-start-summary');
    if (summary) summary.textContent = 'This game is live. Opening the live game…';
    window.location.reload();
  }

  // --- Save status --------------------------------------------------------------

  const SAVE_TEXT = {
    saving: 'Saving…',
    saved: 'Saved',
    failed: 'Not saved — tap to retry',
  };

  function renderSaveStatus(status) {
    const pill = $('classic-save-status');
    const store = window.CBPregameRotation;
    if (!pill || !store) return;
    const state = status || store.getStatus();
    const unsynced = store.hasUnsyncedLocalState() || store.isSaveInFlightOrQueued();
    const shown = state === 'idle' && unsynced ? 'saving' : state;
    pill.dataset.state = shown;
    const code = shown === 'failed' ? store.getLastError?.()?.code : null;
    pill.textContent = code === 'rotation_conflict'
      ? 'Not saved — another coach changed this; tap to choose'
      : code === 'rotation_refresh_required'
        ? 'Not saved — refresh this page to keep editing'
        : (SAVE_TEXT[shown] || 'All changes saved');
    pill.className = `badge rounded-pill cb-classic-save ${
      shown === 'failed' ? 'text-bg-danger'
        : shown === 'saving' ? 'text-bg-warning'
          : shown === 'saved' ? 'text-bg-success'
            : 'text-bg-light border'}`;
    if (shown === 'failed') {
      pill.setAttribute('role', 'button');
      pill.tabIndex = 0;
      const error = store.getLastError?.();
      pill.title = error?.message || 'The last change to the defense was not saved.';
    } else {
      pill.setAttribute('role', 'status');
      pill.removeAttribute('tabindex');
      pill.removeAttribute('title');
    }
  }

  function retrySave() {
    const store = window.CBPregameRotation;
    if (!store || store.getStatus() !== 'failed') return;
    store.retry(undefined, true);
  }

  // --- Start Live Game ------------------------------------------------------------

  function renderReadiness(response) {
    lastReadiness = response;
    const readiness = response?.readiness || {};
    if (readiness.is_live) {
      handOffToLive();
      return;
    }
    const button = $('startLiveGameBtnAction');
    const summary = $('classic-start-summary');
    const box = $('start-live-blockers');
    if (!button || !summary || !box) return;

    const missing = Array.isArray(response?.missing) ? response.missing.filter(Boolean) : [];
    const ready = response?.ready === true;
    button.disabled = !ready || starting;
    button.classList.toggle('disabled', button.disabled);

    // An open position or missing rules is the coach's call: Start stays
    // usable and asks about it (the same as Updated).
    const asks = [];
    if (ready && response.open_question) {
      asks.push(`${response.open_question.title} ${response.open_question.message || ''}`.trim());
    }
    if (ready && response.pitching_rules_selected === false) {
      asks.push("Pitching rules aren't selected for this game, so CoachBoard can't confirm the starting pitcher's eligibility.");
    }

    if (!ready) {
      summary.textContent = 'Finish setup before first pitch.';
      box.className = 'alert alert-warning mb-0 mt-3';
      box.innerHTML = `<strong>Before you can start:</strong><ul class="mb-0 mt-1 ps-3">${
        (missing.length ? missing : ['Finish setup before first pitch.']).map((text) => `<li>${esc(text)}</li>`).join('')}</ul>`;
    } else if (asks.length) {
      summary.textContent = 'Ready. Start Live Game will ask you first:';
      box.className = 'alert alert-warning mb-0 mt-3';
      box.innerHTML = `<ul class="mb-0 ps-3">${asks.map((text) => `<li>${esc(text)}</li>`).join('')}</ul>`;
    } else {
      summary.textContent = 'Ready for first pitch. The batting order and later innings can be finished later.';
      box.className = 'alert mb-0 mt-3 d-none';
      box.innerHTML = '';
    }
    renderRulesNote(response);
  }

  // The Pitcher Availability table shows the server's eligibility; without the
  // game's rules it cannot confirm it, so say so right above the table.
  function renderRulesNote(response) {
    const card = $('pitcher-availability-card');
    if (!card) return;
    let note = $('classic-rules-note');
    if (response?.pitching_rules_selected !== false) {
      note?.remove();
      return;
    }
    if (!note) {
      note = document.createElement('div');
      note.id = 'classic-rules-note';
      note.className = 'alert alert-warning py-2 small';
      note.setAttribute('role', 'note');
      note.textContent = "Game rules haven't been selected, so this table can't confirm who may pitch today. Choose the game's rules above; Start Live Game will also ask.";
      card.insertAdjacentElement('beforebegin', note);
    }
  }

  async function startLiveGame(event) {
    event.preventDefault();
    const button = event.currentTarget;
    if (starting || button.disabled || !window.CBStartGame) return;
    starting = true;
    button.disabled = true;
    const label = button.innerHTML;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> Starting…';
    try {
      const started = await window.CBStartGame.start();
      if (started) {
        handOffToLive();
        return;
      }
    } catch (error) {
      const box = $('start-live-blockers');
      if (box) {
        box.className = 'alert alert-danger mb-0 mt-3';
        box.textContent = error?.message || 'Unable to start the game. Try again.';
      }
    }
    starting = false;
    button.innerHTML = label;
    if (lastReadiness) renderReadiness(lastReadiness);
    else button.disabled = false;
  }

  // --- Availability and Batting Lineup cards (another coach's changes) -------------

  function renderGameData(data) {
    if (!data) return;
    const absent = new Set((data.absent_player_ids || []).map(Number));
    const roster = data.roster || [];
    const present = $('availabilityPresentCount');
    const absentCount = $('classicAbsentCount');
    if (present) present.textContent = String(roster.length - absent.size);
    if (absentCount) absentCount.textContent = String(absent.size);
    const outNames = roster.filter((player) => absent.has(Number(player.id))).map((player) => player.name);
    let names = $('classicAbsentNames');
    if (outNames.length) {
      if (!names) {
        names = document.createElement('p');
        names.id = 'classicAbsentNames';
        names.className = 'small text-muted mb-2';
        absentCount?.closest('p')?.insertAdjacentElement('afterend', names);
      }
      if (names) names.textContent = `Out: ${outNames.join(', ')}`;
    } else {
      names?.remove();
    }

    const body = $('lineup-card-body');
    const order = data.lineup?.lineup_positions || [];
    if (body) {
      body.innerHTML = order.length
        ? `<ol class="list-group list-group-numbered">${order.map((name) => (outNames.includes(name)
          ? `<li class="list-group-item list-group-item-danger">${esc(name)} <span class="badge text-bg-danger">Out</span></li>`
          : `<li class="list-group-item">${esc(name)}</li>`)).join('')}</ol>`
        : '<div class="text-center p-3 text-muted"><p class="mb-1">No lineup has been set.</p></div>';
    }
  }

  // --- Wiring -------------------------------------------------------------------------

  function start() {
    $('startLiveGameBtnAction')?.addEventListener('click', startLiveGame);
    const pill = $('classic-save-status');
    pill?.addEventListener('click', retrySave);
    pill?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        retrySave();
      }
    });
    window.CBPregameRotation?.onStatusChange(renderSaveStatus);
    window.CBPregameRotation?.onChange(() => renderSaveStatus());
    renderSaveStatus();

    document.addEventListener('coachboard:readiness', (event) => {
      if (Number(event.detail?.game_id) !== gameId) return;
      renderReadiness(event.detail.response);
    });
    document.addEventListener('coachboard:game-data', (event) => {
      if (Number(event.detail?.game_id) !== gameId) return;
      if (event.detail.data?.game?.is_live) {
        handOffToLive();
        return;
      }
      renderGameData(event.detail.data);
    });
    document.addEventListener('coachboard:game-state-broadcast', (event) => {
      if (Number(event.detail?.game_id) === gameId && event.detail.is_live) handOffToLive();
    });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once: true})
    : start();
})();
