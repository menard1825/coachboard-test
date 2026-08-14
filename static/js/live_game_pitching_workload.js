(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let state = null;
  let loading = false;
  let applying = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function numberOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function summaryForPlayer(player) {
    return state?.pitch_count_summary?.[player?.name] || {};
  }

  function playerById(playerId) {
    return (state?.roster || []).find(player => Number(player.id) === Number(playerId));
  }

  function planFor(playerId) {
    return (state?.pitching_plans || []).find(plan => Number(plan.player_id) === Number(playerId));
  }

  function workloadNumbers(summary) {
    const officialDay = numberOrNull(summary.official_daily_pitches ?? summary.daily);
    const workloadDay = numberOrNull(summary.workload_daily_pitches);
    const workload7 = numberOrNull(summary.workload_7_day_pitches);
    const nonGameDay = officialDay !== null && workloadDay !== null
      ? Math.max(0, workloadDay - officialDay)
      : null;

    return {officialDay, workloadDay, workload7, nonGameDay};
  }

  function workloadText(summary, compact = false) {
    const values = workloadNumbers(summary);
    const official = values.officialDay === null ? 'Official: unknown' : `Official: ${values.officialDay}`;
    const day = values.workloadDay === null ? 'Game-day workload: unknown' : `Game-day workload: ${values.workloadDay}`;
    const seven = values.workload7 === null ? '7-day workload: unknown' : `7-day workload: ${values.workload7}`;
    const extra = values.nonGameDay > 0 ? ` • ${values.nonGameDay} non-game throws` : '';

    if (compact) return `${official} • ${day} • ${seven}${extra}`;
    return `${official} game pitches • ${day} pitches • ${seven} pitches${extra}`;
  }

  function decisionDetail(player) {
    const summary = summaryForPlayer(player);
    const plan = planFor(player.id);
    const pieces = [
      summary.status || 'Eligibility unknown',
      workloadText(summary, true),
      summary.coach_target != null ? `Coach target: ${summary.coach_target}` : null,
      plan?.role || null,
    ].filter(Boolean);
    return pieces.join(' • ');
  }

  function installStyles() {
    if (document.getElementById('pitching-workload-game-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitching-workload-game-styles';
    style.textContent = `
      .pitch-workload-line{font-size:.72rem;color:#667085;margin-top:3px;line-height:1.35}
      .pitch-workload-line strong{color:#344054}
      .pitch-workload-extra{color:#8a5a13;font-weight:750}
      .pitch-workload-add{display:block;font-size:.69rem;color:#667085;margin-top:3px;line-height:1.3}
      @media(max-width:575.98px){.pitch-workload-line,.pitch-workload-add{font-size:.66rem}}
    `;
    document.head.appendChild(style);
  }

  function patchCurrentPitcher() {
    const name = document.getElementById('live-current-pitcher')?.textContent?.trim();
    const stats = document.getElementById('live-pitcher-stats');
    if (!name || !stats) return;
    const player = (state?.roster || []).find(item => item.name === name);
    if (!player) return;
    stats.textContent = decisionDetail(player);
  }

  function patchChangePitcherChoices() {
    document.querySelectorAll('.pitcher-choice-v2[data-player-id]').forEach(button => {
      const player = playerById(button.dataset.playerId);
      if (!player) return;
      const detail = button.querySelector('.small.text-muted.mt-1');
      if (detail) detail.textContent = decisionDetail(player);
    });
  }

  function patchPitchingBoard() {
    document.querySelectorAll('#pitching-board-v2 .edit-plan-v2[data-player-id]').forEach(editButton => {
      const player = playerById(editButton.dataset.playerId);
      const card = editButton.closest('.border.rounded');
      if (!player || !card) return;
      const detail = card.querySelector('.small.text-muted');
      if (detail) detail.textContent = decisionDetail(player);
    });
  }

  function patchAddPitcherChoices() {
    document.querySelectorAll('.add-plan-player-v2[data-player-id]').forEach(button => {
      const player = playerById(button.dataset.playerId);
      if (!player) return;
      let detail = button.querySelector('.pitch-workload-add');
      if (!detail) {
        const playerName = button.textContent.trim();
        button.innerHTML = `<strong>${esc(playerName)}</strong><span class="pitch-workload-add"></span>`;
        detail = button.querySelector('.pitch-workload-add');
      }
      detail.textContent = decisionDetail(player);
    });
  }

  function patchVisiblePitcherViews() {
    if (!state || applying) return;
    applying = true;
    try {
      patchCurrentPitcher();
      patchChangePitcherChoices();
      patchPitchingBoard();
      patchAddPitcherChoices();
    } finally {
      applying = false;
    }
  }

  async function loadState() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
      if (!response.ok) return;
      state = await response.json();
      patchVisiblePitcherViews();
    } catch (_) {
      // The authoritative live controller will surface connection errors.
    } finally {
      loading = false;
    }
  }

  installStyles();

  const observer = new MutationObserver(() => {
    window.requestAnimationFrame(patchVisiblePitcherViews);
  });

  const start = () => {
    observer.observe(document.body, {childList:true, subtree:true});
    loadState();
    window.setInterval(loadState, 5000);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once:true});
  } else {
    start();
  }
})();
