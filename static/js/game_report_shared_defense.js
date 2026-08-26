(() => {
  'use strict';

  const shell = document.querySelector('.agr-shell[data-game-id]');
  if (!shell) return;

  const gameId = Number(shell.dataset.gameId);
  if (!Number.isInteger(gameId) || gameId <= 0) return;

  const positions = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'CF', 'RCF', 'RF'];
  const midInningTypes = new Set(['Defensive Change', 'Pitcher Change', 'Set New Defense']);

  function hasAlignment(value) {
    return Boolean(value && typeof value === 'object' && Object.values(value).some(Boolean));
  }

  function activeEvents(state) {
    return [...(state.rotation_events || [])]
      .filter(event => !event.reverted)
      .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0));
  }

  function playerLabelFactory(roster) {
    const byName = new Map((roster || []).map(player => [String(player.name || '').trim(), player]));
    return (name) => {
      const clean = String(name || '').trim();
      if (!clean) return '';
      const player = byName.get(clean);
      const number = String(player?.number || '').trim();
      return number ? `#${number} ${clean}` : clean;
    };
  }

  function startingAlignment(inning, events, state) {
    const boundary = events.find(event =>
      event.event_type === 'End Inning' &&
      String(event.inning) === inning &&
      hasAlignment(event.after_alignment)
    );
    if (boundary) return boundary.after_alignment;

    const firstMidInningChange = events.find(event =>
      midInningTypes.has(event.event_type) &&
      String(event.inning) === inning &&
      hasAlignment(event.before_alignment)
    );
    if (firstMidInningChange) return firstMidInningChange.before_alignment;

    const planned = state.rotation?.innings?.[inning];
    if (hasAlignment(planned)) return planned;

    return state.actual_rotation?.[inning] || {};
  }

  function addSnapshot(participants, fielded, alignment) {
    positions.forEach(position => {
      const name = String(alignment?.[position] || '').trim();
      if (!name) return;
      fielded.add(name);
      const list = participants.get(position);
      if (!list.includes(name)) list.push(name);
    });
  }

  function ensurePositionRow(card, position) {
    let row = card.querySelector(`.agr-pos[data-pos="${position}"]`);
    if (row) return row;

    const bench = card.querySelector('[data-role="bench"]');
    row = document.createElement('div');
    row.className = 'agr-pos';
    row.dataset.pos = position;
    row.innerHTML = `<b>${position}</b><span></span>`;
    if (bench) bench.before(row);
    else card.appendChild(row);
    return row;
  }

  function renderInning(card, state, events, roster, labelPlayer) {
    const inning = String(card.dataset.inning || '');
    const participants = new Map(positions.map(position => [position, []]));
    const fielded = new Set();

    addSnapshot(participants, fielded, startingAlignment(inning, events, state));

    events
      .filter(event => midInningTypes.has(event.event_type) && String(event.inning) === inning)
      .forEach(event => addSnapshot(participants, fielded, event.after_alignment || {}));

    // The final authoritative snapshot is included as a safety net for older games
    // that may not have a complete event chain.
    addSnapshot(participants, fielded, state.actual_rotation?.[inning] || {});

    participants.forEach((names, position) => {
      if (!names.length) return;
      const row = ensurePositionRow(card, position);
      const value = row.querySelector('span');
      if (value) value.textContent = names.map(labelPlayer).join(' / ');
    });

    const bench = (roster || [])
      .map(player => String(player.name || '').trim())
      .filter(name => name && !fielded.has(name));

    const benchEl = card.querySelector('[data-role="bench"]');
    if (benchEl && card.dataset.reliable === '1') {
      benchEl.replaceChildren();
      const strong = document.createElement('strong');
      strong.textContent = 'Bench: ';
      benchEl.appendChild(strong);
      benchEl.append(document.createTextNode(bench.length ? bench.map(labelPlayer).join(', ') : 'None'));
    }

    return {
      inning,
      reliable: card.dataset.reliable === '1',
      bench,
    };
  }

  function renderBenchSummary(results, roster, labelPlayer) {
    const body = document.getElementById('agr-bench-body');
    if (!body) return;

    const totals = new Map((roster || []).map(player => [String(player.name || '').trim(), []]));
    results.forEach(result => {
      if (!result.reliable) return;
      result.bench.forEach(name => {
        if (!totals.has(name)) totals.set(name, []);
        totals.get(name).push(result.inning);
      });
    });

    const rows = [...totals.entries()]
      .filter(([name]) => name)
      .map(([name, innings]) => ({name, innings, count: innings.length}))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

    body.replaceChildren();
    rows.forEach(row => {
      const tr = document.createElement('tr');
      const playerCell = document.createElement('td');
      playerCell.className = 'ps-3 fw-semibold';
      playerCell.textContent = labelPlayer(row.name);
      const countCell = document.createElement('td');
      countCell.textContent = String(row.count);
      const inningsCell = document.createElement('td');
      inningsCell.className = 'pe-3';
      inningsCell.textContent = row.innings.length ? row.innings.join(', ') : '—';
      tr.append(playerCell, countCell, inningsCell);
      body.appendChild(tr);
    });
  }

  function locationMap(alignment, roster) {
    const locations = new Map();
    positions.forEach(position => {
      const name = String(alignment?.[position] || '').trim();
      if (name) locations.set(name, position);
    });
    (roster || []).forEach(player => {
      const name = String(player.name || '').trim();
      if (name && !locations.has(name)) locations.set(name, 'BENCH');
    });
    return locations;
  }

  function describeEvent(event, roster, labelPlayer) {
    const before = locationMap(event.before_alignment || {}, roster);
    const after = locationMap(event.after_alignment || {}, roster);
    const names = new Set([...before.keys(), ...after.keys()]);
    const moves = [...names]
      .map(name => ({
        name,
        from: before.get(name) || 'BENCH',
        to: after.get(name) || 'BENCH',
      }))
      .filter(move => move.from !== move.to)
      .sort((a, b) => {
        const aBench = a.to === 'BENCH' ? 1 : 0;
        const bBench = b.to === 'BENCH' ? 1 : 0;
        if (aBench !== bBench) return aBench - bBench;
        return positions.indexOf(a.to) - positions.indexOf(b.to) || a.name.localeCompare(b.name);
      });

    return moves.length
      ? moves.map(move => `${labelPlayer(move.name)}: ${move.from} → ${move.to}`).join(' · ')
      : event.event_type;
  }

  function renderChanges(events, roster, labelPlayer) {
    const card = document.getElementById('agr-game-changes-card');
    const list = document.getElementById('agr-game-changes');
    if (!card || !list) return;

    const changes = events.filter(event => midInningTypes.has(event.event_type));
    if (!changes.length) return;

    list.replaceChildren();
    changes.forEach(event => {
      const row = document.createElement('div');
      row.className = 'agr-change-row';

      const meta = document.createElement('div');
      meta.className = 'agr-change-meta';
      meta.textContent = `Inning ${event.inning} · ${event.event_type}`;

      const detail = document.createElement('div');
      detail.className = 'agr-change-detail';
      detail.textContent = describeEvent(event, roster, labelPlayer);

      row.append(meta, detail);
      list.appendChild(row);
    });

    card.hidden = false;
  }

  async function enhanceReport() {
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`Live history request failed (${response.status}).`);
      const state = await response.json();
      const roster = state.roster || [];
      const events = activeEvents(state);
      const labelPlayer = playerLabelFactory(roster);

      const results = [...document.querySelectorAll('.agr-inning[data-inning]')]
        .map(card => renderInning(card, state, events, roster, labelPlayer));

      renderBenchSummary(results, roster, labelPlayer);
      renderChanges(events, roster, labelPlayer);
    } catch (error) {
      // Keep the server-rendered report as a safe fallback if live history cannot
      // be loaded. The report remains usable; it simply cannot show shared reps.
      console.warn('CoachBoard shared-defense report enhancement unavailable:', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceReport, {once: true});
  } else {
    enhanceReport();
  }
})();
