(() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const val = (v, fallback='—') => (v === null || v === undefined || v === '') ? fallback : v;

  function section(title, sub, body){
    return `<section class="sv2-card"><div class="sv2-head"><h3>${esc(title)}</h3><p>${esc(sub)}</p></div><div class="sv2-body">${body}</div></section>`;
  }
  function positions(row){
    const entries=Object.entries(row.positions||{});
    return entries.length ? entries.map(([p,n])=>`<span class="sv2-pos">${esc(p)} ${n}</span>`).join('') : '<span class="text-muted small">No recorded defense</span>';
  }
  function flags(row){
    return row.flags?.length ? row.flags.map(f=>`<span class="sv2-flag"><i class="bi bi-flag"></i>${esc(f)}</span>`).join('') : '<span class="sv2-good"><i class="bi bi-check-circle me-1"></i>No usage flag</span>';
  }
  function playerButton(row){ return `<button class="sv2-player" data-sv2-player="${row.player_id}">${esc(row.name)}</button>`; }

  function playerUsage(data){
    const rows=data.player_usage||[];
    const desktop=`<div class="table-responsive sv2-desktop"><table class="table table-hover sv2-table"><thead><tr><th>Player</th><th>Avail. Games</th><th>Def. Games</th><th>Field Inn.</th><th>Bench Inn.</th><th>Bench %</th><th>Positions</th><th>Coach Flags</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${playerButton(r)}</td><td>${r.available_games}</td><td>${r.defensive_games}</td><td><strong>${r.field_innings}</strong></td><td>${r.bench_innings}</td><td>${val(r.bench_pct)}${r.bench_pct==null?'':'%'}</td><td>${positions(r)}</td><td>${flags(r)}</td></tr>`).join('')}</tbody></table></div>`;
    const mobile=`<div class="sv2-mobile">${rows.map(r=>`<div class="sv2-mcard"><div class="sv2-mtop"><div><div class="sv2-mname">${playerButton(r)}</div><div class="sv2-meta">${positions(r)}</div></div><div>${flags(r)}</div></div><div class="sv2-mgrid"><div class="sv2-mstat"><small>Field Inn.</small><strong>${r.field_innings}</strong></div><div class="sv2-mstat"><small>Bench Inn.</small><strong>${r.bench_innings}</strong></div><div class="sv2-mstat"><small>Bench %</small><strong>${val(r.bench_pct)}${r.bench_pct==null?'':'%'}</strong></div><div class="sv2-mstat"><small>Available</small><strong>${r.available_games}</strong></div><div class="sv2-mstat"><small>Def. Games</small><strong>${r.defensive_games}</strong></div><div class="sv2-mstat"><small>Pos. Variety</small><strong>${r.position_variety}</strong></div></div></div>`).join('')}</div>`;
    return section('Player Usage','Recorded defensive inning appearances and bench usage. Mid-inning substitutions count each player who appeared in that inning once.',desktop+mobile);
  }

  function pitching(data){
    const rows=data.pitching_usage||[];
    if(!rows.length) return section('Pitching Usage','Game pitching only. Practice and lesson throws remain workload context on the Pitching page.','<div class="sv2-empty">No game pitching outings are recorded in this view.</div>');
    const share=r=>r.pitch_share_pct??r.outs_share_pct;
    const desktop=`<div class="table-responsive sv2-desktop"><table class="table table-hover sv2-table"><thead><tr><th>Pitcher</th><th>App</th><th>Starts</th><th>Relief</th><th>IP</th><th>Pitches</th><th>P/App</th><th>IP/App</th><th>Share</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td>${r.appearances}</td><td>${r.starts}</td><td>${r.relief_appearances}</td><td>${r.total_innings}${r.innings_history_complete?'':'*'}</td><td>${r.total_pitches}</td><td>${val(r.pitches_per_appearance)}</td><td>${val(r.innings_per_appearance)}</td><td>${val(share(r))}${share(r)==null?'':'%'}</td></tr>`).join('')}</tbody></table></div>`;
    const mobile=`<div class="sv2-mobile">${rows.map(r=>`<div class="sv2-mcard"><div class="sv2-mname">${esc(r.name)}</div><div class="sv2-mgrid"><div class="sv2-mstat"><small>Appearances</small><strong>${r.appearances}</strong></div><div class="sv2-mstat"><small>Starts</small><strong>${r.starts}</strong></div><div class="sv2-mstat"><small>Relief</small><strong>${r.relief_appearances}</strong></div><div class="sv2-mstat"><small>IP</small><strong>${r.total_innings}${r.innings_history_complete?'':'*'}</strong></div><div class="sv2-mstat"><small>Pitches</small><strong>${r.total_pitches}</strong></div><div class="sv2-mstat"><small>Share</small><strong>${val(share(r))}${share(r)==null?'':'%'}</strong></div></div></div>`).join('')}</div>`;
    return section('Pitching Usage','Season game workload across the selected stats window. * means at least one appearance is missing innings data.',desktop+mobile);
  }

  function attendance(data){
    const rows=data.attendance||[];
    const desktop=`<div class="table-responsive sv2-desktop"><table class="table table-hover sv2-table"><thead><tr><th>Player</th><th>Games</th><th>Game %</th><th>Missed</th><th>Practices</th><th>Practice %</th><th>Missed</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td>${r.games_present}/${r.games_total}</td><td>${val(r.game_attendance_pct)}${r.game_attendance_pct==null?'':'%'}</td><td>${r.games_missed}</td><td>${r.practices_present}/${r.practices_total}</td><td>${val(r.practice_attendance_pct)}${r.practice_attendance_pct==null?'':'%'}</td><td>${r.practices_missed}</td></tr>`).join('')}</tbody></table></div>`;
    const mobile=`<div class="sv2-mobile">${rows.map(r=>`<div class="sv2-mcard"><div class="sv2-mname">${esc(r.name)}</div><div class="sv2-mgrid"><div class="sv2-mstat"><small>Games</small><strong>${r.games_present}/${r.games_total}</strong></div><div class="sv2-mstat"><small>Game %</small><strong>${val(r.game_attendance_pct)}${r.game_attendance_pct==null?'':'%'}</strong></div><div class="sv2-mstat"><small>Missed</small><strong>${r.games_missed}</strong></div><div class="sv2-mstat"><small>Practices</small><strong>${r.practices_present}/${r.practices_total}</strong></div><div class="sv2-mstat"><small>Practice %</small><strong>${val(r.practice_attendance_pct)}${r.practice_attendance_pct==null?'':'%'}</strong></div><div class="sv2-mstat"><small>Missed</small><strong>${r.practices_missed}</strong></div></div></div>`).join('')}</div>`;
    return section('Attendance','Percentages give missed counts context. Historical attendance assumes the current roster except where an absence was recorded.',desktop+mobile);
  }

  function insights(data){
    const rows=data.insights||[]; if(!rows.length) return '';
    return section('Coaching Insights','Usage patterns worth reviewing — not player rankings.',`<div class="sv2-insights">${rows.map(i=>`<div class="sv2-insight ${i.level==='attention'?'attention':''}"><strong>${esc(i.title)}</strong><span>${esc(i.detail)}</span></div>`).join('')}</div>`);
  }
  function quality(data){
    const q=data.data_quality||{};
    return section('Data Quality','Know what is actual Live Game history versus an older saved-plan estimate.',`<div class="sv2-quality"><span class="sv2-chip live">${q.live_games||0} Live Game</span><span class="sv2-chip legacy">${q.legacy_games||0} Legacy Estimate</span><span class="sv2-chip">${q.live_innings||0} live innings</span><span class="sv2-chip">${q.legacy_innings||0} legacy innings</span></div><div class="sv2-note">${esc(q.note||'')}</div>`);
  }
  function raw(data){
    const pos=data.raw?.position_game_appearances||{};
    const all=[...new Set(Object.values(pos).flatMap(x=>Object.keys(x||{})))].sort();
    if(!all.length) return '';
    const table=`<div class="table-responsive"><table class="table table-sm sv2-table"><thead><tr><th>Player</th>${all.map(p=>`<th>${esc(p)}</th>`).join('')}</tr></thead><tbody>${(data.player_usage||[]).map(r=>`<tr><td><strong>${esc(r.name)}</strong></td>${all.map(p=>`<td>${pos[r.name]?.[p]||0}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    return `<div class="accordion" id="statsRaw"><div class="accordion-item"><h2 class="accordion-header"><button class="accordion-button collapsed" data-bs-toggle="collapse" data-bs-target="#statsRawPos">Raw detail: games appeared by position</button></h2><div id="statsRawPos" class="accordion-collapse collapse"><div class="accordion-body">${table}<div class="sv2-note">This legacy-style table counts games in which a player appeared at each position. Use Player Usage above for inning-level rotation analysis.</div></div></div></div></div>`;
  }

  function render(data, state){
    const s=data.summary||{};
    return `<div data-stats-dashboard-v2 class="sv2"><div class="sv2-toolbar"><div><div class="sv2-filters"><button class="btn btn-sm ${state.scope==='season'?'btn-primary':'btn-outline-secondary'}" data-sv2-scope="season">Full Season</button><button class="btn btn-sm ${state.scope==='last5'?'btn-primary':'btn-outline-secondary'}" data-sv2-scope="last5">Last 5 Games</button></div><div class="sv2-scope">Showing: <strong>${esc(data.scope?.label||'Full Season')}</strong>${data.scope?.start?` · ${esc(data.scope.start)} to ${esc(data.scope.end||data.scope.start)}`:''}</div></div><div class="sv2-range"><div><label>Start</label><input type="date" class="form-control form-control-sm" id="sv2Start" value="${esc(state.start)}"></div><div><label>End</label><input type="date" class="form-control form-control-sm" id="sv2End" value="${esc(state.end)}"></div><button class="btn btn-sm btn-outline-primary" id="sv2ApplyRange">Apply Range</button></div></div><div class="sv2-kpis"><div class="sv2-kpi"><small>Games in View</small><strong>${s.games||0}</strong><span>${s.games_with_defensive_data||0} with defensive usage</span></div><div class="sv2-kpi"><small>Defensive Innings</small><strong>${s.defensive_innings_recorded||0}</strong><span>recorded inning samples</span></div><div class="sv2-kpi"><small>Team Attendance</small><strong>${val(s.team_attendance_pct)}${s.team_attendance_pct==null?'':'%'}</strong><span>game availability</span></div><div class="sv2-kpi"><small>Team Pitching IP</small><strong>${val(s.team_pitching_innings)}</strong><span>${s.team_pitching_pitches||0} recorded pitches</span></div><div class="sv2-kpi"><small>Avg. Available</small><strong>${val(s.avg_available_per_game)}</strong><span>players per game</span></div></div>${insights(data)}${playerUsage(data)}${pitching(data)}${attendance(data)}${quality(data)}${raw(data)}</div>`;
  }

  function openPlayer(data, id){
    const r=(data.player_usage||[]).find(x=>Number(x.player_id)===Number(id)); if(!r)return;
    const a=(data.attendance||[]).find(x=>Number(x.player_id)===Number(id))||{};
    const p=(data.pitching_usage||[]).find(x=>Number(x.player_id)===Number(id));
    let modal=document.getElementById('statsV2PlayerModal');
    if(!modal){modal=document.createElement('div');modal.id='statsV2PlayerModal';modal.className='modal fade stats-v2-player-modal';modal.tabIndex=-1;document.body.appendChild(modal);}
    modal.innerHTML=`<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><div class="cb-kicker">Player Season Usage</div><h5 class="modal-title">${esc(r.name)}</h5></div><button class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="stats-kpis"><div class="stats-kpi"><small>Field Innings</small><strong>${r.field_innings}</strong></div><div class="stats-kpi"><small>Bench Innings</small><strong>${r.bench_innings}</strong></div><div class="stats-kpi"><small>Bench %</small><strong>${val(r.bench_pct)}${r.bench_pct==null?'':'%'}</strong></div><div class="stats-kpi"><small>Def. Games</small><strong>${r.defensive_games}/${r.available_games}</strong></div></div><div class="stats-title">Positions</div><div>${positions(r)}</div><div class="stats-title">Attendance</div><div class="stats-kpis"><div class="stats-kpi"><small>Games</small><strong>${val(a.games_present,0)}/${val(a.games_total,0)} · ${val(a.game_attendance_pct)}${a.game_attendance_pct==null?'':'%'}</strong></div><div class="stats-kpi"><small>Practices</small><strong>${val(a.practices_present,0)}/${val(a.practices_total,0)} · ${val(a.practice_attendance_pct)}${a.practice_attendance_pct==null?'':'%'}</strong></div></div><div class="stats-title">Pitching</div>${p?`<div class="stats-kpis"><div class="stats-kpi"><small>Appearances</small><strong>${p.appearances}</strong></div><div class="stats-kpi"><small>Starts / Relief</small><strong>${p.starts} / ${p.relief_appearances}</strong></div><div class="stats-kpi"><small>IP</small><strong>${p.total_innings}</strong></div><div class="stats-kpi"><small>Pitches</small><strong>${p.total_pitches}</strong></div></div>`:'<div class="sv2-note">No game pitching appearances in this view.</div>'}<div class="stats-title">Coach Flags</div><div>${flags(r)}</div><div class="sv2-note mt-3">Live defensive innings: ${r.live_field_innings}. Legacy estimated innings: ${r.legacy_field_innings}.</div></div><div class="modal-footer"><button class="btn btn-secondary" data-bs-dismiss="modal">Close</button></div></div></div>`;
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  window.CoachStatsV2Renderer={render,openPlayer};
})();
