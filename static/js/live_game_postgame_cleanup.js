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

  function requiredPositionCount(state) {
    return Number(state?.outfielder_count) === 4 ? 10 : 9;
  }

  function playerPosition(alignment, name) {
    for (const [position, playerName] of Object.entries(alignment || {})) {
      if (playerName === name) return position;
    }
    return null;
  }

  function alignmentPlayerCount(alignment) {
    return Object.values(alignment || {}).filter(Boolean).length;
  }

  function completedActualSnapshots(state) {
    const current = currentWholeInning(state);
    const required = requiredPositionCount(state);
    const actual = state?.actual_rotation || {};
    const snapshots = [];

    for (let inning = 1; inning < current; inning += 1) {
      const alignment = actual[String(inning)] || {};
      if (alignmentPlayerCount(alignment) !== required) continue;
      snapshots.push({ inning, alignment });
    }
    return snapshots;
  }

  function plannedGameContext(state) {
    const required = requiredPositionCount(state);
    const innings = state?.rotation?.innings || {};
    const wholeKeys = Object.keys(innings)
      .map(key => Number(key))
      .filter(value => Number.isFinite(value) && Number.isInteger(value) && value > 0)
      .sort((a, b) => a - b);

    if (!wholeKeys.length) {
      return { reliable: false, snapshots: [], inningCount: 0 };
    }

    const maxInning = Math.max(...wholeKeys);
    const snapshots = [];
    let reliable = true;

    for (let inning = 1; inning <= maxInning; inning += 1) {
      const alignment = innings[String(inning)] || {};
      if (alignmentPlayerCount(alignment) !== required) {
        reliable = false;
        continue;
      }
      snapshots.push({ inning, alignment });
    }

    return { reliable, snapshots, inningCount: maxInning };
  }

  function buildBenchStats(state) {
    if (!state) return { stats: new Map(), planReliable: false };

    const currentAlignment = state.current_alignment || {};
    const completedActual = completedActualSnapshots(state);
    const plan = plannedGameContext(state);
    const stats = new Map();

    (state.roster || []).forEach(player => {
      const name = player.name;
      const positionNow = playerPosition(currentAlignment, name);
      const onBenchNow = !positionNow;
      const actualBenchInnings = completedActual
        .filter(item => !playerPosition(item.alignment, name))
        .map(item => item.inning);
      const plannedBenchInnings = plan.snapshots
        .filter(item => !playerPosition(item.alignment, name))
        .map(item => item.inning);

      stats.set(name, {
        name,
        positionNow: positionNow || 'BENCH',
        onBenchNow,
        actualBenchInnings,
        actualBenchCount: actualBenchInnings.length,
        plannedBenchInnings,
        plannedBenchCount: plan.reliable ? plannedBenchInnings.length : null,
      });
    });

    return { stats, planReliable: plan.reliable, plannedInnings: plan.inningCount };
  }

  function countLabel(value) {
    return Number(value) === 1 ? '1 inning' : `${Number(value) || 0} innings`;
  }

  function balanceText(stat) {
    const actual = `Sat ${countLabel(stat?.actualBenchCount || 0)}`;
    const planned = stat?.plannedBenchCount === null || stat?.plannedBenchCount === undefined
      ? 'Planned —'
      : `Planned ${countLabel(stat.plannedBenchCount)}`;
    return `${actual} • ${planned}`;
  }

  function benchOptionLabel(name, stat, targetPosition) {
    if (!stat) return name;
    const context = balanceText(stat);

    if (stat.onBenchNow) {
      return `${name} — BENCH NOW • ${context}`;
    }

    if (stat.positionNow && stat.positionNow !== targetPosition) {
      return `${name} — At ${stat.positionNow} • ${context}`;
    }

    return `${name} — ${context}`;
  }

  function benchStatus(stat) {
    if (stat?.plannedBenchCount === null || stat?.plannedBenchCount === undefined) return '';
    const actual = Number(stat.actualBenchCount || 0);
    const planned = Number(stat.plannedBenchCount || 0);
    if (actual > planned) return 'over';
    if (actual === planned && planned > 0) return 'at';
    return '';
  }

  function installBenchStyles() {
    if (document.getElementById('actual-bench-context-styles')) return;
    const style = document.createElement('style');
    style.id = 'actual-bench-context-styles';
    style.textContent = `
      .actual-bench-context{margin:0 0 12px;padding:10px 11px;border:1px solid #d9e1ea;border-radius:10px;background:#f8fafc}
      .actual-bench-context-title{font-size:.65rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:#667085;margin-bottom:6px}
      .actual-bench-context-help{font-size:.66rem;color:#8a94a3;margin:-3px 0 7px}.actual-bench-context-help.warning{color:#9a6700;font-weight:700}
      .actual-bench-context-list{display:flex;flex-wrap:wrap;gap:6px}.actual-bench-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid #d7dde5;background:#fff;border-radius:999px;padding:5px 8px;font-size:.68rem;color:#344054;white-space:nowrap}
      .actual-bench-chip strong{font-weight:800;color:#172033}.actual-bench-chip .bench-history{color:#667085;font-weight:750}.actual-bench-chip.at{border-color:#e7c66b;background:#fff9e9}.actual-bench-chip.at .bench-history{color:#8b5c00}.actual-bench-chip.over{border-color:#e1a1a1;background:#fff2f2}.actual-bench-chip.over .bench-history{color:#a32929}.actual-bench-flag{font-size:.56rem;font-weight:850;letter-spacing:.04em;text-transform:uppercase}.ni-select option[data-bench-now="1"]{font-weight:700}
      @media(max-width:575.98px){.actual-bench-context{padding:9px}.actual-bench-chip{font-size:.63rem;padding:4px 7px}}
    `;
    document.head.appendChild(style);
  }

  function enhanceAdjustModal(state = latestState) {
    const modal = document.getElementById('next-inning-adjust-modal');
    const body = document.getElementById('next-inning-adjust-body');
    if (!modal || !body || !state) return;

    installBenchStyles();
    const { stats, planReliable } = buildBenchStats(state);
    const benchNow = [...stats.values()]
      .filter(item => item.onBenchNow)
      .sort((a, b) => {
        if (a.actualBenchCount !== b.actualBenchCount) return b.actualBenchCount - a.actualBenchCount;
        const aPlan = a.plannedBenchCount ?? Number.MAX_SAFE_INTEGER;
        const bPlan = b.plannedBenchCount ?? Number.MAX_SAFE_INTEGER;
        if (aPlan !== bPlan) return aPlan - bPlan;
        return a.name.localeCompare(b.name);
      });

    let context = body.querySelector('.actual-bench-context');
    if (!context) {
      context = document.createElement('div');
      context.className = 'actual-bench-context';
      body.prepend(context);
    }

    const help = planReliable
      ? 'Sat = completed defensive innings actually benched. Planned = full pregame bench total.'
      : 'Actual bench time is shown. The saved pregame rotation has incomplete innings, so Planned is unavailable.';

    context.innerHTML = `
      <div class="actual-bench-context-title">Bench Balance — Actual vs Plan</div>
      <div class="actual-bench-context-help ${planReliable ? '' : 'warning'}">${esc(help)}</div>
      <div class="actual-bench-context-list">
        ${benchNow.length
          ? benchNow.map(item => {
              const status = benchStatus(item);
              const flag = status === 'over' ? '<span class="actual-bench-flag">Over plan</span>' : status === 'at' ? '<span class="actual-bench-flag">At plan</span>' : '';
              return `<span class="actual-bench-chip ${status}"><strong>${esc(item.name)}</strong><span class="bench-history">${esc(balanceText(item))}</span>${flag}</span>`;
            }).join('')
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
        option.dataset.actualBench = String(stat?.actualBenchCount || 0);
        option.dataset.plannedBench = stat?.plannedBenchCount === null || stat?.plannedBenchCount === undefined ? '' : String(stat.plannedBenchCount);
      });

      const playerOptions = options.filter(option => option.value);
      playerOptions.sort((a, b) => {
        const aBench = Number(a.dataset.benchNow || 0);
        const bBench = Number(b.dataset.benchNow || 0);
        if (aBench !== bBench) return bBench - aBench;
        const aActual = Number(a.dataset.actualBench || 0);
        const bActual = Number(b.dataset.actualBench || 0);
        if (aActual !== bActual) return bActual - aActual;
        const aPlan = a.dataset.plannedBench === '' ? Number.MAX_SAFE_INTEGER : Number(a.dataset.plannedBench);
        const bPlan = b.dataset.plannedBench === '' ? Number.MAX_SAFE_INTEGER : Number(b.dataset.plannedBench);
        if (aPlan !== bPlan) return aPlan - bPlan;
        return a.value.localeCompare(b.value);
      });

      const openOption = options.find(option => !option.value);
      select.innerHTML = '';
      if (openOption) select.appendChild(openOption);
      playerOptions.forEach(option => select.appendChild(option));
      select.value = selectedValue;
    });

    body.querySelectorAll('.ni-bench span').forEach(chip => {
      const rawName = chip.dataset.playerName || chip.textContent.split(' • ')[0].trim();
      chip.dataset.playerName = rawName;
      const stat = stats.get(rawName);
      if (stat?.onBenchNow) {
        chip.textContent = `${rawName} • ${balanceText(stat)}`;
        chip.title = `${rawName} is currently on the bench. ${balanceText(stat)}.`;
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
        // A completed game belongs in the actual-usage flow, not back in the
        // pregame planner. This also moves secondary coaches when another coach ends it.
        window.location.assign(`/game-day/${gameId}/report`);
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
      setTimeout(() => enhanceAdjustModal(), 0);
    }
  }, true);

  document.addEventListener('click', event => {
    if (event.target.closest('#confirmFinalCountsBtn')) {
      seenLive = true;
      setTimeout(checkState, 250);
      setTimeout(checkState, 700);
    }
  }, true);
})();
