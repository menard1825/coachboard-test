(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  let latestState = null;
  let busy = false;

  function loadPitchingWorkloadUi() {
    if (document.querySelector('script[data-pitching-workload-game]')) return;
    const script = document.createElement('script');
    script.src = '/static/js/live_game_pitching_workload.js';
    script.dataset.pitchingWorkloadGame = 'true';
    document.head.appendChild(script);
  }

  loadPitchingWorkloadUi();

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  async function loadState() {
    const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
    if (!response.ok) throw new Error('Unable to load current game state.');
    latestState = await response.json();
    return latestState;
  }

  function addPitcher(order, name) {
    if (name && !order.includes(name)) order.push(name);
  }

  function pitcherOrder(state) {
    const order = [];
    const events = [...(state.rotation_events || [])]
      .filter(e => !e.reverted)
      .sort((a,b) => Number(a.sequence || 0) - Number(b.sequence || 0));

    events.forEach(event => {
      addPitcher(order, event.before_alignment?.P);
      addPitcher(order, event.after_alignment?.P);
    });

    const maxReached = Number(state.current_inning || state.game?.live_current_inning || 1);
    Object.entries(state.actual_rotation || {})
      .sort((a,b) => Number(a[0]) - Number(b[0]))
      .filter(([inning]) => !Number.isFinite(maxReached) || Number(inning) <= maxReached)
      .forEach(([, alignment]) => addPitcher(order, alignment?.P));

    addPitcher(order, state.current_alignment?.P);
    return order;
  }

  function splitInnings(value) {
    if (value === null || value === undefined || value === '') return ['', '0'];
    const [whole, outs = '0'] = String(value).split('.');
    return [whole, ['0','1','2'].includes(outs) ? outs : '0'];
  }

  function clearStaleModalLayer(modalEl) {
    const otherOpenModals = [...document.querySelectorAll('.modal.show')]
      .filter(modal => modal !== modalEl);
    if (otherOpenModals.length) return;

    document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
    if (!modalEl?.classList.contains('show')) {
      document.body.classList.remove('modal-open');
      document.body.style.removeProperty('overflow');
      document.body.style.removeProperty('padding-right');
    }
  }

  function prepareFinalCountsModal() {
    const modalEl = document.getElementById('liveFinalCountsModal');
    if (!modalEl) return null;

    if (modalEl.parentElement !== document.body) {
      document.body.appendChild(modalEl);
    }
    modalEl.style.zIndex = '1060';

    if (modalEl.dataset.coachboardLayerFixed !== '1') {
      modalEl.dataset.coachboardLayerFixed = '1';
      modalEl.addEventListener('show.bs.modal', () => clearStaleModalLayer(modalEl));
      modalEl.addEventListener('shown.bs.modal', () => {
        const backdrops = [...document.querySelectorAll('.modal-backdrop')];
        if (backdrops.length > 1 && !document.querySelector('.modal.show:not(#liveFinalCountsModal)')) {
          backdrops.slice(0, -1).forEach(backdrop => backdrop.remove());
        }
        modalEl.querySelector('input, select, button')?.focus({preventScroll:true});
      });
      modalEl.addEventListener('hidden.bs.modal', () => clearStaleModalLayer(modalEl));
    }

    return modalEl;
  }

  function cardFields(card) {
    return {
      pitches: card.querySelector('.final-complete-pitches'),
      innings: card.querySelector('.final-complete-innings'),
      outs: card.querySelector('.final-complete-outs'),
      status: card.querySelector('.final-entry-status'),
      preview: card.querySelector('.final-ip-preview'),
    };
  }

  function fieldPresent(input) {
    return !!input && String(input.value ?? '').trim() !== '';
  }

  function updatePitcherCardStatus(card) {
    const fields = cardFields(card);
    const hasPitches = fieldPresent(fields.pitches);
    const hasInnings = fieldPresent(fields.innings);
    const whole = hasInnings ? Number(fields.innings.value) : null;
    const outs = Number(fields.outs?.value || 0);
    const pitches = hasPitches ? Number(fields.pitches.value) : null;

    card.classList.remove('border-warning', 'border-success', 'border-danger');
    [fields.pitches, fields.innings, fields.outs].forEach(field => field?.classList.remove('is-invalid'));

    if (fields.preview) {
      fields.preview.textContent = hasInnings && Number.isInteger(whole) && whole >= 0 && [0,1,2].includes(outs)
        ? `GameChanger IP to save: ${whole}.${outs}`
        : 'Enter the IP exactly as GameChanger shows it.';
    }

    if (!fields.status) return;

    if (!hasPitches && !hasInnings) {
      fields.status.className = 'final-entry-status small text-muted mt-2';
      fields.status.innerHTML = '<i class="bi bi-arrow-up-circle me-1"></i>Enter both Pitch Count and Innings Pitched from GameChanger.';
      return;
    }

    if (hasPitches && (!Number.isInteger(pitches) || pitches < 0)) {
      card.classList.add('border-danger');
      fields.pitches?.classList.add('is-invalid');
      fields.status.className = 'final-entry-status small text-danger mt-2 fw-semibold';
      fields.status.textContent = 'Pitch Count must be a whole number of 0 or more.';
      return;
    }

    if (hasInnings && (!Number.isInteger(whole) || whole < 0 || ![0,1,2].includes(outs))) {
      card.classList.add('border-danger');
      fields.innings?.classList.add('is-invalid');
      fields.status.className = 'final-entry-status small text-danger mt-2 fw-semibold';
      fields.status.textContent = 'Innings must use full innings plus 0, 1, or 2 extra outs.';
      return;
    }

    if (hasPitches && !hasInnings) {
      card.classList.add('border-warning');
      fields.status.className = 'final-entry-status small text-warning-emphasis mt-2 fw-semibold';
      fields.status.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Pitch Count is entered. Add Innings Pitched before saving.';
      return;
    }

    if (!hasPitches && hasInnings) {
      card.classList.add('border-warning');
      fields.status.className = 'final-entry-status small text-warning-emphasis mt-2 fw-semibold';
      fields.status.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Innings Pitched is entered. Add the Pitch Count before saving.';
      return;
    }

    card.classList.add('border-success');
    fields.status.className = 'final-entry-status small text-success mt-2 fw-semibold';
    fields.status.innerHTML = `<i class="bi bi-check-circle me-1"></i>Ready: ${pitches} pitches · ${whole}.${outs} IP`;
  }

  function allPitcherCardsReady() {
    const cards = [...document.querySelectorAll('.final-pitcher-card')];
    return cards.length > 0 && cards.every(card => {
      const fields = cardFields(card);
      if (!fieldPresent(fields.pitches) || !fieldPresent(fields.innings)) return false;
      const pitches = Number(fields.pitches.value);
      const whole = Number(fields.innings.value);
      const outs = Number(fields.outs?.value || 0);
      return Number.isInteger(pitches) && pitches >= 0 && Number.isInteger(whole) && whole >= 0 && [0,1,2].includes(outs);
    });
  }

  function refreshSaveButton() {
    document.querySelectorAll('.final-pitcher-card').forEach(updatePitcherCardStatus);
    const button = document.getElementById('confirmFinalCountsBtn');
    if (!button || busy) return;
    const ready = allPitcherCardsReady();
    button.disabled = !ready;
    button.innerHTML = ready
      ? '<i class="bi bi-check2-circle me-1"></i>Save GameChanger Stats'
      : '<i class="bi bi-pencil-square me-1"></i>Complete All Pitching Stats';
  }

  function renderPitchingForm(state) {
    const container = document.getElementById('finalCountsFormContainer');
    if (!container) return;

    const order = pitcherOrder(state);
    const logByPlayer = new Map((state.game_pitching_log || []).map(o => [Number(o.player_id), o]));

    if (!order.length) {
      container.innerHTML = '<div class="text-muted text-center py-3">No pitchers were found in the live defensive history.</div>';
      return;
    }

    container.innerHTML = `
      <div class="alert alert-primary-subtle border mb-3">
        <div class="fw-bold mb-1"><i class="bi bi-clipboard-check me-1"></i>Copy both numbers from GameChanger</div>
        <div class="small">For each pitcher, enter the <strong>Pitch Count</strong> and <strong>IP (Innings Pitched)</strong>. They are separate stats. If GameChanger shows <strong>2.1 IP</strong>, enter <strong>2 full innings</strong> and <strong>1 extra out</strong>.</div>
        <div class="small mt-2">If a value is already filled in but GameChanger shows something different, replace it with the GameChanger number. GameChanger is the final source on this screen.</div>
      </div>
      ${order.map((name, index) => {
        const player = (state.roster || []).find(p => p.name === name);
        if (!player) return '';
        const existing = logByPlayer.get(Number(player.id)) || {};
        const [whole, outs] = splitInnings(existing.innings);
        const role = index === 0 ? 'Starter' : 'Reliever';
        return `
          <div class="border rounded-4 p-3 mb-3 final-pitcher-card" data-player-id="${player.id}" data-player-name="${esc(name)}">
            <div class="d-flex justify-content-between align-items-center mb-3 gap-2">
              <div>
                <strong class="final-pitcher-name d-block fs-5">${esc(name)}</strong>
                <span class="small text-muted">Enter exactly what GameChanger shows.</span>
              </div>
              <span class="badge text-bg-light border">${role}</span>
            </div>

            <div class="mb-3">
              <label class="form-label fw-semibold mb-1">Pitch Count</label>
              <input type="number" min="0" step="1" inputmode="numeric" class="form-control form-control-lg final-complete-pitches" value="${existing.pitches ?? ''}" placeholder="Example: 47">
            </div>

            <div class="rounded-3 bg-light border p-3">
              <div class="fw-semibold mb-1">Innings Pitched (IP)</div>
              <div class="small text-muted mb-2">Split the GameChanger IP into full innings and extra outs.</div>
              <div class="row g-2">
                <div class="col-7">
                  <label class="form-label small fw-semibold">Full Innings</label>
                  <input type="number" min="0" step="1" inputmode="numeric" class="form-control form-control-lg final-complete-innings" value="${esc(whole)}" placeholder="2">
                </div>
                <div class="col-5">
                  <label class="form-label small fw-semibold">Extra Outs</label>
                  <select class="form-select form-select-lg final-complete-outs">
                    <option value="0" ${outs==='0'?'selected':''}>0 outs</option>
                    <option value="1" ${outs==='1'?'selected':''}>1 out</option>
                    <option value="2" ${outs==='2'?'selected':''}>2 outs</option>
                  </select>
                </div>
              </div>
              <div class="final-ip-preview small text-muted mt-2"></div>
            </div>
            <div class="final-entry-status small text-muted mt-2"></div>
          </div>`;
      }).join('')}
      <div class="small text-muted border-top pt-3"><strong>Not sure yet?</strong> Tap <strong>Not Ready Yet</strong> and come back after GameChanger has the final pitching line. CoachBoard will not guess missing stats.</div>`;

    refreshSaveButton();
  }

  function configureVisibleLabels() {
    const endButton = document.getElementById('liveEndGameBtn');
    if (endButton) {
      endButton.innerHTML = '<i class="bi bi-stop-circle-fill me-1"></i> End Game';
      endButton.title = 'Finalize the game now. GameChanger pitching stats can be entered later.';
    }
  }

  async function finishGame() {
    if (busy) return;
    const okay = window.confirm('End this game now?\n\nThe actual defense and live history will be saved. You can enter the final GameChanger pitching stats later when they are ready.');
    if (!okay) return;

    busy = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/end-with-pitching`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({defer_pitching:true}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to end game.');
      window.location.assign(`/game-day/${gameId}/report`);
    } catch (err) {
      alert(err.message || 'Unable to end game.');
    } finally {
      busy = false;
    }
  }

  async function openPitchingEntry() {
    if (busy) return;
    busy = true;
    try {
      const state = await loadState();
      const modalEl = prepareFinalCountsModal();
      if (!modalEl) throw new Error('GameChanger pitching dialog is unavailable.');
      renderPitchingForm(state);
      const title = modalEl.querySelector('.modal-title');
      if (title) title.textContent = 'Enter GameChanger Pitching Stats';
      const confirm = modalEl.querySelector('#confirmFinalCountsBtn');
      if (confirm) {
        confirm.classList.remove('btn-danger');
        confirm.classList.add('btn-primary');
      }
      const cancel = modalEl.querySelector('.modal-footer [data-bs-dismiss="modal"]');
      if (cancel) {
        cancel.disabled = false;
        cancel.textContent = 'Not Ready Yet';
      }
      busy = false;
      refreshSaveButton();
      clearStaleModalLayer(modalEl);
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (err) {
      busy = false;
      alert(err.message || 'Unable to prepare GameChanger pitching entry.');
    }
  }

  function validatePitchingForm() {
    const cards = [...document.querySelectorAll('.final-pitcher-card')];
    for (const card of cards) {
      const name = card.dataset.playerName || 'Pitcher';
      const fields = cardFields(card);
      const hasPitches = fieldPresent(fields.pitches);
      const hasInnings = fieldPresent(fields.innings);

      if (hasPitches && !hasInnings) {
        fields.innings?.focus();
        return `${name}: You entered the pitch count, but Innings Pitched is blank. In GameChanger, copy the IP value too. Example: 2.1 IP = 2 full innings + 1 extra out.`;
      }
      if (!hasPitches && hasInnings) {
        fields.pitches?.focus();
        return `${name}: You entered Innings Pitched, but the Pitch Count is blank. Copy the pitch total from GameChanger too.`;
      }
      if (!hasPitches && !hasInnings) {
        fields.pitches?.focus();
        return `${name}: Enter both Pitch Count and Innings Pitched from GameChanger. If GameChanger is not ready yet, use “Not Ready Yet” instead of saving partial stats.`;
      }

      const pitches = Number(fields.pitches.value);
      const whole = Number(fields.innings.value);
      const outs = Number(fields.outs?.value || 0);
      if (!Number.isInteger(pitches) || pitches < 0) {
        fields.pitches?.focus();
        return `${name}: Pitch Count must be a whole number of 0 or more.`;
      }
      if (!Number.isInteger(whole) || whole < 0 || ![0,1,2].includes(outs)) {
        fields.innings?.focus();
        return `${name}: Innings Pitched must use full innings plus 0, 1, or 2 extra outs.`;
      }
    }
    return null;
  }

  async function savePitching() {
    if (busy) return;

    const validationMessage = validatePitchingForm();
    if (validationMessage) {
      alert(validationMessage);
      refreshSaveButton();
      return;
    }

    busy = true;
    const button = document.getElementById('confirmFinalCountsBtn');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }

    try {
      const counts = [...document.querySelectorAll('.final-pitcher-card')].map((card, index) => {
        const fields = cardFields(card);
        return {
          player_id: Number(card.dataset.playerId),
          pitches: Number(fields.pitches.value),
          innings_whole: Number(fields.innings.value),
          innings_outs: Number(fields.outs?.value || 0),
          pitcher_type: index === 0 ? 'Starter' : 'Reliever',
        };
      });

      const response = await fetch(`/api/live-game/${gameId}/end-with-pitching`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({counts}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to save GameChanger pitching stats.');

      const modalEl = prepareFinalCountsModal();
      if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      if (data.warnings?.length) {
        alert(`GameChanger stats were saved, but CoachBoard still found incomplete data:\n\n${data.warnings.join('\n')}\n\nReopen the pitching entry screen and copy both Pitch Count and IP from GameChanger.`);
      }
      window.location.assign(`/game-day/${gameId}/report`);
    } catch (err) {
      alert(err.message || 'Unable to save GameChanger pitching stats.');
      busy = false;
      refreshSaveButton();
      return;
    }

    busy = false;
  }

  document.addEventListener('input', event => {
    if (event.target.matches('.final-complete-pitches, .final-complete-innings')) {
      refreshSaveButton();
    }
  });

  document.addEventListener('change', event => {
    if (event.target.matches('.final-complete-outs')) {
      refreshSaveButton();
    }
  });

  document.addEventListener('click', event => {
    const endButton = event.target.closest('#liveEndGameBtn');
    if (endButton) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      finishGame();
      return;
    }

    const confirmButton = event.target.closest('#confirmFinalCountsBtn');
    if (confirmButton) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      savePitching();
    }
  }, true);

  prepareFinalCountsModal();
  configureVisibleLabels();
  document.addEventListener('DOMContentLoaded', () => {
    prepareFinalCountsModal();
    configureVisibleLabels();
  }, {once:true});

  const params = new URLSearchParams(window.location.search);
  if (params.get('pitching') === '1') {
    const launch = () => window.setTimeout(openPitchingEntry, 100);
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', launch, {once:true})
      : launch();
  } else if (params.get('finalize') === '1') {
    const launch = () => window.setTimeout(finishGame, 100);
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', launch, {once:true})
      : launch();
  }
})();
