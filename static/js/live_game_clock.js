(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let clock = null;
  let syncedAtMs = 0;
  let polling = false;
  let socket = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function injectStyles() {
    if (document.getElementById('cb-game-clock-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-game-clock-style';
    style.textContent = `
      .cb-game-clock-card{border:1px solid #dfe4ea;border-radius:14px;background:#fff;padding:12px 14px;margin:0 0 14px;box-shadow:0 4px 14px rgba(15,23,42,.05)}
      .cb-game-clock-main{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
      .cb-game-clock-values{display:flex;align-items:stretch;gap:9px;flex-wrap:wrap;flex:1}
      .cb-game-clock-value{min-width:145px;border:1px solid #e6e9ee;border-radius:11px;padding:8px 10px;background:#f8fafc}
      .cb-game-clock-label{font-size:.62rem;text-transform:uppercase;letter-spacing:.07em;color:#667085;font-weight:800}
      .cb-game-clock-time{font-size:1.25rem;line-height:1.1;font-weight:850;color:#172033;font-variant-numeric:tabular-nums;margin-top:2px}
      .cb-game-clock-value.warning{background:#fff8eb;border-color:#efd8ac}.cb-game-clock-value.warning .cb-game-clock-time{color:#8b5c00}
      .cb-game-clock-value.danger{background:#fff0f0;border-color:#f4b8b8}.cb-game-clock-value.danger .cb-game-clock-time{color:#b42318}
      .cb-game-clock-actions{display:flex;gap:7px;flex-wrap:wrap}
      .cb-game-clock-note{font-size:.68rem;color:#667085;margin-top:8px}
      .cb-pregame-clock{border:1px solid #dfe4ea;border-radius:12px;background:#fff;padding:10px 12px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
      .cb-pregame-clock strong{font-size:.8rem}.cb-pregame-clock span{font-size:.7rem;color:#667085}
      .cb-clock-preset-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:12px}
      .cb-clock-preset-grid .btn{min-height:42px}
      .cb-clock-end-choice{border:1px solid #e1e6ec;border-radius:12px;padding:12px;margin-bottom:10px;text-align:left;width:100%;background:#fff}
      .cb-clock-end-choice:hover{background:#f8fafc}
      @media(max-width:575.98px){
        .cb-game-clock-card{padding:10px}.cb-game-clock-values{display:grid;grid-template-columns:1fr 1fr;width:100%;gap:7px}.cb-game-clock-value{min-width:0}.cb-game-clock-time{font-size:1.05rem}.cb-game-clock-actions{width:100%}.cb-game-clock-actions .btn{flex:1}.cb-clock-preset-grid{grid-template-columns:repeat(2,1fr)}
      }
    `;
    document.head.appendChild(style);
  }

  function formatDuration(totalSeconds, allowNegative = false) {
    let seconds = Number(totalSeconds);
    if (!Number.isFinite(seconds)) return '—';
    const negative = seconds < 0;
    seconds = Math.abs(Math.floor(seconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    const text = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    return negative && allowNegative ? `+${text}` : text;
  }

  function formatTimeLimit(totalMinutes) {
    const minutes = Number(totalMinutes);
    if (!Number.isFinite(minutes) || minutes <= 0) return 'No limit';
    const whole = Math.floor(minutes);
    const hours = Math.floor(whole / 60);
    const remainder = whole % 60;
    if (!hours) return `${whole} min`;
    return `${hours}:${String(remainder).padStart(2, '0')}`;
  }

  function liveElapsedSeconds() {
    if (!clock || clock.elapsed_seconds === null || clock.elapsed_seconds === undefined) return null;
    let elapsed = Number(clock.elapsed_seconds) || 0;
    if (clock.is_live && clock.started_at_utc && !clock.ended_at_utc && syncedAtMs) {
      elapsed += Math.max(0, Math.floor((Date.now() - syncedAtMs) / 1000));
    }
    return elapsed;
  }

  function remainingSeconds() {
    const elapsed = liveElapsedSeconds();
    const limit = Number(clock?.time_limit_minutes || 0);
    if (elapsed === null || !limit) return null;
    return limit * 60 - elapsed;
  }

  function clockStatusClass(remaining) {
    if (remaining === null) return '';
    if (remaining <= 0) return 'danger';
    if (remaining <= 10 * 60) return 'warning';
    return '';
  }

  async function fetchClock() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`, {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to load game clock.');
      clock = data.clock || null;
      syncedAtMs = Date.now();
      render();
    } catch (err) {
      console.warn('CoachBoard game clock:', err);
    } finally {
      polling = false;
    }
  }

  async function postClock(payload) {
    const response = await fetch(`/api/live-game/${gameId}/clock`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to update game clock.');
    clock = data.clock || clock;
    syncedAtMs = Date.now();
    render();
    return data;
  }

  function syncPresetButtons(modal) {
    modal?.querySelectorAll('.cb-clock-preset').forEach(btn => {
      const selected = Number(btn.dataset.minutes || 0) === Number(clock?.time_limit_minutes || 0);
      btn.classList.toggle('btn-primary', selected);
      btn.classList.toggle('btn-outline-secondary', !selected);
    });
  }

  function ensureConfigModal() {
    let modal = document.getElementById('cbGameClockConfigModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'cbGameClockConfigModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div><h5 class="modal-title mb-0">Game Clock</h5><div class="small text-muted">Set the tournament time limit. The clock itself starts with Live Game.</div></div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="cb-clock-preset-grid">
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="75">1:15</button>
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="90">1:30</button>
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="100">1:40</button>
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="105">1:45</button>
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="120">2:00</button>
              <button type="button" class="btn btn-outline-secondary cb-clock-preset" data-minutes="0">No Limit</button>
            </div>
            <label for="cbClockCustomMinutes" class="form-label fw-semibold">Custom time limit</label>
            <div class="input-group mb-2"><input type="number" min="15" max="300" step="1" inputmode="numeric" id="cbClockCustomMinutes" class="form-control" placeholder="Minutes"><span class="input-group-text">minutes</span></div>
            <div class="form-text">CoachBoard warns when time is getting low, but it never ends a game automatically because tournament rules differ.</div>
            <div id="cbClockRestartWrap" class="mt-3 d-none"><hr><button type="button" class="btn btn-sm btn-outline-danger" id="cbClockRestartBtn"><i class="bi bi-arrow-clockwise me-1"></i>Restart clock from now</button><div class="form-text">Use this only if Live Game was started before the actual game clock began.</div></div>
          </div>
          <div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Done</button></div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.addEventListener('click', async event => {
      const preset = event.target.closest('.cb-clock-preset');
      if (preset) {
        try {
          const minutes = Number(preset.dataset.minutes || 0);
          await postClock({time_limit_minutes: minutes || null});
          syncPresetButtons(modal);
          const custom = document.getElementById('cbClockCustomMinutes');
          if (custom) custom.value = minutes || '';
        } catch (err) { window.alert(err.message); }
      }
    });

    const custom = modal.querySelector('#cbClockCustomMinutes');
    custom?.addEventListener('change', async () => {
      if (custom.value.trim() === '') return;
      try {
        await postClock({time_limit_minutes: Number(custom.value)});
        syncPresetButtons(modal);
      } catch (err) { window.alert(err.message); }
    });

    modal.querySelector('#cbClockRestartBtn')?.addEventListener('click', async () => {
      if (!window.confirm('Restart the CoachBoard game clock from 00:00:00 now?')) return;
      try {
        await postClock({action: 'restart'});
        bootstrap.Modal.getOrCreateInstance(modal).hide();
      } catch (err) { window.alert(err.message); }
    });

    return modal;
  }

  function openConfig() {
    const modal = ensureConfigModal();
    const custom = modal.querySelector('#cbClockCustomMinutes');
    if (custom) custom.value = clock?.time_limit_minutes || '';
    modal.querySelector('#cbClockRestartWrap')?.classList.toggle('d-none', !clock?.is_live);
    syncPresetButtons(modal);
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function ensureTimeLimitEndModal() {
    let modal = document.getElementById('cbTimeLimitEndModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'cbTimeLimitEndModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div><h5 class="modal-title mb-0">End Game — Time Limit</h5><div class="small text-muted">Tell CoachBoard which innings were actually played.</div></div>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body" id="cbTimeLimitChoices"></div>
          <div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  async function endForTimeLimit(currentInningPlayed, button) {
    if (button) button.disabled = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/end-with-pitching`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          defer_pitching: true,
          end_reason: 'time_limit',
          current_inning_played: Boolean(currentInningPlayed),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to end the game.');
      window.location.assign(`/game-day/${gameId}/report`);
    } catch (err) {
      window.alert(err.message || 'Unable to end the game.');
      if (button) button.disabled = false;
    }
  }

  function openTimeLimitEnd() {
    const modal = ensureTimeLimitEndModal();
    const inning = Number.parseInt(String(clock?.current_inning || '1'), 10) || 1;
    const previous = Math.max(1, inning - 1);
    const choices = modal.querySelector('#cbTimeLimitChoices');
    choices.innerHTML = `
      <p class="mb-3">CoachBoard has a <strong>${inning}-inning live state</strong> right now. Did Inning ${inning} actually begin?</p>
      <button type="button" class="cb-clock-end-choice" data-played="yes"><strong class="d-block"><i class="bi bi-check-circle text-success me-1"></i>Yes — Inning ${inning} was played</strong><span class="small text-muted">Count Inning ${inning} in actual defense and bench usage.</span></button>
      ${inning > 1 ? `<button type="button" class="cb-clock-end-choice" data-played="no"><strong class="d-block"><i class="bi bi-skip-backward text-primary me-1"></i>No — time expired before Inning ${inning} started</strong><span class="small text-muted">Last played inning was ${previous}. Pregame innings ${inning} and later will not count in actual usage.</span></button>` : ''}
      <div class="alert alert-light border small mb-0 mt-2"><strong>Your 6-inning plan is not deleted.</strong> CoachBoard keeps it as the pregame plan; only innings actually played count in the game report and season usage.</div>`;
    choices.querySelectorAll('[data-played]').forEach(button => {
      button.addEventListener('click', () => endForTimeLimit(button.dataset.played === 'yes', button), {once: true});
    });
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function ensureLiveCard() {
    const overlay = document.getElementById('live-game-overlay');
    if (!overlay || !clock?.is_live) return null;
    let card = document.getElementById('cbLiveGameClock');
    if (!card) {
      card = document.createElement('div');
      card.id = 'cbLiveGameClock';
      card.className = 'cb-game-clock-card';
      const inningRow = overlay.querySelector('.row.text-center.mb-3');
      if (inningRow) inningRow.insertAdjacentElement('afterend', card);
      else overlay.prepend(card);
    }
    return card;
  }

  function ensurePregameCard() {
    const pregame = document.getElementById('pregame-checklist-container');
    const start = document.getElementById('startLiveGameBtnAction');
    if (!pregame || !start || clock?.is_live) return null;
    let card = document.getElementById('cbPregameClock');
    if (!card) {
      card = document.createElement('div');
      card.id = 'cbPregameClock';
      card.className = 'cb-pregame-clock';
      start.closest('.d-grid')?.insertAdjacentElement('beforebegin', card);
    }
    return card;
  }

  function renderLive() {
    const card = ensureLiveCard();
    if (!card) {
      document.getElementById('cbLiveGameClock')?.remove();
      return;
    }

    const elapsed = liveElapsedSeconds();
    const remaining = remainingSeconds();
    const limit = Number(clock?.time_limit_minutes || 0);
    const statusClass = clockStatusClass(remaining);
    let remainingLabel = 'No time limit';
    let remainingValue = '—';
    if (limit) {
      remainingLabel = remaining !== null && remaining <= 0 ? 'Past Time Limit' : 'Time Remaining';
      remainingValue = remaining !== null && remaining < 0 ? formatDuration(remaining, true) : formatDuration(remaining);
    }

    card.innerHTML = `
      <div class="cb-game-clock-main">
        <div class="cb-game-clock-values">
          <div class="cb-game-clock-value"><div class="cb-game-clock-label">Game Clock · Elapsed</div><div class="cb-game-clock-time">${formatDuration(elapsed)}</div></div>
          <div class="cb-game-clock-value ${statusClass}"><div class="cb-game-clock-label">${esc(remainingLabel)}</div><div class="cb-game-clock-time">${esc(remainingValue)}</div></div>
        </div>
        <div class="cb-game-clock-actions"><button type="button" class="btn btn-sm btn-outline-secondary cb-clock-config"><i class="bi bi-clock-history me-1"></i>Set Clock</button><button type="button" class="btn btn-sm btn-outline-danger cb-clock-end-time"><i class="bi bi-stop-circle me-1"></i>End — Time Limit</button></div>
      </div>
      <div class="cb-game-clock-note">${limit ? `${formatTimeLimit(limit)} time limit. ` : ''}The clock starts with Live Game and stays synced to the server. CoachBoard never ends the game automatically.</div>`;
    card.querySelector('.cb-clock-config')?.addEventListener('click', openConfig);
    card.querySelector('.cb-clock-end-time')?.addEventListener('click', openTimeLimitEnd);
  }

  function renderPregame() {
    const card = ensurePregameCard();
    if (!card) {
      document.getElementById('cbPregameClock')?.remove();
      return;
    }
    const limit = Number(clock?.time_limit_minutes || 0);
    card.innerHTML = `<div><strong><i class="bi bi-clock me-1"></i>Game Clock</strong><span class="d-block">${limit ? `Time limit: ${formatTimeLimit(limit)}` : 'No time limit set yet'} · starts when you tap Start Live Game</span></div><button type="button" class="btn btn-sm btn-outline-primary cb-clock-config">${limit ? 'Change' : 'Set Time Limit'}</button>`;
    card.querySelector('.cb-clock-config')?.addEventListener('click', openConfig);
  }

  function render() {
    injectStyles();
    renderPregame();
    renderLive();
  }

  function connectClockSocket() {
    if (typeof io !== 'function' || socket) return;
    socket = io();
    socket.on('connect', () => {
      socket.emit('join_game_room', {game_id: gameId});
    });
    socket.on('game_clock_update', payload => {
      if (Number(payload?.game_id) !== gameId) return;
      clock = payload;
      syncedAtMs = Date.now();
      render();
    });
  }

  injectStyles();
  ensureConfigModal();
  ensureTimeLimitEndModal();
  connectClockSocket();
  fetchClock();
  window.setInterval(render, 1000);
  window.setInterval(fetchClock, 15000);
  document.addEventListener('DOMContentLoaded', () => {
    render();
    fetchClock();
  }, {once: true});
})();
