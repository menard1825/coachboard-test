(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  let latestState = null;
  let busy = false;

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

    Object.entries(state.actual_rotation || {})
      .sort((a,b) => Number(a[0]) - Number(b[0]))
      .forEach(([, alignment]) => addPitcher(order, alignment?.P));

    addPitcher(order, state.current_alignment?.P);
    return order;
  }

  function splitInnings(value) {
    if (value === null || value === undefined || value === '') return ['', '0'];
    const [whole, outs = '0'] = String(value).split('.');
    return [whole, ['0','1','2'].includes(outs) ? outs : '0'];
  }

  function renderFinalForm(state) {
    const container = document.getElementById('finalCountsFormContainer');
    if (!container) return;

    const order = pitcherOrder(state);
    const logByPlayer = new Map((state.game_pitching_log || []).map(o => [Number(o.player_id), o]));

    if (!order.length) {
      container.innerHTML = '<div class="text-muted text-center py-3">No pitchers were found in the live defensive history. You can still finalize the game.</div>';
      return;
    }

    container.innerHTML = `
      <div class="alert alert-light border small mb-3">
        Final GameChanger check-in. Blank values stay <strong>unknown</strong> — CoachBoard will never turn them into zero.
      </div>
      ${order.map((name, index) => {
        const player = (state.roster || []).find(p => p.name === name);
        if (!player) return '';
        const existing = logByPlayer.get(Number(player.id)) || {};
        const [whole, outs] = splitInnings(existing.innings);
        const role = index === 0 ? 'Starter' : 'Reliever';
        return `
          <div class="border rounded-3 p-3 mb-3 final-pitcher-card" data-player-id="${player.id}">
            <div class="d-flex justify-content-between align-items-center mb-2 gap-2">
              <strong>${esc(name)}</strong>
              <span class="badge text-bg-light border">${role}</span>
            </div>
            <div class="row g-2">
              <div class="col-12 col-sm-5">
                <label class="form-label small fw-semibold">Pitches</label>
                <input type="number" min="0" step="1" inputmode="numeric" class="form-control final-complete-pitches" value="${existing.pitches ?? ''}" placeholder="GameChanger count">
              </div>
              <div class="col-7 col-sm-4">
                <label class="form-label small fw-semibold">Full Innings</label>
                <input type="number" min="0" step="1" inputmode="numeric" class="form-control final-complete-innings" value="${esc(whole)}" placeholder="2">
              </div>
              <div class="col-5 col-sm-3">
                <label class="form-label small fw-semibold">Extra Outs</label>
                <select class="form-select final-complete-outs">
                  <option value="0" ${outs==='0'?'selected':''}>0</option>
                  <option value="1" ${outs==='1'?'selected':''}>1</option>
                  <option value="2" ${outs==='2'?'selected':''}>2</option>
                </select>
              </div>
            </div>
          </div>`;
      }).join('')}
      <div class="small text-muted">Game innings are stored by outs. Example: 2 full innings + 1 out = 2.1 IP.</div>`;
  }

  async function openEndGame() {
    if (busy) return;
    busy = true;
    try {
      const state = await loadState();
      renderFinalForm(state);
      const modalEl = document.getElementById('liveFinalCountsModal');
      if (!modalEl) throw new Error('Final pitching dialog is unavailable.');
      const title = modalEl.querySelector('.modal-title');
      if (title) title.textContent = 'Finalize Game';
      const confirm = modalEl.querySelector('#confirmFinalCountsBtn');
      if (confirm) confirm.textContent = 'Finalize Game';
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (err) {
      alert(err.message || 'Unable to prepare final pitching entry.');
    } finally {
      busy = false;
    }
  }

  async function saveAndEnd() {
    if (busy) return;
    busy = true;
    const button = document.getElementById('confirmFinalCountsBtn');
    if (button) { button.disabled = true; button.textContent = 'Finalizing…'; }

    try {
      const counts = [...document.querySelectorAll('.final-pitcher-card')].map((card, index) => {
        const pitchesInput = card.querySelector('.final-complete-pitches');
        const inningsInput = card.querySelector('.final-complete-innings');
        const outsInput = card.querySelector('.final-complete-outs');
        return {
          player_id: Number(card.dataset.playerId),
          pitches: pitchesInput?.value.trim() === '' ? null : Number(pitchesInput.value),
          innings_whole: inningsInput?.value.trim() === '' ? null : Number(inningsInput.value),
          innings_outs: Number(outsInput?.value || 0),
          pitcher_type: index === 0 ? 'Starter' : 'Reliever',
        };
      });

      const response = await fetch(`/api/live-game/${gameId}/end-with-pitching`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({counts}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to finalize game.');

      bootstrap.Modal.getOrCreateInstance(document.getElementById('liveFinalCountsModal')).hide();
      if (data.warnings?.length) {
        alert(`Game saved. Please verify later:\n\n${data.warnings.join('\n')}`);
      }
      window.location.assign(`/game-day/${gameId}/report`);
    } catch (err) {
      alert(err.message || 'Unable to save final pitching numbers.');
      if (button) { button.disabled = false; button.textContent = 'Finalize Game'; }
    } finally {
      busy = false;
    }
  }

  document.addEventListener('click', event => {
    const endButton = event.target.closest('#liveEndGameBtn');
    if (endButton) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      openEndGame();
      return;
    }

    const confirmButton = event.target.closest('#confirmFinalCountsBtn');
    if (confirmButton) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      saveAndEnd();
    }
  }, true);

  // Game Day uses ?finalize=1 to recover an older/unfinished game that has live
  // history but no durable End Game marker. Open the same final check-in directly.
  if (new URLSearchParams(window.location.search).get('finalize') === '1') {
    const launch = () => window.setTimeout(openEndGame, 100);
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', launch, {once:true})
      : launch();
  }
})();
