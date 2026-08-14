(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let seenLive = false;
  let reloading = false;
  let checking = false;
  let latestState = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function currentWholeInning(state) {
    const parsed = Number(state?.current_inning || state?.game?.live_current_inning || 1);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1;
  }

  function playerPosition(alignment, name) {
    for (const [position, playerName] of Object.entries(alignment || {})) {
      if (playerName === name) return position;
    }
    return null;
  }

  function reachedSnapshots(state) {
    const current = currentWholeInning(state);
    const actual = state?.actual_rotation || {};
    const snapshots = [];

    for (let inning = 1; inning <= current; inning += 1) {
      let alignment = actual[String(inning)] || {};
      if (inning === current && state?.current_alignment) {
        alignment = state.current_alignment;
      }
      // Ignore a corrupted/unknown empty inning rather than calling every player benched.
      if (!Object.values(alignment || {}).some(Boolean)) continue;
      snapshots.push({ inning, alignment });
    }
    return snapshots;
  }

  function buildBenchStats(state) {
    if (!state) return new Map();
    const current = currentWholeInning(state);
    const currentAlignment = state.current_alignment || {};
    const snapshots = reachedSnapshots(state);
    const completed = snapshots.filter(item => item.inning < current);
    const stats = new Map();

    (state.roster || []).forEach(player => {
      const name = player.name;
      const positionNow = playerPosition(currentAlignment, name);
      const onBenchNow = !positionNow;
      const completedBenchInningsList = completed
        .filter(item => !playerPosition(item.alignment, name))
        .map(item => item.inning);
      const completedBenchInnings = completedBenchInningsList.length;

      let priorBenchStreak = 0;
      for (let i = completed.length - 1; i >= 0; i -= 1) {
        if (playerPosition(completed[i].alignment, name)) break;
        priorBenchStreak += 1;
      }

      const currentBenchStreak = onBenchNow ? priorBenchStreak + 1 : 0;
      stats.set(name, {
        name,
        positionNow: positionNow || 'BENCH',
        onBenchNow,
        completedBenchInnings,
        completedBenchInningsList,
        currentBenchStreak,
        currentInning: current,
      });
    });

    return stats;
  }

  function inningListText(innings) {
    if (!innings?.length) return '';
    return innings.join(', ');
  }

  function satHistoryText(innings) {
    if (!innings?.length) return '';
    return innings.length === 1
      ? `Sat inning ${innings[0]}`
      : `Sat innings ${inningListText(innings)}`;
  }

  function benchOptionLabel(name, stat, targetPosition) {
    if (!stat) return name;
    const history = satHistoryText(stat.completedBenchInningsList);

    if (stat.onBenchNow) {
      const pieces = [`${name} — BENCH NOW`];
      if (history) pieces.push(history);
      pieces.push(`Sitting inning ${stat.currentInning}`);
      return pieces.join(' • ');
    }

    const pieces = [name];
    // If the player is already at this row's position, the position label on the
    // left already communicates it. Only show location when choosing would move
    // the player from somewhere else on the field.
    if (stat.positionNow && stat.positionNow !== targetPosition) {
      pieces.push(`On field at ${stat.positionNow}`);
    }
    if (history) pieces.push(history);
    return pieces.join(' — ').replace(' — On field', ' — On field');
  }

  function installBenchStyles() {
    if (document.getElementById('actual-bench-context-styles')) return;
    const style = document.createElement('style');
    style.id = 'actual-bench-context-styles';
    style.textContent = `
      .actual-bench-context{margin:0 0 12px;padding:10px 11px;border:1px solid #d9e1ea;border-radius:10px;background:#f8fafc}
      .actual-bench-context-title{font-size:.65rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:#667085;margin-bottom:6px}
      .actual-bench-context-help{font-size:.66rem;color:#8a94a3;margin:-3px 0 7px}
      .actual-bench-context-list{display:flex;flex-wrap:wrap;gap:6px}
      .actual-bench-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid #d7dde5;background:#fff;border-radius:999px;padding:5px 8px;font-size:.68rem;color:#344054;white-space:nowrap}
      .actual-bench-chip strong{font-weight:800;color:#172033}.actual-bench-chip .bench-history{color:#8b5c00;font-weight:800}
      .ni-select option[data-bench-now="1"]{font-weight:700}
      @media(max-width:575.98px){.actual-bench-context{padding:9px}.actual-bench-chip{font-size:.63rem;padding:4px 7px}}
    `;
    document.head.appendChild(style);
  }

  function benchNowChipText(item) {
    const history = satHistoryText(item.completedBenchInningsList);
    return history
      ? `${history} • Sitting inning ${item.currentInning}`
      : `Sitting inning ${item.currentInning}`;
  }

  function enhanceAdjustModal(state = latestState) {
    const modal = document.getElementById('next-inning-adjust-modal');
    const body = document.getElementById('next-inning-adjust-body');
    if (!modal || !body || !state) return;

    installBenchStyles();
    const stats = buildBenchStats(state);
    const benchNow = [...stats.values()]
      .filter(item => item.onBenchNow)
      .sort((a, b) => b.currentBenchStreak - a.currentBenchStreak || b.completedBenchInnings - a.completedBenchInnings || a.name.localeCompare(b.name));

    let context = body.querySelector('.actual-bench-context');
    if (!context) {
      context = document.createElement('div');
      context.className = 'actual-bench-context';
      body.prepend(context);
    }

    context.innerHTML = `
      <div class="actual-bench-context-title">Bench Now — Actual Game</div>
      <div class="actual-bench-context-help">Actual innings only. Future planned bench time is not counted.</div>
      <div class="actual-bench-context-list">
        ${benchNow.length
          ? benchNow.map(item => `<span class="actual-bench-chip"><strong>${esc(item.name)}</strong><span class="bench-history">${esc(benchNowChipText(item))}</span></span>`).join('')
          : '<span class="actual-bench-chip">Nobody is currently on the bench.</span>'}
      </div>`;

    body.querySelectorAll('.ni-select').forEach(select => {
      const selectedValue = select.value;
      const targetPosition = select.dataset.pos || '';
      const options = [...select.options];
      options.forEach(option => {
        if (!option.value) {
          option.textContent = 'Open position';
          return;
        }
        const stat = stats.get(option.value);
        option.textContent = benchOptionLabel(option.value, stat, targetPosition);
        option.dataset.benchNow = stat?.onBenchNow ? '1' : '0';
        option.dataset.benchStreak = String(stat?.currentBenchStreak || 0);
        option.dataset.completedBench = String(stat?.completedBenchInnings || 0);
      });

      // Put players actually sitting now first, longest current bench stretch first.
      const playerOptions = options.filter(option => option.value);
      playerOptions.sort((a, b) => {
        const aBench = Number(a.dataset.benchNow || 0);
        const bBench = Number(b.dataset.benchNow || 0);
        if (aBench !== bBench) return bBench - aBench;
        const aStreak = Number(a.dataset.benchStreak || 0);
        const bStreak = Number(b.dataset.benchStreak || 0);
        if (aStreak !== bStreak) return bStreak - aStreak;
        const aTotal = Number(a.dataset.completedBench || 0);
        const bTotal = Number(b.dataset.completedBench || 0);
        if (aTotal !== bTotal) return bTotal - aTotal;
        return a.value.localeCompare(b.value);
      });

      const openOption = options.find(option => !option.value);
      select.innerHTML = '';
      if (openOption) select.appendChild(openOption);
      playerOptions.forEach(option => select.appendChild(option));
      select.value = selectedValue;
    });

    // Upgrade the small Bench chips at the bottom with actual inning history too.
    body.querySelectorAll('.ni-bench span').forEach(chip => {
      const rawName = chip.dataset.playerName || chip.textContent.trim();
      chip.dataset.playerName = rawName;
      const stat = stats.get(rawName);
      if (stat?.onBenchNow) {
        const history = satHistoryText(stat.completedBenchInningsList);
        chip.textContent = history
          ? `${rawName} • ${history} • Sitting inning ${stat.currentInning}`
          : `${rawName} • Sitting inning ${stat.currentInning}`;
        chip.title = `${rawName} is on the bench now. Completed bench innings: ${stat.completedBenchInningsList?.length ? inningListText(stat.completedBenchInningsList) : 'none'}. Current inning: ${stat.currentInning}.`;
      }
    });
  }

  async function checkState() {
    if (checking || reloading) return;
    checking = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      latestState = state;
      const isLive = Boolean(state?.game?.is_live);
      if (isLive) {
        seenLive = true;
        enhanceAdjustModal(state);
        return;
      }
      if (seenLive) {
        reloading = true;
        // Rebuild Game Management from the saved planned rotation instead of
        // leaving the legacy planner in a stale live-state DOM.
        window.location.reload();
      }
    } catch (_) {
      // The main Live Game controller owns user-facing sync errors.
    } finally {
      checking = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    installBenchStyles();
    checkState();
    setInterval(checkState, 1000);
  });

  document.addEventListener('shown.bs.modal', event => {
    if (event.target?.id === 'next-inning-adjust-modal') {
      setTimeout(() => enhanceAdjustModal(), 0);
    }
  });

  document.addEventListener('change', event => {
    if (event.target?.classList?.contains('ni-select')) {
      // Board Prep rebuilds the modal body after a selection; enrich the new DOM.
      setTimeout(() => enhanceAdjustModal(), 0);
    }
  }, true);

  document.addEventListener('click', event => {
    if (event.target.closest('#confirmFinalCountsBtn')) {
      seenLive = true;
      setTimeout(checkState, 200);
      setTimeout(checkState, 600);
    }
  }, true);
})();
