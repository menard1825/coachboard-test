(() => {
  'use strict';

  if (window.location.pathname !== '/pitching') return;
  if (window.CoachBoardPitchingDashboardV3?.initialized) return;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function localDateString() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function applyTargetScopeUI() {
    const scope = document.getElementById('targetScopeInput')?.value || 'day';
    const isGame = scope === 'game';
    document.getElementById('targetDateField')?.classList.toggle('d-none', isGame);
    document.getElementById('targetGameField')?.classList.toggle('d-none', !isGame);
    const help = document.getElementById('targetScopeHelp');
    if (help) {
      help.textContent = isGame
        ? 'Applies only to the selected scheduled game.'
        : 'Applies across all games on the selected date.';
    }
  }

  function openTargetModal(button) {
    const gameId = button?.dataset.gameId || '';
    const player = document.getElementById('targetPlayerInput');
    const pitches = document.getElementById('targetPitchesInput');
    const reason = document.getElementById('targetReasonInput');
    const date = document.getElementById('targetDateInput');
    const game = document.getElementById('targetGameInput');
    const scope = document.getElementById('targetScopeInput');
    if (player) player.value = button?.dataset.playerId || '';
    if (pitches) pitches.value = button?.dataset.targetPitches || '';
    if (reason) reason.value = button?.dataset.targetReason || '';
    if (date) date.value = button?.dataset.targetDate || localDateString();
    if (game) game.value = gameId;
    if (scope) scope.value = gameId ? 'game' : 'day';
    applyTargetScopeUI();
    const modal = document.getElementById('coachTargetModal');
    if (modal && typeof bootstrap !== 'undefined') bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function bindTargetButtons(root = document) {
    root.querySelectorAll('.open-target-modal').forEach(button => {
      if (button.dataset.cbPitchTargetBound === '1') return;
      button.dataset.cbPitchTargetBound = '1';
      button.addEventListener('click', () => openTargetModal(button));
    });
  }

  function applyOutingTypeUI(prefix = '') {
    const isEdit = prefix === 'edit_';
    const select = document.getElementById(`${prefix}outing_type`);
    if (!select) return;
    const isGame = select.value === 'Game';
    document.querySelectorAll(isEdit ? '.edit-game-only' : '.game-only-field')
      .forEach(el => el.classList.toggle('d-none', !isGame));

    const inningsWhole = document.getElementById(`${prefix}innings_whole`);
    if (inningsWhole) inningsWhole.required = isGame;

    const contextLabel = document.getElementById(isEdit ? 'editContextLabel' : 'contextLabel');
    const contextInput = document.getElementById(`${prefix}opponent`);
    if (contextLabel) contextLabel.textContent = isGame ? 'Opponent' : 'Context / Notes (optional)';
    if (contextInput) {
      contextInput.required = isGame;
      contextInput.placeholder = isGame
        ? 'Opponent name'
        : (select.value === 'Practice' ? 'Team bullpen' : 'Pitching lesson');
    }
  }

  function toast(message, kind = 'success') {
    let holder = document.getElementById('cb-pitching-toast-holder');
    if (!holder) {
      holder = document.createElement('div');
      holder.id = 'cb-pitching-toast-holder';
      holder.className = 'toast-container position-fixed top-0 end-0 p-3';
      holder.style.zIndex = '2000';
      document.body.appendChild(holder);
    }
    const el = document.createElement('div');
    el.className = `toast align-items-center text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    holder.appendChild(el);
    if (typeof bootstrap !== 'undefined') {
      const instance = bootstrap.Toast.getOrCreateInstance(el, {delay: 2600});
      el.addEventListener('hidden.bs.toast', () => el.remove(), {once: true});
      instance.show();
    } else {
      window.setTimeout(() => el.remove(), 2600);
    }
  }

  async function refreshTargetUi(playerId) {
    const response = await fetch('/pitching', {
      cache: 'no-store',
      headers: {'X-CoachBoard-Refresh': 'pitching-target'},
    });
    if (!response.ok) return;
    const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');

    const currentTargets = document.getElementById('pitchTargetsCard');
    const freshTargets = parsed.getElementById('pitchTargetsCard');
    if (currentTargets && freshTargets) {
      const imported = document.importNode(freshTargets, true);
      currentTargets.replaceWith(imported);
      bindTargetButtons(imported);
    }

    const selector = `.cb-pitch-target[data-player-id="${CSS.escape(String(playerId))}"]`;
    const currentSlot = document.querySelector(selector);
    const freshSlot = parsed.querySelector(selector);
    if (currentSlot && freshSlot) {
      const imported = document.importNode(freshSlot, true);
      currentSlot.replaceWith(imported);
      bindTargetButtons(imported);
    }
  }

  function bindTargetSave() {
    const button = document.getElementById('saveTargetBtn');
    if (!button || button.dataset.cbPitchTargetSaveBound === '1') return;
    button.dataset.cbPitchTargetSaveBound = '1';
    button.addEventListener('click', async () => {
      const playerInput = document.getElementById('targetPlayerInput');
      const scopeInput = document.getElementById('targetScopeInput');
      const gameSelect = document.getElementById('targetGameInput');
      const dateInput = document.getElementById('targetDateInput');
      const pitchesInput = document.getElementById('targetPitchesInput');
      const reasonInput = document.getElementById('targetReasonInput');
      const playerId = playerInput?.value || '';
      const scope = scopeInput?.value || 'day';
      const gameId = scope === 'game' ? (gameSelect?.value || '') : '';

      if (!playerId) { playerInput?.focus(); return; }
      if (scope === 'game' && !gameId) { gameSelect?.focus(); return; }

      const selectedGame = gameSelect?.selectedOptions?.[0];
      const targetDate = scope === 'game' ? selectedGame?.dataset.date : dateInput?.value;
      if (!targetDate) { dateInput?.focus(); return; }

      const raw = pitchesInput?.value.trim() || '';
      button.disabled = true;
      const oldText = button.textContent;
      button.textContent = 'Saving…';
      try {
        const response = await fetch('/save_player_target', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            player_id: playerId,
            target_pitches: raw === '' ? null : Number(raw),
            local_date: targetDate,
            game_id: gameId || null,
            reason: reasonInput?.value.trim() || null,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to save target.');
        const modal = document.getElementById('coachTargetModal');
        if (modal && typeof bootstrap !== 'undefined') bootstrap.Modal.getOrCreateInstance(modal).hide();
        await refreshTargetUi(playerId);
        toast(raw === '' ? 'Pitch target cleared.' : 'Pitch target saved.');
      } catch (error) {
        toast(error.message || 'Unable to save target.', 'danger');
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    });
  }

  function enhanceHistory() {
    const list = document.getElementById('pitchHistoryList');
    const player = document.getElementById('cbPitchHistoryPlayer');
    const range = document.getElementById('cbPitchHistoryRange');
    const count = document.getElementById('cbPitchHistoryCount');
    const empty = document.getElementById('cbPitchHistoryEmpty');
    if (!list || !player || !range || !count || !empty) return;
    const items = [...list.querySelectorAll('[data-pitch-history-player]')];

    const apply = () => {
      const selectedPlayer = player.value || '';
      const selectedRange = range.value || '7';
      const today = new Date();
      today.setHours(12, 0, 0, 0);
      let visible = 0;
      items.forEach(item => {
        const playerOk = !selectedPlayer || item.dataset.pitchHistoryPlayer === selectedPlayer;
        let dateOk = true;
        if (selectedRange !== 'all' && item.dataset.pitchHistoryDate) {
          const date = new Date(`${item.dataset.pitchHistoryDate}T12:00:00`);
          const diff = Math.floor((today - date) / 86400000);
          dateOk = diff >= 0 && diff < Number(selectedRange);
        }
        const show = playerOk && dateOk;
        item.classList.toggle('d-none', !show);
        if (show) visible += 1;
      });
      count.textContent = `Showing ${visible} of ${items.length}`;
      empty.classList.toggle('d-none', visible !== 0);
    };

    player.addEventListener('change', apply);
    range.addEventListener('change', apply);
    apply();
  }

  function bindEditOutingModal() {
    const modal = document.getElementById('editPitchingOutingModal');
    if (!modal || modal.dataset.cbPitchEditBound === '1') return;
    modal.dataset.cbPitchEditBound = '1';
    modal.addEventListener('show.bs.modal', event => {
      const button = event.relatedTarget;
      if (!button) return;
      const form = document.getElementById('editPitchingOutingForm');
      if (form) form.action = `/edit_pitching/${button.dataset.outingId}`;
      const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value ?? ''; };
      set('edit_pitch_date', button.dataset.date);
      set('edit_pitcher', button.dataset.playerId);
      set('edit_opponent', button.dataset.opponent || '');
      set('edit_pitches', button.dataset.pitches || '');
      set('edit_outing_type', button.dataset.outingType || 'Game');
      set('edit_pitcher_type', button.dataset.pitcherType || 'Starter');

      const innings = String(button.dataset.innings || '');
      if (innings) {
        const [whole, outs = '0'] = innings.split('.');
        set('edit_innings_whole', whole);
        set('edit_innings_outs', ['0', '1', '2'].includes(outs) ? outs : '0');
      } else {
        set('edit_innings_whole', '');
        set('edit_innings_outs', '0');
      }
      applyOutingTypeUI('edit_');
    });
  }

  function loadDugoutMobileView() {
    if (document.getElementById('cb-pitching-dugout-mobile-script')) return;
    const script = document.createElement('script');
    script.id = 'cb-pitching-dugout-mobile-script';
    script.src = '/static/js/pitching_dugout_mobile.js?v=20260821-1';
    script.async = false;
    document.head.appendChild(script);
  }

  function init() {
    const pitchDate = document.getElementById('pitch_date');
    if (pitchDate && !pitchDate.value) pitchDate.value = localDateString();

    bindTargetButtons();
    bindTargetSave();
    enhanceHistory();
    bindEditOutingModal();
    document.getElementById('targetScopeInput')?.addEventListener('change', applyTargetScopeUI);
    document.getElementById('outing_type')?.addEventListener('change', () => applyOutingTypeUI());
    document.getElementById('edit_outing_type')?.addEventListener('change', () => applyOutingTypeUI('edit_'));
    applyTargetScopeUI();
    applyOutingTypeUI();
    loadDugoutMobileView();

    window.openTargetModal = openTargetModal;
    window.CoachBoardPitchingDashboardV3 = {
      initialized: true,
      refreshTargetUi,
      openTargetModal,
    };
    document.dispatchEvent(new CustomEvent('coachboard:pitching-dashboard-ready'));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
