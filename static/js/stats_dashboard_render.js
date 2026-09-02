(() => {
  'use strict';

  const POSITION_ORDER = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'CF', 'RCF', 'RF', 'DH', 'EH'];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const val = (value, fallback = '—') => (value === null || value === undefined || value === '') ? fallback : value;

  function section(title, subtitle, body, extraClass = '') {
    return `<section class="sv2-card ${extraClass}"><div class="sv2-head"><h3>${esc(title)}</h3><p>${esc(subtitle)}</p></div><div class="sv2-body">${body}</div></section>`;
  }

  function allPositions(rows) {
    const found = new Set();
    rows.forEach(row => Object.keys(row.positions || {}).forEach(position => found.add(position)));
    const ordered = POSITION_ORDER.filter(position => found.has(position));
    const extras = [...found].filter(position => !POSITION_ORDER.includes(position)).sort();
    return ordered.concat(extras);
  }

  function sortedPositionEntries(row) {
    return Object.entries(row.positions || {}).sort((a, b) => {
      const countDiff = Number(b[1] || 0) - Number(a[1] || 0);
      if (countDiff) return countDiff;
      const aIndex = POSITION_ORDER.indexOf(a[0]);
      const bIndex = POSITION_ORDER.indexOf(b[0]);
      if (aIndex === -1 && bIndex === -1) return a[0].localeCompare(b[0]);
      if (aIndex === -1) return 1;
      if (bIndex === -1) return -1;
      return aIndex - bIndex;
    });
  }

  function positionPills(row) {
    const entries = sortedPositionEntries(row);
    return entries.length
      ? entries.map(([position, innings]) => `<span class="sv2-pos"><strong>${esc(position)}</strong> ${innings}</span>`).join('')
      : '<span class="text-muted small">No recorded defense</span>';
  }

  function usageNoteLabel(value) {
    const labels = {
      'High bench usage': 'More bench time recorded',
      'Limited position variety': 'Mostly used at one position',
      'Heavy catcher workload': 'Heavy catching workload',
      'Lower game availability': 'Lower game availability'
    };
    return labels[value] || value;
  }

  function flags(row) {
    return row.flags?.length
      ? row.flags.map(flag => `<span class="sv2-flag"><i class="bi bi-info-circle"></i>${esc(usageNoteLabel(flag))}</span>`).join('')
      : '<span class="sv2-good"><i class="bi bi-check-circle me-1"></i>No usage notes</span>';
  }

  function playerButton(row) {
    return `<button class="sv2-player" data-sv2-player="${row.player_id}">${esc(row.name)}</button>`;
  }

  function teamTotals(data) {
    const rows = data.player_usage || [];
    return {
      fieldInnings: rows.reduce((sum, row) => sum + Number(row.field_innings || 0), 0),
      benchInnings: rows.reduce((sum, row) => sum + Number(row.bench_innings || 0), 0),
      defensivePlayers: rows.filter(row => Number(row.field_innings || 0) > 0).length,
      multiPositionPlayers: rows.filter(row => Number(row.position_variety || 0) >= 3).length
    };
  }

  function overview(data) {
    const summary = data.summary || {};
    const totals = teamTotals(data);
    return `<div class="sv3-overview">
      <div class="sv3-title-row">
        <div>
          <div class="cb-kicker">Season dashboard</div>
          <h2>Team Stats & Usage</h2>
          <p>Defensive innings, position exposure, pitching workload, attendance, and roster balance in one place.</p>
        </div>
        <div class="sv3-source-note"><i class="bi bi-shield-check"></i><span>Live Game history is used whenever available.</span></div>
      </div>
      <div class="sv2-kpis">
        <div class="sv2-kpi"><small>Games in View</small><strong>${summary.games || 0}</strong><span>${summary.games_with_defensive_data || 0} with defensive data</span></div>
        <div class="sv2-kpi"><small>Recorded Game Innings</small><strong>${summary.defensive_innings_recorded || 0}</strong><span>team inning samples</span></div>
        <div class="sv2-kpi"><small>Player Field Innings</small><strong>${totals.fieldInnings}</strong><span>player inning appearances</span></div>
        <div class="sv2-kpi"><small>Bench Innings</small><strong>${totals.benchInnings}</strong><span>recorded bench appearances</span></div>
        <div class="sv2-kpi"><small>Avg. Available</small><strong>${val(summary.avg_available_per_game)}</strong><span>players per game</span></div>
        <div class="sv2-kpi"><small>Team Pitching IP</small><strong>${val(summary.team_pitching_innings)}</strong><span>${summary.team_pitching_pitches ?? 0} recorded pitches</span></div>
      </div>
    </div>`;
  }

  function balanceSnapshot(data) {
    const rows = (data.player_usage || []).filter(row => Number(row.field_innings || 0) + Number(row.bench_innings || 0) > 0);
    if (!rows.length) return '';

    const byField = [...rows].sort((a, b) => Number(a.field_innings || 0) - Number(b.field_innings || 0));
    const benchRows = rows.filter(row => row.bench_pct !== null && row.bench_pct !== undefined);
    const byBench = [...benchRows].sort((a, b) => Number(a.bench_pct || 0) - Number(b.bench_pct || 0));
    const minField = byField[0];
    const maxField = byField[byField.length - 1];
    const minBench = byBench[0];
    const maxBench = byBench[byBench.length - 1];
    const fieldSpread = Number(maxField.field_innings || 0) - Number(minField.field_innings || 0);
    const benchSpread = minBench && maxBench ? Number(maxBench.bench_pct || 0) - Number(minBench.bench_pct || 0) : null;
    const multiPosition = rows.filter(row => Number(row.position_variety || 0) >= 3).length;

    const body = `<div class="sv3-balance-grid" data-sv3-balance>
      <div class="sv3-balance-card"><small>Field inning spread</small><strong>${fieldSpread}</strong><span>${esc(minField.name)} ${minField.field_innings} → ${esc(maxField.name)} ${maxField.field_innings}</span></div>
      <div class="sv3-balance-card"><small>Bench % spread</small><strong>${benchSpread === null ? '—' : `${benchSpread} pts`}</strong><span>${minBench && maxBench ? `${esc(minBench.name)} ${minBench.bench_pct}% → ${esc(maxBench.name)} ${maxBench.bench_pct}%` : 'Not enough recorded bench data'}</span></div>
      <div class="sv3-balance-card"><small>3+ positions</small><strong>${multiPosition}/${rows.length}</strong><span>players with broad defensive exposure</span></div>
      <div class="sv3-balance-card"><small>Recorded defense</small><strong>${rows.filter(row => Number(row.field_innings || 0) > 0).length}/${rows.length}</strong><span>players with a field inning in this view</span></div>
    </div>`;
    return section('Roster Balance Snapshot', 'A quick comparison of opportunity and position exposure. These are coaching signals, not player grades.', body, 'sv3-balance-section');
  }

  function defensiveMatrix(data) {
    const rows = data.player_usage || [];
    const positions = allPositions(rows);
    const positionHeaders = positions.map(position => `<th class="sv3-pos-head" title="Recorded inning appearances at ${esc(position)}">${esc(position)}</th>`).join('');

    const desktopRows = rows.map(row => `<tr data-sv3-player-row="${row.player_id}">
      <td class="sv3-sticky-player">${playerButton(row)}<div class="sv3-row-sub">${row.defensive_games}/${row.available_games} defensive games</div></td>
      <td><strong>${row.field_innings}</strong></td>
      <td>${row.bench_innings}</td>
      <td>${val(row.bench_pct)}${row.bench_pct == null ? '' : '%'}</td>
      ${positions.map(position => `<td class="sv3-pos-cell" data-position="${esc(position)}">${Number(row.positions?.[position] || 0) || '—'}</td>`).join('')}
      <td>${row.position_variety}</td>
    </tr>`).join('');

    const desktop = `<div class="table-responsive sv2-desktop sv3-matrix-wrap"><table class="table table-hover sv2-table sv3-position-matrix" id="sv3PositionMatrix">
      <thead><tr><th class="sv3-sticky-player">Player</th><th>Field Inn.</th><th>Bench Inn.</th><th>Bench %</th>${positionHeaders}<th>Variety</th></tr></thead>
      <tbody>${desktopRows}</tbody>
    </table></div>`;

    const mobile = `<div class="sv2-mobile sv3-player-cards">${rows.map(row => `<article class="sv2-mcard sv3-player-card" data-sv3-player-card="${row.player_id}">
      <div class="sv2-mtop"><div><div class="sv2-mname">${playerButton(row)}</div><div class="sv2-meta">${row.defensive_games}/${row.available_games} defensive games · ${row.position_variety} positions</div></div><div>${flags(row)}</div></div>
      <div class="sv2-mgrid"><div class="sv2-mstat"><small>Field Inn.</small><strong>${row.field_innings}</strong></div><div class="sv2-mstat"><small>Bench Inn.</small><strong>${row.bench_innings}</strong></div><div class="sv2-mstat"><small>Bench %</small><strong>${val(row.bench_pct)}${row.bench_pct == null ? '' : '%'}</strong></div></div>
      <div class="sv3-mobile-positions"><small>Innings by position</small><div class="sv3-mobile-position-grid">${sortedPositionEntries(row).map(([position, innings]) => `<span><b>${esc(position)}</b><strong>${innings}</strong></span>`).join('') || '<em>No recorded defense</em>'}</div></div>
    </article>`).join('')}</div>`;

    return section(
      'Defensive Innings by Position',
      'Each number is a recorded inning appearance at that position. If a player changes positions mid-inning, both positions can receive one appearance for that inning.',
      desktop + mobile,
      'sv3-defense-section'
    );
  }

  function positionCoverage(data) {
    const rows = data.player_usage || [];
    const positions = allPositions(rows);
    if (!positions.length) return '';

    const body = `<div class="sv3-position-summary" data-sv3-position-summary>${positions.map(position => {
      const players = rows.filter(row => Number(row.positions?.[position] || 0) > 0);
      const innings = players.reduce((sum, row) => sum + Number(row.positions?.[position] || 0), 0);
      const leader = [...players].sort((a, b) => Number(b.positions?.[position] || 0) - Number(a.positions?.[position] || 0))[0];
      return `<div class="sv3-position-card"><div class="sv3-position-name">${esc(position)}</div><strong>${innings}</strong><span>inning appearances</span><small>${players.length} player${players.length === 1 ? '' : 's'}${leader ? ` · most: ${esc(leader.name)} (${leader.positions[position]})` : ''}</small></div>`;
    }).join('')}</div>`;

    return section('Team Position Coverage', 'See how much each defensive spot has been shared across the roster in the selected window.', body);
  }

  function pitching(data) {
    const rows = data.pitching_usage || [];
    if (!rows.length) return section('Pitching Usage', 'Game pitching only. Practice and lesson throws remain workload context on the Pitching page.', '<div class="sv2-empty">No game pitching outings are recorded in this view.</div>');
    const share = row => row.pitch_share_pct ?? row.outs_share_pct;
    const desktop = `<div class="table-responsive sv2-desktop"><table class="table table-hover sv2-table"><thead><tr><th>Pitcher</th><th>App</th><th>Starts</th><th>Relief</th><th>IP</th><th>Pitches</th><th>P/App</th><th>IP/App</th><th>Share</th></tr></thead><tbody>${rows.map(row => `<tr><td><strong>${esc(row.name)}</strong></td><td>${row.appearances}</td><td>${row.starts}</td><td>${row.relief_appearances}</td><td>${row.total_innings}${row.innings_history_complete ? '' : '*'}</td><td>${val(row.total_pitches)}</td><td>${val(row.pitches_per_appearance)}</td><td>${val(row.innings_per_appearance)}</td><td>${val(share(row))}${share(row) == null ? '' : '%'}</td></tr>`).join('')}</tbody></table></div>`;
    const mobile = `<div class="sv2-mobile">${rows.map(row => `<div class="sv2-mcard"><div class="sv2-mname">${esc(row.name)}</div><div class="sv2-mgrid"><div class="sv2-mstat"><small>Appearances</small><strong>${row.appearances}</strong></div><div class="sv2-mstat"><small>Starts</small><strong>${row.starts}</strong></div><div class="sv2-mstat"><small>Relief</small><strong>${row.relief_appearances}</strong></div><div class="sv2-mstat"><small>IP</small><strong>${row.total_innings}${row.innings_history_complete ? '' : '*'}</strong></div><div class="sv2-mstat"><small>Pitches</small><strong>${val(row.total_pitches)}</strong></div><div class="sv2-mstat"><small>Share</small><strong>${val(share(row))}${share(row) == null ? '' : '%'}</strong></div></div></div>`).join('')}</div>`;
    return section('Pitching Usage', 'Season game workload across the selected stats window. * means at least one appearance is missing innings data.', desktop + mobile);
  }

  function attendance(data) {
    const rows = data.attendance || [];
    const desktop = `<div class="table-responsive sv2-desktop"><table class="table table-hover sv2-table"><thead><tr><th>Player</th><th>Games</th><th>Game %</th><th>Missed</th><th>Practices</th><th>Practice %</th><th>Missed</th></tr></thead><tbody>${rows.map(row => `<tr><td><strong>${esc(row.name)}</strong></td><td>${row.games_present}/${row.games_total}</td><td>${val(row.game_attendance_pct)}${row.game_attendance_pct == null ? '' : '%'}</td><td>${row.games_missed}</td><td>${row.practices_present}/${row.practices_total}</td><td>${val(row.practice_attendance_pct)}${row.practice_attendance_pct == null ? '' : '%'}</td><td>${row.practices_missed}</td></tr>`).join('')}</tbody></table></div>`;
    const mobile = `<div class="sv2-mobile">${rows.map(row => `<div class="sv2-mcard"><div class="sv2-mname">${esc(row.name)}</div><div class="sv2-mgrid"><div class="sv2-mstat"><small>Games</small><strong>${row.games_present}/${row.games_total}</strong></div><div class="sv2-mstat"><small>Game %</small><strong>${val(row.game_attendance_pct)}${row.game_attendance_pct == null ? '' : '%'}</strong></div><div class="sv2-mstat"><small>Missed</small><strong>${row.games_missed}</strong></div><div class="sv2-mstat"><small>Practices</small><strong>${row.practices_present}/${row.practices_total}</strong></div><div class="sv2-mstat"><small>Practice %</small><strong>${val(row.practice_attendance_pct)}${row.practice_attendance_pct == null ? '' : '%'}</strong></div><div class="sv2-mstat"><small>Missed</small><strong>${row.practices_missed}</strong></div></div></div>`).join('')}</div>`;
    return section('Attendance', 'Percentages give missed counts context. Historical attendance assumes the current roster except where an absence was recorded.', desktop + mobile);
  }

  function insights(data) {
    const rows = data.insights || [];
    if (!rows.length) return '';
    return section('Coaching Insights', 'Usage patterns worth reviewing — not player rankings.', `<div class="sv2-insights">${rows.map(item => `<div class="sv2-insight ${item.level === 'attention' ? 'attention' : ''}"><strong>${esc(item.title)}</strong><span>${esc(item.detail)}</span></div>`).join('')}</div>`);
  }

  function quality(data) {
    const qualityData = data.data_quality || {};
    return section('Data Quality', 'Know what is actual Live Game history versus an older saved-plan estimate.', `<div class="sv2-quality"><span class="sv2-chip live">${qualityData.live_games || 0} Live Game</span><span class="sv2-chip legacy">${qualityData.legacy_games || 0} Legacy Estimate</span><span class="sv2-chip">${qualityData.live_innings || 0} live innings</span><span class="sv2-chip">${qualityData.legacy_innings || 0} legacy innings</span></div><div class="sv2-note">${esc(qualityData.note || '')}</div>`);
  }

  function legacyPositionGames(data) {
    const positionGames = data.raw?.position_game_appearances || {};
    const positions = [...new Set(Object.values(positionGames).flatMap(value => Object.keys(value || {})))].sort();
    if (!positions.length) return '';
    const table = `<div class="table-responsive"><table class="table table-sm sv2-table"><thead><tr><th>Player</th>${positions.map(position => `<th>${esc(position)}</th>`).join('')}</tr></thead><tbody>${(data.player_usage || []).map(row => `<tr><td><strong>${esc(row.name)}</strong></td>${positions.map(position => `<td>${positionGames[row.name]?.[position] || 0}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    return `<div class="accordion sv3-legacy-accordion" id="statsRaw"><div class="accordion-item"><h2 class="accordion-header"><button class="accordion-button collapsed" data-bs-toggle="collapse" data-bs-target="#statsRawPos">Legacy detail: games appeared by position</button></h2><div id="statsRawPos" class="accordion-collapse collapse"><div class="accordion-body">${table}<div class="sv2-note">This older view counts games in which a player appeared at each position. The defensive matrix above is the preferred inning-level view.</div></div></div></div></div>`;
  }

  function render(data, state) {
    return `<div data-stats-dashboard-v2 data-stats-dashboard-v3 class="sv2 sv3">
      ${overview(data)}
      <div class="sv2-toolbar"><div><div class="sv2-filters"><button class="btn btn-sm ${state.scope === 'season' ? 'btn-primary' : 'btn-outline-secondary'}" data-sv2-scope="season">Full Season</button><button class="btn btn-sm ${state.scope === 'last5' ? 'btn-primary' : 'btn-outline-secondary'}" data-sv2-scope="last5">Last 5 Games</button></div><div class="sv2-scope">Showing: <strong>${esc(data.scope?.label || 'Full Season')}</strong>${data.scope?.start ? ` · ${esc(data.scope.start)} to ${esc(data.scope.end || data.scope.start)}` : ''}</div></div><div class="sv2-range"><div><label>Start</label><input type="date" class="form-control form-control-sm" id="sv2Start" value="${esc(state.start)}"></div><div><label>End</label><input type="date" class="form-control form-control-sm" id="sv2End" value="${esc(state.end)}"></div><button class="btn btn-sm btn-outline-primary" id="sv2ApplyRange">Apply Range</button></div></div>
      ${balanceSnapshot(data)}
      ${defensiveMatrix(data)}
      ${positionCoverage(data)}
      ${insights(data)}
      ${pitching(data)}
      ${attendance(data)}
      ${quality(data)}
      ${legacyPositionGames(data)}
    </div>`;
  }

  function positionDetail(row) {
    const entries = sortedPositionEntries(row);
    if (!entries.length) return '<div class="sv2-note">No defensive position innings are recorded in this view.</div>';
    const max = Math.max(...entries.map(([, innings]) => Number(innings || 0)), 1);
    return `<div class="sv3-player-position-list" data-sv3-position-detail>${entries.map(([position, innings]) => `<div class="sv3-player-position-row"><strong>${esc(position)}</strong><div class="sv3-position-bar"><span style="width:${Math.max(8, Math.round(Number(innings || 0) / max * 100))}%"></span></div><b>${innings}</b></div>`).join('')}</div><div class="sv2-note">Position totals are inning appearances. A mid-inning position change can count one appearance at each position.</div>`;
  }

  function openPlayer(data, id) {
    const row = (data.player_usage || []).find(item => Number(item.player_id) === Number(id));
    if (!row) return;
    const attendanceRow = (data.attendance || []).find(item => Number(item.player_id) === Number(id)) || {};
    const pitchingRow = (data.pitching_usage || []).find(item => Number(item.player_id) === Number(id));
    let modal = document.getElementById('statsV2PlayerModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'statsV2PlayerModal';
      modal.className = 'modal fade stats-v2-player-modal';
      modal.tabIndex = -1;
      document.body.appendChild(modal);
    }

    modal.innerHTML = `<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><div class="cb-kicker">Player season usage</div><h5 class="modal-title">${esc(row.name)}</h5><div class="sv3-modal-sub">Selected window: ${esc(data.scope?.label || 'Full Season')}</div></div><button class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body">
      <div class="stats-kpis"><div class="stats-kpi"><small>Field Innings</small><strong>${row.field_innings}</strong></div><div class="stats-kpi"><small>Bench Innings</small><strong>${row.bench_innings}</strong></div><div class="stats-kpi"><small>Bench %</small><strong>${val(row.bench_pct)}${row.bench_pct == null ? '' : '%'}</strong></div><div class="stats-kpi"><small>Def. Games</small><strong>${row.defensive_games}/${row.available_games}</strong></div><div class="stats-kpi"><small>Positions</small><strong>${row.position_variety}</strong></div></div>
      <div class="stats-title">Defensive innings by position</div>${positionDetail(row)}
      <div class="stats-title">Attendance</div><div class="stats-kpis"><div class="stats-kpi"><small>Games</small><strong>${val(attendanceRow.games_present, 0)}/${val(attendanceRow.games_total, 0)} · ${val(attendanceRow.game_attendance_pct)}${attendanceRow.game_attendance_pct == null ? '' : '%'}</strong></div><div class="stats-kpi"><small>Practices</small><strong>${val(attendanceRow.practices_present, 0)}/${val(attendanceRow.practices_total, 0)} · ${val(attendanceRow.practice_attendance_pct)}${attendanceRow.practice_attendance_pct == null ? '' : '%'}</strong></div></div>
      <div class="stats-title">Pitching</div>${pitchingRow ? `<div class="stats-kpis"><div class="stats-kpi"><small>Appearances</small><strong>${pitchingRow.appearances}</strong></div><div class="stats-kpi"><small>Starts / Relief</small><strong>${pitchingRow.starts} / ${pitchingRow.relief_appearances}</strong></div><div class="stats-kpi"><small>IP</small><strong>${pitchingRow.total_innings}</strong></div><div class="stats-kpi"><small>Pitches</small><strong>${val(pitchingRow.total_pitches)}</strong></div><div class="stats-kpi"><small>Pitches / App</small><strong>${val(pitchingRow.pitches_per_appearance)}</strong></div></div>` : '<div class="sv2-note">No game pitching appearances in this view.</div>'}
      <div class="stats-title">Usage Notes</div><div>${flags(row)}</div>
      <div class="sv2-note mt-3">Live defensive innings: ${row.live_field_innings}. Legacy estimated innings: ${row.legacy_field_innings}. Usage Notes highlight patterns for review; they are not player ratings.</div>
    </div><div class="modal-footer"><button class="btn btn-secondary" data-bs-dismiss="modal">Close</button></div></div></div>`;
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  window.CoachStatsV2Renderer = { render, openPlayer };
})();
